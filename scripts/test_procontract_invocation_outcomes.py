import unittest
from procontract_invocation_outcomes import classify_execution, artifact_measurement_available, measurement_result, protocol_adjudication, execution_digest, measure_artifact_if_safe


def req(i=1, **kw):
    return dict(id=i, thread_id='review', turn_id='t', role='reviewer', started=1., finished=4.,
                http_status=200, terminal=None, failure='BrokenPipeError', **kw)

class OutcomesTests(unittest.TestCase):
    def test_cancel_bound_legacy_remains_unknown_origin_but_measurable(self):
        r=req();b=dict(request_id=1,thread_id='review',turn_id='t',cancelled_at=2.,closure_at=3.,effects_resolved=True,source_ids=['abort','receipt'])
        result=classify_execution([r],cancellation_bindings=[b],main_turn_status='failed')
        self.assertEqual(result['requests'][0]['classification'],'cancellation_correlated_legacy_transport')
        self.assertEqual(result['requests'][0]['failure_origin'],'unknown')
        self.assertTrue(result['protocol_review_needed'])
        self.assertTrue(artifact_measurement_available(effects_closed=True,artifact_frozen=True,artifact_complete=True,environment_qualified=True))
    def test_no_cancellation_is_not_ignored(self):
        self.assertEqual(classify_execution([req()])['requests'][0]['classification'],'unresolved_transport_failure')
    def test_wrong_turn_or_no_closure_cannot_bind(self):
        for turn,closed in [('other',True),('t',False)]:
            b=dict(request_id=1,thread_id='review',turn_id=turn,cancelled_at=2.,closure_at=3.,effects_resolved=closed,source_ids=['r'])
            self.assertEqual(classify_execution([req()],cancellation_bindings=[b])['requests'][0]['classification'],'unresolved_transport_failure')
    def test_provider_error_not_hidden_by_completed_main_or_cancel(self):
        for status,terminal in [(503,None),(200,'response.failed')]:
            r=req();r.update(http_status=status,terminal=terminal)
            result=classify_execution([r],main_turn_status='completed')
            self.assertEqual(result['requests'][0]['classification'],'unresolved_provider_failure')
    def test_same_turn_recovery_and_other_role_success_differ(self):
        a=req();a.update(http_status=503)
        b=req(2);b.update(terminal='response.completed',failure=None)
        self.assertEqual(classify_execution([a,b])['requests'][0]['classification'],'recovered_provider_failure')
        b['thread_id']='root'
        self.assertEqual(classify_execution([a,b])['requests'][0]['classification'],'unresolved_provider_failure')
    def test_deadline_tool_interruption_does_not_complete_main_turn(self):
        a=req();a['failure']='task_deadline'
        r=classify_execution([a],main_turn_status='failed')
        self.assertEqual(r['requests'][0]['classification'],'original_deadline');self.assertEqual(r['main_turn_status'],'failed')
    def test_no_deadline_response_and_owner_shutdown(self):
        a=req();a.update(terminal='response.completed',failure=None)
        self.assertEqual(classify_execution([a])['requests'][0]['classification'],'response_completed')
        a['transport_events']=[dict(kind='request_end',gateway_owner_shutdown_observed=True)]
        self.assertEqual(classify_execution([a])['requests'][0]['classification'],'gateway_owner_shutdown')
    def test_incomplete_artifact_or_unknown_effects_not_measurable(self):
        for field in ['effects_closed','artifact_frozen','artifact_complete','environment_qualified']:
            values=dict(effects_closed=True,artifact_frozen=True,artifact_complete=True,environment_qualified=True);values[field]=None
            self.assertFalse(artifact_measurement_available(**values))
    def test_skipped_private_cases_are_not_one_ninth_quality(self):
        r=measurement_result(expected=9,outcomes=[True],effects_closed=True)
        self.assertEqual(r['passed'],1);self.assertIsNone(r['value']);self.assertFalse(r['admissible'])
    def test_quality_and_protocol_admissibility_are_distinct(self):
        r=measurement_result(expected=2,outcomes=[True,False],effects_closed=True,protocol_eligible=None)
        self.assertEqual(r['value'],.5);self.assertFalse(r['admissible'])
        r=measurement_result(expected=2,outcomes=[False,False],effects_closed=True,protocol_eligible=True)
        self.assertEqual(r['value'],0);self.assertTrue(r['admissible'])

    def test_source_bound_owner_decision_can_restore_legacy_comparability(self):
        facts=classify_execution([req()],main_turn_status='failed')
        self.assertIsNone(protocol_adjudication(facts)['eligible'])
        record=dict(execution_sha256=execution_digest(facts),authority_ref='owner-grant',
                    evidence_refs=['cancel-receipt','closed-publication','original-deadline'],decision='eligible')
        judged=protocol_adjudication(facts,record,authorized_authority_refs=['owner-grant'])
        self.assertTrue(judged['eligible']);self.assertEqual(facts['requests'][0]['failure_origin'],'unknown')
        result=measurement_result(expected=2,outcomes=[True,True],effects_closed=True,protocol_eligible=judged['eligible'])
        self.assertEqual(result['value'],1);self.assertTrue(result['admissible'])
        for changed in [dict(record,execution_sha256='wrong'),dict(record,authority_ref='unadmitted'),dict(record,evidence_refs=[])]:
            with self.assertRaises(ValueError):protocol_adjudication(facts,changed,authorized_authority_refs=['owner-grant'])

    def test_safe_artifact_callback_is_not_gated_by_solver_failure(self):
        execution=classify_execution([req()],main_turn_status='failed')
        self.assertTrue(execution['protocol_review_needed'])
        calls=[]
        def measure():
            calls.append('admitted-measurement');return {'outcomes':[True,False],'effects_closed':True}
        r=measure_artifact_if_safe(effects_closed=True,artifact_frozen=True,artifact_complete=True,
            environment_qualified=True,expected=2,measure=measure)
        self.assertEqual(calls,['admitted-measurement']);self.assertEqual(r['value'],.5);self.assertFalse(r['admissible'])
        r=measure_artifact_if_safe(effects_closed=False,artifact_frozen=True,artifact_complete=True,
            environment_qualified=True,expected=2,measure=measure)
        self.assertEqual(len(calls),1);self.assertIsNone(r['value'])

    def test_transport_error_before_cancel_is_not_attributed_to_cancel(self):
        b=dict(request_id=1,thread_id='review',turn_id='t',cancelled_at=2.,closure_at=3.,effects_resolved=True,source_ids=['r'])
        r=req(transport_events=[dict(kind='transport_error',failure_origin='downstream_write',observed_at=1.5)])
        self.assertEqual(classify_execution([r],cancellation_bindings=[b])['requests'][0]['classification'],'unresolved_transport_failure')
        r['transport_events'][0]['observed_at']=3.5
        self.assertEqual(classify_execution([r],cancellation_bindings=[b])['requests'][0]['classification'],'cancelled_downstream')

    def test_existing_protocol_can_admit_normal_outcome_without_owner_click(self):
        r=req();r.update(failure=None,terminal='response.completed')
        execution=classify_execution([r],main_turn_status='completed')
        self.assertTrue(protocol_adjudication(execution,default_eligible=True)['eligible'])
        self.assertIsNone(protocol_adjudication(classify_execution([req()]),default_eligible=True)['eligible'])

if __name__=='__main__':unittest.main()
