"""Fresh confirmation and fenced adoption, shared by campaigns and streams.

The assignment is the durable experiment plan, not a success marker. Resumption uses
the same tasks and incumbent; it never buys another chance with a fresh holdout.
"""

import contextlib
import json
import sqlite3
import statistics

import procontract_h_admission as h_admission
import procontract_proposal_scope as proposal_scope
import procontract_store as store


def task_attempt_limit(terms: dict) -> int:
    """Legacy campaigns keep two attempts; a new explicit allowance is authoritative."""
    budgets = terms.get("budgets", {})
    if not isinstance(budgets, dict):
        raise ValueError("campaign budgets must be an object")
    limit = budgets.get("task_attempts", 2)
    if type(limit) is not int or limit not in (1, 2):
        raise ValueError("task_attempts must be 1 or 2")
    return limit


def receipt(path, value):
    """Publish a whole receipt; a failed write must never become a completion marker."""
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, indent=2) + "\n")
    pending.replace(path)


def record_run(host, result):
    """Repair an interrupted cache→ledger handoff without executing the task again."""
    if not any(
        e["body"].get("run_dir") == result["run_dir"] for e in host.events("execution")
    ):
        host.record("execution", {k: v for k, v in result.items() if k != "label"})
    if result.get("label") and not any(
        e["body"] == result["label"] for e in host.events("label")
    ):
        host.record("label", result["label"], epoch=result["label"]["evaluator_epoch"])
    return result


@contextlib.contextmanager
def writer(camp):
    """One workflow writer per campaign; process exit releases the lock, including after a crash."""
    camp.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(camp / "workflow.lock.sqlite", timeout=0)
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            raise RuntimeError("another workflow writer owns this campaign") from error
        yield
    finally:
        connection.close()


def incumbent_record(host):
    return next(
        (
            r
            for r in reversed(store.events(host.store))
            if r["event"]["kind"] == "selection"
            and r["event"]["body"].get("role") == "incumbent"
        ),
        None,
    )


def confirmation_plan(host, candidate):
    return next(
        (
            e["body"]
            for e in host.events("assignment")
            if e["body"].get("confirmation") == candidate
        ),
        None,
    )


def confirm(host, candidate, incumbent):
    adoption = f"adoption.{candidate[:16]}"
    state = host.contract(adoption)
    if state and state["standing"] == "released":
        return "confirmation failed; its sources remain spent"
    if state and state["standing"] == "discharged":
        return "confirmed and adopted"
    host.validate_evaluator()
    try:
        h_admission.check(host, candidate, incumbent, freeze=True)
    except h_admission.Inconclusive as error:
        return str(error)
    plan = confirmation_plan(host, candidate)
    if plan is not None and plan.get("class") == "paired_updater_v1":
        raise RuntimeError(
            "method confirmation must resume its paired updater workflow, not inherited task scores"
        )
    if plan is None:
        if state is not None:
            raise RuntimeError(
                "existing adoption has no frozen confirmation assignment; refusing legacy evidence"
            )
        if candidate == incumbent:
            return "the candidate is already incumbent"
        proposal_scope.assert_task_confirmation(host, candidate, incumbent)
        fresh = [
            t
            for t in host.terms["pools"]["confirm"]
            if t not in host.used_confirmation_tasks()
        ]
        count = host.terms["gates"]["confirm_tasks"]
        if count < 1 or len(fresh) < count:
            return "insufficient fresh confirmation tasks"
        current = incumbent_record(host)
        if host.incumbent() != incumbent:
            return "confirmation stale; incumbent changed"
        plan = {
            "confirmation": candidate,
            "incumbent": incumbent,
            "incumbent_seq": current["seq"],
            "tasks": fresh[:count],
            "gate": {
                k: host.terms["gates"][k]
                for k in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
            },
        }
        host.record("assignment", plan)
    else:
        proposal_scope.assert_task_confirmation(host, candidate, plan["incumbent"])
    if (
        host.incumbent() != plan["incumbent"]
        or incumbent_record(host)["seq"] != plan["incumbent_seq"]
    ):
        if state is not None:
            host.release(adoption, "the confirmation incumbent changed")
        return "confirmation stale; incumbent changed"
    tasks, gate = plan["tasks"], plan["gate"]
    host.issue(
        adoption,
        {
            "campaign": host.campaign_hash(),
            "candidate": candidate,
            "expected_incumbent": plan["incumbent"],
            "incumbent_seq": plan["incumbent_seq"],
            "gate": gate,
        },
        {
            "class": "paired_confirmation",
            "tasks": store.digest("pool", tasks),
            "gate": gate,
        },
        "delegate",
    )
    host.propose(adoption, candidate)
    view = f"confirmation:{candidate}"
    if not any(e["body"]["view"] == view for e in host.events("exposure")):
        host.record("exposure", {"view": view, "sources": tasks})
    if not host.contract(adoption)["support"]:
        results = host.measure_all(
            [(v, t) for t in tasks for v in (candidate, plan["incumbent"])], "confirm"
        )
        pairs = {
            t: (
                results[(candidate, t)]["pass_rate"],
                results[(plan["incumbent"], t)]["pass_rate"],
            )
            for t in tasks
            if all(
                results[(v, t)]["validity"] == "valid"
                for v in (candidate, plan["incumbent"])
            )
        }
        deltas = [c - i for c, i in pairs.values()]
        evidence = {
            "pairs": pairs,
            "mean_delta": statistics.fmean(deltas) if deltas else 0,
            "wins": sum(d > 0 for d in deltas),
            "gate": gate,
        }
        if len(pairs) != gate["confirm_tasks"] or (
            evidence["mean_delta"] < gate["confirm_min_delta"]
            or evidence["wins"] < gate["confirm_min_wins"]
        ):
            host.release(adoption, f"confirmation gate failed: {evidence}")
            return "confirmation failed"
        host.support(
            adoption,
            evidence,
            {"tasks": tasks, "evaluator": host.adapter.evaluator()},
            "beyond",
        )
    if host.terms["adoption"] == "presumed":
        host.adopt(candidate, presumed=True)
        return "confirmed and adopted under the campaign's convention"
    return "confirmed; awaiting the principal's adoption"


def adopt(host, candidate, presumed=False):
    adoption = f"adoption.{candidate[:16]}"
    state = host.contract(adoption)
    if not state or not state["support"]:
        raise RuntimeError(f"{candidate[:12]} has no supported adoption")
    if state["standing"] == "discharged":
        return f"{candidate[:12]} was already adopted"
    if presumed and host.terms["adoption"] != "presumed":
        raise RuntimeError("the campaign requires explicit adoption")
    plan = confirmation_plan(host, candidate)
    bootstrap = any(
        e["body"]["contract_id"] == adoption and e["body"]["terms"].get("bootstrap")
        for e in host.events("issue")
    )
    if plan is None and not bootstrap:
        raise RuntimeError("adoption needs a frozen confirmation assignment")
    if plan is not None and host.incumbent() != plan["incumbent"]:
        raise RuntimeError("the confirmation incumbent is no longer authorized")
    if h_admission.enabled(host):
        if bootstrap:
            if (
                plan is not None
                or set(host.versions()) != {candidate}
                or host.versions()[candidate]["lineage"]
                != {"parent": None, "proposed_by": "operator"}
                or incumbent_record(host) is not None
            ):
                raise RuntimeError(
                    "only the first operator root may bootstrap an H episode"
                )
        else:
            h_admission.check(host, candidate, plan["incumbent"])
    # Support names frozen bytes. Verify them before first publication, not when replaying an
    # already settled decision: historical adoption remains readable after artifact cleanup.
    host.validate_harness(candidate)
    host.validate_evaluator()
    if plan is not None and plan.get("class") == "paired_updater_v1":
        import procontract_method_confirmation as method_confirmation

        method_confirmation.validate_adoption(host, plan)
    elif plan is not None:
        proposal_scope.assert_task_confirmation(host, candidate, plan["incumbent"])
    coordinate = state["support"]["coordinate"]
    if coordinate["evaluator_digest"] != store.digest(
        "evaluator", host.adapter.evaluator()
    ) or coordinate["environment_digest"] != store.digest(
        "environment", host.adapter.environment()
    ):
        raise RuntimeError(
            "adoption evidence belongs to a different evaluator or environment"
        )
    decision = host.presumed() if presumed else {"type": "explicit"}
    command = {
        "contract_id": adoption,
        "expected_version": state["version"],
        "role": "settler",
        "provenance": "delegate" if presumed else "human",
        "command": {
            "type": "discharge",
            "coordinate": state["support"]["coordinate"],
            "attestation": store.digest("attestation", f"adopt {candidate}"),
            "decision": decision,
        },
    }
    store.adopt(
        host.store,
        f"adopt:{adoption}",
        command,
        plan["incumbent_seq"] if plan else None,
        host.identities(),
    )
    return f"{candidate[:12]} is the incumbent"
