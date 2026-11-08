"""Facts for invocation execution, safe artifact measurement and protocol eligibility.

No workflow, retries, grading or adoption is dispatched here. Cancellation bindings
must come from a trusted adapter's retained records, never an actor's free text.
Legacy transport origins remain unknown; correlations do not backfill raw ledgers.
"""
from __future__ import annotations


def _same_turn(left, right):
    return (bool(left.get('thread_id') and left.get('turn_id'))
            and (left['thread_id'], left['turn_id']) ==
            (right.get('thread_id'), right.get('turn_id')))


def _cancel_binding(request, bindings):
    for bound in bindings:
        if (bound.get('request_id') == request['id'] and _same_turn(request, bound)
                and bound.get('effects_resolved') is True and bound.get('source_ids')
                and request.get('started') is not None and request.get('finished') is not None
                and bound.get('cancelled_at') is not None and bound.get('closure_at') is not None
                and request['started'] <= bound['cancelled_at'] <= bound['closure_at'] <= request['finished']):
            return bound
    return None


def classify_execution(requests, *, cancellation_bindings=(), main_turn_status=None):
    """Classify observed requests without treating response completion as turn completion."""
    classified = []
    for request in requests:
        status = request.get('http_status')
        terminal = request.get('terminal')
        failure = request.get('failure')
        facts = request.get('transport_events', [])
        errors = [x for x in facts if x.get('kind') == 'transport_error']
        origin = errors[-1].get('failure_origin', 'unknown') if errors else 'unknown'
        error_at = errors[-1].get('observed_at') if errors else None
        deadline = failure == 'task_deadline' or any(x.get('original_deadline_observed') is True for x in facts)
        owner_stop = any(x.get('gateway_owner_shutdown_observed') is True for x in facts)
        provider_failure = (status is not None and status >= 400) or terminal == 'response.failed'
        later_success = any(other['id'] > request['id'] and _same_turn(request, other)
                            and other.get('terminal') == 'response.completed'
                            and (other.get('http_status') is None or other['http_status'] < 400)
                            for other in requests)
        bound = _cancel_binding(request, cancellation_bindings)
        # Provider evidence is never hidden by cancellation/deadline observations.
        if provider_failure:
            state = 'recovered_provider_failure' if later_success else 'unresolved_provider_failure'
        elif deadline:
            state = 'original_deadline'
        elif owner_stop:
            state = 'gateway_owner_shutdown'
        elif (bound and failure in ('BrokenPipeError', 'ConnectionResetError') and status == 200
              and origin in ('unknown', 'downstream_write')
              and (error_at is None or bound['cancelled_at'] <= error_at)):
            state = 'cancelled_downstream' if origin == 'downstream_write' and error_at is not None else 'cancellation_correlated_legacy_transport'
        elif failure:
            state = 'recovered_transport_failure' if later_success else 'unresolved_transport_failure'
        elif terminal == 'response.completed':
            state = 'response_completed'
        else:
            state = 'incomplete_response'
        classified.append({'request_id': request['id'], 'thread_id': request.get('thread_id'),
                           'turn_id': request.get('turn_id'), 'role': request.get('role'),
                           'classification': state, 'failure_origin': origin,
                           'http_status': status, 'terminal': terminal, 'exception_or_legacy_failure': failure,
                           'transport_errors': errors,
                           'cancel_binding': bound, 'original_deadline_observed': deadline,
                           'gateway_owner_shutdown_observed': owner_stop})
    uncertain = {'unresolved_provider_failure', 'unresolved_transport_failure', 'incomplete_response',
                 'cancellation_correlated_legacy_transport'}
    return {'schema': 'invocation-execution-observation/v1', 'requests': classified, 'main_turn_status': main_turn_status,
            'protocol_review_needed': not classified or any(x['classification'] in uncertain for x in classified),
            'scope': 'Execution facts/interpretation only; not artifact quality or automatic eligibility.'}


def artifact_measurement_available(*, effects_closed, artifact_frozen, artifact_complete,
                                   environment_qualified):
    """Independent of request/turn completion. Unknown booleans are not true."""
    return all(value is True for value in
               (effects_closed, artifact_frozen, artifact_complete, environment_qualified))


def measurement_result(*, expected, outcomes, effects_closed, protocol_eligible=None):
    """None denotes an unavailable/unexecuted test; never divide skipped tests into a score.

    protocol_eligible is a separately adjudicated experiment condition, not a
    decision inferred from a score. This function grants no adoption authority.
    """
    if type(expected) is not int or expected <= 0:
        raise ValueError('expected test count must be positive')
    if len(outcomes) > expected or any(x is not None and type(x) is not bool for x in outcomes):
        raise ValueError('invalid measurement outcomes')
    observed = sum(x is not None for x in outcomes)
    passed = sum(x is True for x in outcomes)
    complete = len(outcomes) == expected and observed == expected
    available = complete and effects_closed is True
    return {'passed': passed, 'observed': observed, 'eligible': expected, 'complete': complete,
            'value': passed / expected if available else None,
            'measurement_available': available, 'effects_resolved': effects_closed is True,
            'protocol_eligible': protocol_eligible,
            'admissible': available and protocol_eligible is True}


def execution_digest(execution):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(execution, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def protocol_adjudication(execution, record=None, *, authorized_authority_refs=(), default_eligible=None):
    """Accept a separate source-bound host/owner protocol decision without rewriting facts.

    authorized_authority_refs is supplied by the trusted adapter's existing
    authority interface, not by an actor. This grants no kernel adoption rights.
    Legacy unknown origin does not permanently bar an explicitly adjudicated case.
    """
    binding = execution_digest(execution)
    if record is None:
        # Existing host protocol can admit ordinary outcomes without a new owner decision.
        if default_eligible is not None and type(default_eligible) is not bool:
            raise ValueError('invalid protocol default')
        eligible = None if execution['protocol_review_needed'] else default_eligible
        return {'execution_sha256': binding, 'eligible': eligible, 'adjudication': None,
                'status': 'needs_review' if execution['protocol_review_needed'] else 'existing_protocol'}
    if record.get('execution_sha256') != binding:
        raise ValueError('adjudication concerns another execution')
    if (not isinstance(record.get('authority_ref'), str)
            or record['authority_ref'] not in authorized_authority_refs
            or not isinstance(record.get('evidence_refs'), list) or not record['evidence_refs']
            or not all(isinstance(ref, str) and ref for ref in record['evidence_refs'])):
        raise ValueError('adjudication lacks admitted authority or source references')
    decision = record.get('decision')
    if decision not in ('eligible', 'ineligible', 'needs_review'):
        raise ValueError('unknown protocol adjudication')
    return {'execution_sha256': binding, 'eligible': {'eligible': True, 'ineligible': False,
            'needs_review': None}[decision], 'status': decision, 'adjudication': dict(record)}


def measure_artifact_if_safe(*, effects_closed, artifact_frozen, artifact_complete,
                             environment_qualified, expected, measure, protocol_eligible=None):
    """Call an already-admitted measurement capability independently of solver labels.

    `measure` owns its own effects/receipts and returns outcomes plus closure.
    This adapter does not create a grant, retry or process owner. Partial returned
    observations are retained even if the new measurement effects are unresolved.
    """
    if not artifact_measurement_available(effects_closed=effects_closed,
            artifact_frozen=artifact_frozen, artifact_complete=artifact_complete,
            environment_qualified=environment_qualified):
        return measurement_result(expected=expected, outcomes=[], effects_closed=effects_closed,
                                  protocol_eligible=protocol_eligible)
    observed = measure()
    return measurement_result(expected=expected, outcomes=observed['outcomes'],
                              effects_closed=observed['effects_closed'], protocol_eligible=protocol_eligible)
