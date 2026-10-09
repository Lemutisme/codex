"""Future H-only native delivery eligibility, independent of score or compliance.

Unknown is not non-delivery. Neither presence in a completed native request nor an
acknowledgement proves attention, obedience, progress, or causal utility.
"""

import json

import procontract_h_action_evidence as action_evidence
import procontract_harness_program as harness
import procontract_native_trace_binding as binding
import procontract_ph_audit as audits
import procontract_ph_protocol as protocol
import procontract_store as store
import procontract_study as study


class Inconclusive(RuntimeError):
    """A frozen confirmation lacks admissible native H delivery; no retry is allowed."""


def inspect_run(host, run, version):
    """Recompute notice presence from the bound private raw trace, not its JSON label."""
    protocol.require(
        host.terms.get("native_notice_trace") == binding.PROFILE,
        "H notice proof needs the frozen native trace profile",
    )
    summary, manifest = (
        protocol.document(run / "run.json"),
        protocol.document(run / "manifest.json"),
    )
    program = harness.load(host.version_dir(version) / "bundle")
    if program is None:
        protocol.require(
            summary.get("delivery_budget") == {"reserve_secs": 0, "attempt": None},
            "unregistered H action cannot certify native delivery",
        )
        action, notice = {"outcome": "no_action"}, None
    else:
        action = action_evidence.probe(run, program, host.terms["task_deadline_secs"])
        notice = action["protocol_log"].pop("notice")
    attempt = (summary.get("delivery_budget") or {}).get("attempt")
    receipt = summary.get("native_notice_trace")
    delivery = binding.verify_notice(
        run,
        manifest,
        notice=notice,
        accepted_turn_id=attempt["turn_id"]
        if action["outcome"] == "accepted"
        else None,
        receipt=receipt,
    )
    protocol.require(
        isinstance(delivery, dict)
        and delivery.get("status") in {"observed", "unknown"},
        "invalid native notice verifier result",
    )
    return {"action": action, "native_notice_trace": receipt, "delivery": delivery}


def confirmation(host, candidate, plan, *, freeze=False):
    """Freeze every arm before deciding; adoption only revalidates an existing table."""
    import procontract_succession as succession

    protocol.require(
        plan == succession.confirmation_plan(host, candidate)
        and plan["confirmation"] == candidate
        and plan["incumbent"] != candidate
        and plan["tasks"] == host.terms["pools"]["confirm"]
        and len(plan["tasks"]) == 4,
        "native delivery needs the fixed confirmation plan",
    )
    audit = audits.Audit(host, study.verify(host.camp, host.terms, runner=host.runner))
    runs = {
        (version, task): host.camp
        / "runs"
        / f"confirm-{version[:12]}-{task}"
        / "attempt-1"
        for task in plan["tasks"]
        for version in (candidate, plan["incumbent"])
    }
    audit.paid(completed_runs={str(run) for run in runs.values()})
    arms = []
    for (version, task), run in runs.items():
        audit.task(version, task, "confirm")
        paid = audit.paid_runs[str(run)]
        protocol.require(
            paid["kind"] == "task"
            and paid["deadline_secs"] == host.terms["task_deadline_secs"]
            and audits.native_exited(protocol.document(run / "run.json")),
            "confirmation delivery lacks its terminal paid task",
        )
        arms.append(
            {
                "version": version,
                "task": task,
                "run": str(run.relative_to(host.camp)),
                "paid": paid,
                **inspect_run(host, run, version),
                "receipts": {
                    name: protocol.digest(run / name)
                    for name in (
                        "run.json",
                        "manifest.json",
                        "study-launch.json",
                        "../result.json",
                    )
                },
            }
        )
    evidence = {
        "schema": 1,
        "plan": plan,
        "arms": arms,
        "candidate_observed": sum(
            arm["version"] == candidate and arm["delivery"]["status"] == "observed"
            for arm in arms
        ),
        "binding_failures": [
            arm["run"]
            for arm in arms
            if arm["delivery"].get("reason") == "binding_verification_failed"
        ],
        "claim": "exact user notice in a new same-turn completed request; not attention or causal utility",
    }
    protocol.require(
        len(json.dumps(evidence, allow_nan=False).encode()) <= protocol.MAX_BYTES,
        "confirmation delivery evidence exceeds its bound",
    )
    entry = {
        "role": "h_confirmation_delivery",
        "digest": store.digest("h_confirmation_delivery", evidence),
        "evidence": evidence,
    }
    previous = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "h_confirmation_delivery"
    ]
    if not previous and freeze:
        host.record("selection", entry)
    else:
        protocol.require(
            previous == [entry], "confirmation delivery is missing, changed or replayed"
        )
    if evidence["binding_failures"]:
        raise Inconclusive(
            "H confirmation has invalid native trace bindings; no adoption or retry"
        )
    if not evidence["candidate_observed"]:
        raise Inconclusive(
            "H confirmation inconclusive: no candidate task observed the notice; no adoption or retry"
        )
    return entry
