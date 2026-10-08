"""Compare updaters through their frozen descendants, then adopt only the updater.

The experiment is one paired episode, not a generalization or significance claim. Both
methods receive the same fresh observation and initial knowledge. Their descendants are
sealed before either sees a held-out score; task scores never stand in for method identity.
"""

import hashlib
import json
import math
import statistics
from pathlib import Path

import procontract_method_episode as episode
import procontract_store as store
import procontract_succession as succession

PROTOCOL = "paired_updater_v1"
TASK_FILES = ("executor.md", "drafter.md", "prober.md", "reviewer.md")
METHOD_FILES = ("analyst.md", "challenger.md", "research.md")
ARMS = ("control", "candidate")


def _phenotype(host, version):
    host.validate_harness(version)
    manifest = host.versions()[version]
    return {
        "binary": manifest["binary"],
        "model": manifest["model"],
        "harness": manifest.get("harness"),
        "policies": {name: manifest["bundle"][name] for name in TASK_FILES},
    }


def _event(host, role, plan):
    matches = [
        event["body"]
        for event in host.events("selection")
        if event["body"].get("role") == role
        and event["body"].get("confirmation") == plan["candidate"]
    ]
    if matches and (
        any(value != matches[0] for value in matches)
        or matches[0]["plan_digest"] != store.digest("method_plan", plan)
    ):
        raise RuntimeError("method receipt differs from its frozen plan")
    return matches[0] if matches else None


def _record(host, role, plan, **fields):
    body = {
        "role": role,
        "confirmation": plan["candidate"],
        "plan_digest": store.digest("method_plan", plan),
        **fields,
    }
    previous = _event(host, role, plan)
    if previous is None:
        host.record("selection", body)
    elif previous != body:
        raise RuntimeError("method receipt changed after publication")


def _gate(terms):
    gate = {
        key: terms["gates"][key]
        for key in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
    }
    count, wins, delta = (
        gate["confirm_tasks"],
        gate["confirm_min_wins"],
        gate["confirm_min_delta"],
    )
    if (
        type(count) is not int
        or count < 1
        or type(wins) is not int
        or not 1 <= wins <= count
        or type(delta) not in (int, float)
        or not math.isfinite(delta)
        or not 0 <= delta <= 1
    ):
        raise ValueError(
            "method confirmation requires positive counts and a nonnegative delta"
        )
    return gate


def _deadlines(terms):
    result = {
        "analyst": terms.get("analysis_deadline_secs", terms["research_deadline_secs"]),
        "challenger": terms.get(
            "analysis_deadline_secs", terms["research_deadline_secs"]
        ),
        "research": terms["research_deadline_secs"],
    }
    if any(type(value) is not int or value < 1 for value in result.values()):
        raise ValueError("method role deadlines must be positive integers")
    return result


def _validate_plan(host, plan):
    candidate, incumbent = plan["candidate"], plan["incumbent"]
    if (
        host.terms.get("stream", {}).get("method_confirmation") != "paired-descendants"
        or plan["class"] != PROTOCOL
        or plan["confirmation"] != candidate
        or plan["root_id"] != candidate
        or plan["gate"] != _gate(host.terms)
        or plan["deadlines"] != _deadlines(host.terms)
        or plan["role_attempts"] != 1
        or plan["task_budget"]
        != {
            "deadline_secs": host.terms["task_deadline_secs"],
            "attempts": succession.task_attempt_limit(host.terms),
        }
        or len(plan["tasks"]) != plan["gate"]["confirm_tasks"]
        or len(set(plan["tasks"])) != len(plan["tasks"])
        or not set(plan["tasks"]) <= set(host.terms["pools"]["confirm"])
    ):
        raise RuntimeError("method confirmation plan does not match its protocol")
    if _phenotype(host, candidate) != _phenotype(host, incumbent):
        raise RuntimeError("method confirmation requires an unchanged task phenotype")
    versions = host.versions()
    if versions[candidate]["lineage"]["parent"] != incumbent or all(
        versions[candidate]["bundle"][name] == versions[incumbent]["bundle"][name]
        for name in METHOD_FILES
    ):
        raise RuntimeError("method confirmation requires a new pure-method successor")
    events = host.events()
    registration = next(
        index
        for index, event in enumerate(events)
        if event["kind"] == "version" and event["body"]["id"] == candidate
    )
    assigned = [
        (index, event["body"])
        for index, event in enumerate(events)
        if event["kind"] == "assignment"
        and event["body"].get("batch") == plan["batch_id"]
    ]
    if len(assigned) != 1:
        raise RuntimeError("method confirmation has no unique fresh batch assignment")
    index, batch = assigned[0]
    if (
        registration >= index
        or batch["phase"] != "method_probe"
        or batch["method_candidate"] != candidate
        or batch["version"] != incumbent
        or batch["expected_incumbent"] != incumbent
        or batch["expected_incumbent_seq"] != plan["incumbent_seq"]
        or set(batch["tasks"]) & set(plan["tasks"])
        or plan["input"]["target"] != incumbent
        or plan["input"]["batch_id"] != plan["batch_id"]
        or plan["input"]["tasks"] != batch["tasks"]
    ):
        raise RuntimeError("method candidate was not frozen before its fresh episode")
    episode.verify_input(host, plan["input"])


def _sealed_arms(host, plan):
    sealed = _event(host, "method_descendants", plan)
    if sealed is None or set(sealed["arms"]) != set(ARMS):
        raise RuntimeError("both method descendants must be sealed before scoring")
    for arm, producer in zip(ARMS, (plan["incumbent"], plan["candidate"])):
        receipt = sealed["arms"][arm]
        episode.verify_arm(host, plan, producer, arm, receipt)
        if receipt["status"] != "qualified" or not receipt["descendant"]:
            raise RuntimeError("method descendant did not qualify")
    if _phenotype(host, sealed["arms"]["control"]["descendant"]) == _phenotype(
        host, sealed["arms"]["candidate"]["descendant"]
    ):
        raise RuntimeError("identical task descendants cannot certify a method change")
    return sealed["arms"]


def _evidence(host, plan, arms):
    """Read terminal receipts only; validation must never launch missing measurements."""
    purpose = f"method-confirm-{plan['candidate'][:16]}"
    runs, pairs = {}, {}
    for arm in ARMS:
        version = arms[arm]["descendant"]
        runs[arm] = {}
        for task in plan["tasks"]:
            path = (
                host.camp / "runs" / f"{purpose}-{version[:12]}-{task}" / "result.json"
            )
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("method score receipt is missing or not regular")
            raw = path.read_bytes()
            result = json.loads(raw)
            score = result.get("pass_rate")
            if (
                result.get("version") != version
                or result.get("task") != task
                or result.get("purpose") != purpose
                or Path(result.get("run_dir", ""))
                not in {
                    path.parent / f"attempt-{number}"
                    for number in range(1, plan["task_budget"]["attempts"] + 1)
                }
                or result.get("validity") != "valid"
                or type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise RuntimeError(
                    "method score receipt is invalid or belongs to another run"
                )
            host.validate_evaluator(result)
            host.validate_harness(version, Path(result["run_dir"]))
            runs[arm][task] = {
                "version": version,
                "task": task,
                "purpose": purpose,
                "run_dir": result["run_dir"],
                "pass_rate": score,
                "receipt_sha256": hashlib.sha256(raw).hexdigest(),
            }
    for task in plan["tasks"]:
        pairs[task] = [
            runs["candidate"][task]["pass_rate"],
            runs["control"][task]["pass_rate"],
        ]
    deltas = [candidate - control for candidate, control in pairs.values()]
    mean_delta = statistics.fmean(deltas)
    wins = sum(delta > 0 for delta in deltas)
    return {
        "class": PROTOCOL,
        "plan_digest": store.digest("method_plan", plan),
        "descendants": {arm: arms[arm]["descendant"] for arm in ARMS},
        "runs": runs,
        "pairs": pairs,
        "mean_delta": mean_delta,
        "wins": wins,
        "gate": plan["gate"],
        "passed": mean_delta > plan["gate"]["confirm_min_delta"]
        and wins >= plan["gate"]["confirm_min_wins"],
        "claim": "single_episode_empirical_updater_selection_not_general_superiority",
    }


def _basis(host, plan, evidence):
    return {
        "class": PROTOCOL,
        "plan_digest": store.digest("method_plan", plan),
        "tasks": plan["tasks"],
        "descendants": evidence["descendants"],
        "evaluator": host.adapter.evaluator(),
    }


def validate_adoption(host, plan):
    """Verify the updater's supported experiment before its first atomic publication."""
    if succession.confirmation_plan(host, plan["candidate"]) != plan:
        raise RuntimeError("method adoption has no matching frozen assignment")
    _validate_plan(host, plan)
    arms = _sealed_arms(host, plan)
    recorded = _event(host, "method_confirmation_evidence", plan)
    evidence = _evidence(host, plan, arms)
    if recorded is None or recorded["evidence"] != evidence or not evidence["passed"]:
        raise RuntimeError("method adoption has no intact passing downstream evidence")
    state = host.contract(f"adoption.{plan['candidate'][:16]}")
    coordinate = state["support"]["coordinate"] if state and state["support"] else {}
    if (
        coordinate.get("subject_hash") != plan["candidate"]
        or coordinate.get("evidence_hash") != store.digest("evidence", evidence)
        or coordinate.get("basis")
        != store.digest("basis", _basis(host, plan, evidence))
    ):
        raise RuntimeError("method adoption support does not bind this experiment")


def step(host, batch):
    """Resume one paired updater episode, reserving its holdout even when it fails."""
    candidate, incumbent = batch["method_candidate"], batch["expected_incumbent"]
    adoption = f"adoption.{candidate[:16]}"
    state = host.contract(adoption)
    if state and state["standing"] == "discharged":
        return "method confirmed and adopted"
    if state and state["standing"] == "released":
        return "method confirmation failed; its sources remain spent"
    if (
        host.incumbent() != incumbent
        or succession.incumbent_record(host)["seq"] != batch["expected_incumbent_seq"]
    ):
        raise RuntimeError("method confirmation incumbent changed")
    host.validate_evaluator()
    plan = succession.confirmation_plan(host, candidate)
    if plan is None:
        if state is not None:
            raise RuntimeError("method adoption has no frozen assignment")
        gate = _gate(host.terms)
        unavailable = set(host.used_confirmation_tasks()) | set(batch["tasks"])
        unavailable.update(result["task"] for result in host.observed().values())
        for event in host.events("exposure"):
            unavailable.update(event["body"]["sources"])
        fresh = [
            task for task in host.terms["pools"]["confirm"] if task not in unavailable
        ]
        if len(fresh) < gate["confirm_tasks"]:
            return "insufficient fresh method confirmation tasks"
        plan = {
            "confirmation": candidate,
            "candidate": candidate,
            "class": PROTOCOL,
            "incumbent": incumbent,
            "incumbent_seq": batch["expected_incumbent_seq"],
            "root_id": candidate,
            "batch_id": batch["batch"],
            "tasks": fresh[: gate["confirm_tasks"]],
            "gate": gate,
            "input": episode.freeze_input(host, batch),
            "deadlines": _deadlines(host.terms),
            "role_attempts": 1,
            "task_budget": {
                "deadline_secs": host.terms["task_deadline_secs"],
                "attempts": succession.task_attempt_limit(host.terms),
            },
        }
        _validate_plan(host, plan)
        host.record("assignment", plan)
    if (
        plan["batch_id"] != batch["batch"]
        or plan["incumbent"] != incumbent
        or plan["incumbent_seq"] != batch["expected_incumbent_seq"]
    ):
        raise RuntimeError("method confirmation belongs to another batch")
    _validate_plan(host, plan)
    host.issue(
        adoption,
        {"campaign": host.campaign_hash(), "method_plan": plan},
        {"class": PROTOCOL, "gate": plan["gate"], "claim": "one_paired_episode"},
        "delegate",
    )
    host.propose(adoption, candidate)
    sealed = _event(host, "method_descendants", plan)
    if sealed is None:
        arms = {}
        for arm, producer in zip(ARMS, (incumbent, candidate)):
            arms[arm] = episode.run_arm(host, plan, producer, arm)
            if arms[arm]["status"] != "qualified":
                reason = (
                    f"{arm} updater failed: {arms[arm].get('reason', 'unqualified')}"
                )
                _record(
                    host, "method_confirmation_rejected", plan, reason=reason, arms=arms
                )
                host.release(adoption, reason)
                return reason
        if _phenotype(host, arms["control"]["descendant"]) == _phenotype(
            host, arms["candidate"]["descendant"]
        ):
            reason = "identical task descendants provide no method intervention"
            _record(
                host, "method_confirmation_rejected", plan, reason=reason, arms=arms
            )
            host.release(adoption, reason)
            return reason
        _record(host, "method_descendants", plan, arms=arms)
    arms = _sealed_arms(host, plan)
    recorded = _event(host, "method_confirmation_evidence", plan)
    if recorded is None:
        view = f"confirmation:{candidate}"
        if not any(event["body"]["view"] == view for event in host.events("exposure")):
            host.record("exposure", {"view": view, "sources": plan["tasks"]})
        results = host.measure_all(
            [(arms[arm]["descendant"], task) for task in plan["tasks"] for arm in ARMS],
            f"method-confirm-{candidate[:16]}",
        )
        if any(result["validity"] != "valid" for result in results.values()):
            reason = "method confirmation has invalid downstream execution/evaluation"
            _record(
                host,
                "method_confirmation_invalid",
                plan,
                reason=reason,
                results=[
                    {
                        "version": version,
                        "task": task,
                        "validity": result["validity"],
                        "run_dir": result["run_dir"],
                    }
                    for (version, task), result in results.items()
                ],
            )
            raise RuntimeError(reason)
        evidence = _evidence(host, plan, arms)
        _record(host, "method_confirmation_evidence", plan, evidence=evidence)
    else:
        evidence = _evidence(host, plan, arms)
        if recorded["evidence"] != evidence:
            raise RuntimeError("method confirmation evidence changed")
    if not evidence["passed"]:
        host.release(
            adoption, f"paired updater gate failed: {evidence['mean_delta']:+.6f}"
        )
        return "method confirmation failed its strict downstream score gate"
    host.support(adoption, evidence, _basis(host, plan, evidence), "beyond")
    validate_adoption(host, plan)
    if host.terms["adoption"] == "presumed":
        host.adopt(candidate, presumed=True)
        return "method confirmed and adopted under the single-episode convention"
    return "method confirmed; awaiting the principal's adoption"


def write_feedback(host, archive):
    """Give later researchers bounded, attributed method outcomes, never future holdout plans."""
    for event in host.events("selection"):
        body = event["body"]
        if body.get("role") not in (
            "method_confirmation_evidence",
            "method_confirmation_rejected",
        ):
            continue
        candidate = body["confirmation"]
        plan = succession.confirmation_plan(host, candidate)
        if plan is None or plan.get("class") != PROTOCOL:
            continue
        evidence = body.get("evidence")
        report = {
            "class": PROTOCOL,
            "method": candidate,
            "comparator": plan["incumbent"],
            "common_input": plan["input"]["subject"],
            "selection_unit": "one paired updater episode; not independent method replications",
            "adoption_subject": "method only, not a descendant task policy",
            "outcome": "evaluated" if evidence else "no qualified paired update",
        }
        if evidence:
            report.update(
                descendants=evidence["descendants"],
                mean_delta=evidence["mean_delta"],
                wins=evidence["wins"],
                tasks=len(evidence["pairs"]),
                passed=evidence["passed"],
            )
        else:
            report["reason"] = str(body.get("reason", ""))[:240]
        data = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if len(data.encode("utf-8")) > 3500:
            raise RuntimeError("method feedback exceeds its bounded research view")
        target = archive / "method-trials" / f"{candidate}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(data + "\n", encoding="utf-8")
