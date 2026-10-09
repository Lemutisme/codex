"""Prospective H-only admission: notice in a completed native request, not obedience.

Only the predeclared single probe can unlock confirmation. Host-owned evidence is
frozen before exposure and rechecked at every paid confirmation and first adoption.
"""

import procontract_h_notice_delivery as notice_delivery
import procontract_harness_program as harness
import procontract_ph_audit as audits
import procontract_ph_protocol as protocol
import procontract_store as store
import procontract_study as study


class Inconclusive(RuntimeError):
    """A valid probe did not establish an accepted action; no retry is authorized."""


def enabled(host):
    if "ph_supervisor" not in host.terms:
        return False
    plan = protocol.document(protocol.plan_path(host.terms))
    if plan.get("protocol") != "single_candidate_h_v1":
        return False
    selected = protocol.campaign_profile(host.camp, host.terms)
    return selected is not None and selected.required_admission == "accepted_h_probe_v1"


def check(host, candidate, incumbent, *, freeze=False):
    """Freeze/revalidate one admission; return None for all historical profiles."""
    if not enabled(host):
        return None
    import procontract_compliance_gate as compliance

    compliance.authorize_confirmation(host)
    import procontract_rsi as rsi
    import procontract_succession as succession

    sealed = study.verify(host.camp, host.terms, runner=host.runner)
    batches = host.batches()
    protocol.require(
        len(batches) == 2, "H admission requires the single batch-two probe"
    )
    batch, task = batches[1], host.terms["stream"]["order"][1]
    sequence = succession.incumbent_record(host)["seq"]
    protocol.require(
        batch
        == {
            "batch": 2,
            "phase": "probe",
            "version": candidate,
            "expected_incumbent": incumbent,
            "expected_incumbent_seq": sequence,
            "tasks": [task],
        }
        and host.incumbent() == incumbent
        and candidate != incumbent,
        "H probe assignment or incumbent changed",
    )
    protocol.require(
        batches[0]
        == {
            "batch": 1,
            "phase": "serve",
            "version": incumbent,
            "expected_incumbent": incumbent,
            "expected_incumbent_seq": sequence,
            "tasks": [host.terms["stream"]["order"][0]],
        },
        "H root serve differs from its predeclared assignment",
    )
    versions = host.versions()
    for version in (candidate, incumbent):
        host.validate_harness(version)
    protocol.require(
        versions[candidate]["lineage"]
        == {"parent": incumbent, "proposed_by": incumbent}
        and versions[candidate].get("harness") != versions[incumbent].get("harness"),
        "H candidate lineage or intervention differs",
    )
    bundles = [host.version_dir(v) / "bundle" for v in (candidate, incumbent)]
    protocol.require(
        all(
            protocol.raw(bundles[0] / name) == protocol.raw(bundles[1] / name)
            for name in rsi.BUNDLE_FILES
        ),
        "H admission forbids changed P/M bytes",
    )
    selected = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "stream_policy"
    ]
    protocol.require(
        selected == [{"role": "stream_policy", "version": candidate, "batch": 2}],
        "H probe is not the single selected candidate",
    )
    run = host.camp / "runs" / f"stream-{candidate[:12]}-{task}" / "attempt-1"
    intents = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "stream_release_intent"
    ]
    protocol.require(
        len(intents) == 1, "H admission needs its qualified release intent"
    )
    intent = intents[0]
    protocol.require(
        intent
        == {
            "role": "stream_release_intent",
            "batch": 2,
            "version": candidate,
            "expected_incumbent": incumbent,
            "insight": intent.get("insight"),
        },
        "H release intent differs",
    )
    insight = next((i for i in host.insights() if i["k"] == intent["insight"]), None)
    protocol.require(
        insight is not None
        and insight["status"] == "qualified"
        and insight["verdict"] == "present"
        and insight["experiment"] == candidate,
        "H probe lacks a qualified challenged-present signature",
    )
    roles = []
    for role in ("analyst", "challenger"):
        roots = sorted((host.camp / "insight" / str(insight["k"])).glob(f"{role}-*"))
        protocol.require(roots, "H signature lacks its native research roles")
        roles.append(roots[-1])
    audit = audits.Audit(host, sealed)
    audit.paid(completed_runs={str(run), *(str(root / "run") for root in roles)})
    for root in roles:
        receipt = audit.paid_runs[str(root / "run")]
        protocol.require(
            receipt["kind"] == "learning"
            and receipt["deadline_secs"] == host.terms["analysis_deadline_secs"]
            and audits.native_exited(protocol.document(root / "run/run.json")),
            "H research role has no matching terminal paid profile",
        )
    analysis = audit.analysis(batch)
    protocol.require(analysis["k"] == intent["insight"], "H release signature changed")
    paid_probes = [
        path
        for path, identity in audit.reservation_identities.items()
        if (identity.get("version"), identity.get("role"), identity.get("instance"))
        == (candidate, "executor.md", task)
    ]
    protocol.require(paid_probes == [str(run)], "H probe has another paid attempt")
    paid = audit.paid_runs[str(run)]
    protocol.require(
        paid["kind"] == "task"
        and paid["deadline_secs"] == host.terms["task_deadline_secs"],
        "H probe paid profile differs",
    )
    audit.task(candidate, task, "stream")
    protocol.require(
        audits.native_exited(protocol.document(run / "run.json")),
        "H probe native exit is unknown",
    )
    program = harness.load(bundles[0])
    protocol.require(program is not None, "H admission requires a registered action")
    native = notice_delivery.inspect_run(host, run, candidate)
    action = native["action"]
    evidence = {
        "schema": 1,
        "candidate": candidate,
        "incumbent": incumbent,
        "incumbent_seq": sequence,
        "task": task,
        "run": str(run.relative_to(host.camp)),
        "paid": paid,
        "harness": {
            "sha256": program.digest,
            "interpreter": program.interpreter,
            "action": program.action,
        },
        **action,
        "native_notice": {
            key: native[key] for key in ("native_notice_trace", "delivery")
        },
        "release_intent": intent,
        "analysis": analysis,
        "research_receipts": {
            str(root.relative_to(host.camp)): {
                name: protocol.digest(root / name)
                for name in (
                    "run/run.json",
                    "run/manifest.json",
                    "run/study-launch.json",
                    "launch-claim.json",
                    "launch-exit.json",
                )
            }
            for root in roles
        },
        "receipts": {
            name: protocol.digest(run / name)
            for name in (
                "run.json",
                "manifest.json",
                "study-launch.json",
                "../result.json",
            )
        },
        "claim": "exact user notice in a new same-turn completed request; not attention, utility or compliance",
    }
    entry = {
        "role": "h_probe_admission",
        "digest": store.digest("h_probe_admission", evidence),
        "evidence": evidence,
    }
    previous = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "h_probe_admission"
    ]
    if not previous and freeze:
        host.record("selection", entry)
    else:
        protocol.require(
            previous == [entry], "H admission is missing, changed or replayed"
        )
    if action["outcome"] != "accepted":
        raise Inconclusive(
            f"H probe inconclusive: {action['outcome']}; no confirmation or retry"
        )
    if native["delivery"]["status"] != "observed":
        raise Inconclusive(
            "H probe native notice remains unknown; no confirmation or retry"
        )
    return entry


def authorize_task(host, run, manifest):
    """Fence every confirmation-pool task, including alternate caller paths."""
    if not enabled(host) or manifest["instance"] not in host.terms["pools"]["confirm"]:
        return
    import procontract_succession as succession

    batches = host.batches()
    protocol.require(len(batches) == 2, "confirmation has no predeclared H probe")
    candidate, incumbent = batches[1]["version"], batches[1]["expected_incumbent"]
    entry = check(host, candidate, incumbent)
    plan = succession.confirmation_plan(host, candidate)
    protocol.require(
        plan
        == {
            "confirmation": candidate,
            "incumbent": incumbent,
            "incumbent_seq": entry["evidence"]["incumbent_seq"],
            "tasks": host.terms["pools"]["confirm"],
            "gate": {
                key: host.terms["gates"][key]
                for key in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
            },
        },
        "confirmation differs from frozen H plan",
    )
    version, task = manifest["study_version"], manifest["instance"]
    protocol.require(
        version in {candidate, incumbent}
        and run == host.camp / "runs" / f"confirm-{version[:12]}-{task}" / "attempt-1",
        "H confirmation paid path differs or retries",
    )
    return entry
