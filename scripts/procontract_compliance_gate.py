"""Prospective H-only finite submission audit, independent of learned policies.

An accepted receipt is a fixed auditor's bounded judgment, not universal semantic
compliance. Missing evidence, failed transport and adverse findings stop the episode;
no score, learned reviewer or later replay can buy a second judgment.
"""

import procontract_ph_protocol as protocol
import procontract_store as store


class Inconclusive(RuntimeError):
    """The predeclared compliance job did not accept; this episode cannot advance."""


def enabled(host):
    if "ph_supervisor" not in host.terms:
        return False
    if (
        protocol.document(protocol.plan_path(host.terms)).get("protocol")
        != protocol.H_PROTOCOL
    ):
        return False
    selected = protocol.campaign_profile(host.camp, host.terms)
    return selected is not None and selected.protocol == protocol.H_PROTOCOL


def _check(host, phase, assignment, subjects, *, freeze):
    import procontract_compliance_adapter as adapter
    import procontract_fixed_auditor as auditor

    previous = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "fixed_auditor_gate"
        and e["body"].get("phase") == phase
    ]
    protocol.require(len(previous) <= 1, "ambiguous fixed auditor gate")
    protocol.require(previous or freeze, "missing frozen fixed auditor gate")
    if previous and previous[0].get("capture_failure"):
        protocol.require(
            previous[0]["assignment"] == assignment,
            "failed fixed auditor assignment changed",
        )
        raise Inconclusive(f"fixed auditor {phase}: frozen evidence unknown; no retry")
    packs, receipts, runs = [], [], []
    try:
        for version, task, purpose in subjects:
            root = host.camp / "runs" / f"{purpose}-{version[:12]}-{task}"
            run = root / "attempt-1"
            result = protocol.document(root / "result.json")
            protocol.require(
                (
                    result.get("version"),
                    result.get("task"),
                    result.get("purpose"),
                    result.get("run_dir"),
                    result.get("validity"),
                )
                == (version, task, purpose, str(run), "valid")
                and sorted(p.name for p in root.glob("attempt-*") if p.is_dir())
                == ["attempt-1"],
                "fixed auditor subject differs or has another attempt",
            )
            pack, evidence = adapter.build_run_pack(host, run)
            packs.append(pack)
            receipts.append(evidence)
            runs.append(str(run.relative_to(host.camp)))
    except Exception as error:
        if not previous:
            host.record(
                "selection",
                {
                    "role": "fixed_auditor_gate",
                    "phase": phase,
                    "assignment": assignment,
                    "outcome": "unknown",
                    "capture_failure": type(error).__name__[:100],
                },
            )
        raise Inconclusive(
            f"fixed auditor {phase}: evidence unknown; no retry"
        ) from error
    # The launch lane durably consumes one fixed phase claim before any inference.
    # Even a crash between that receipt and this event cannot authorize another job.
    receipt = (
        auditor.verify(host, phase, packs, receipts)
        if previous
        else auditor.execute(host, phase, packs, receipts)
    )
    protocol.require(
        isinstance(receipt, dict)
        and receipt.get("phase") == phase
        and receipt.get("outcome") in {"accepted", "rejected", "unknown"},
        "fixed auditor returned an invalid terminal receipt",
    )
    entry = {
        "role": "fixed_auditor_gate",
        "phase": phase,
        "assignment": assignment,
        "runs": runs,
        "artifact_digest": store.digest("fixed_auditor_artifacts", receipts),
        "receipt_digest": store.digest("fixed_auditor_receipt", receipt),
        "outcome": receipt["outcome"],
    }
    if previous:
        protocol.require(previous == [entry], "frozen fixed auditor evidence changed")
    else:
        host.record("selection", entry)
    if entry["outcome"] != "accepted":
        raise Inconclusive(
            f"fixed auditor {phase}: {entry['outcome']}; no advancement or retry"
        )
    return entry


def stream(host, batch, *, freeze=True):
    """Audit one committed serve/probe after measuring and before any learning."""
    if not enabled(host):
        return None
    number = batch.get("batch")
    protocol.require(type(number) is int and number in (1, 2, 3), "extra H audit phase")
    phase = ("initial_serve", "probe", "successor_serve")[number - 1]
    batches = host.batches()
    protocol.require(
        len(batches) >= number
        and batches[number - 1] == batch
        and batch["phase"] == ("probe" if number == 2 else "serve")
        and batch["tasks"] == [host.terms["stream"]["order"][number - 1]],
        "fixed auditor stream assignment differs",
    )
    return _check(
        host,
        phase,
        batch,
        [(batch["version"], batch["tasks"][0], "stream")],
        freeze=freeze,
    )


def authorize_learning(host, parent, instructions=None):
    """Verify before archive staging and the actual paid learned-role boundary."""
    if not enabled(host):
        return
    batches = host.batches()
    protocol.require(batches and len(batches) <= 3, "learning has no fixed H phase")
    batch = batches[-1]
    import procontract_succession as succession

    protocol.require(
        parent == batch["expected_incumbent"] == host.incumbent()
        and succession.incumbent_record(host)["seq"] == batch["expected_incumbent_seq"],
        "H learning authority differs",
    )
    if instructions is not None:
        allowed = {"analyst.md", "challenger.md"}
        if batch["batch"] in (1, 3):
            allowed.add("research.md")
        protocol.require(instructions in allowed, "H phase forbids this learning role")
    gates = [
        e["body"]
        for e in host.events("selection")
        if e["body"].get("role") == "fixed_auditor_gate"
    ]
    if any(entry.get("outcome") != "accepted" for entry in gates):
        raise Inconclusive(
            "fixed auditor already stopped this episode; no further learning"
        )
    journals = host.camp / "fixed-auditor"
    protocol.require(not journals.is_symlink(), "fixed auditor journals are redirected")
    if journals.exists():
        accepted = {entry["phase"] for entry in gates}
        for journal in journals.iterdir():
            protocol.require(
                not journal.is_symlink()
                and journal.is_dir()
                and journal.name in accepted,
                "unreconciled fixed auditor journal; no further learning",
            )
    stream(host, batch, freeze=False)


def authorize_confirmation(host):
    """Never let direct confirmation/paid callers bypass the two prior audit gates."""
    if not enabled(host):
        return
    batches = host.batches()
    protocol.require(len(batches) == 2, "confirmation needs the two H stream phases")
    for batch in batches:
        stream(host, batch, freeze=False)


def confirmation(host, candidate, plan, *, freeze=False):
    """Audit all eight fixed arms, including direct first-adoption revalidation."""
    if not enabled(host):
        return None
    import procontract_succession as succession

    authorize_confirmation(host)
    protocol.require(
        plan == succession.confirmation_plan(host, candidate)
        and plan["confirmation"] == candidate
        and plan["tasks"] == host.terms["pools"]["confirm"]
        and len(plan["tasks"]) == 4
        and len(set(plan["tasks"])) == 4
        and host.incumbent() == plan["incumbent"]
        and succession.incumbent_record(host)["seq"] == plan["incumbent_seq"],
        "fixed auditor confirmation assignment or authority differs",
    )
    return _check(
        host,
        "confirmation",
        plan,
        [
            (version, task, "confirm")
            for task in plan["tasks"]
            for version in (candidate, plan["incumbent"])
        ],
        freeze=freeze,
    )
