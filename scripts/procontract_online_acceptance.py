"""Read-only finite evidence gates. Never grants adoption, a retry, or a gain claim."""

import json
import hashlib
from pathlib import Path
import sqlite3

from procontract_online import digest, encoded
import procontract_harness_program as harness
from procontract_online_worker import Packet


def assess(plan, results, events, versions, *, evidence_kind):
    if evidence_kind not in ("live", "synthetic"):
        raise ValueError("evidence domain must be explicit")
    planned = {f"{i}-{arm}" for i in range(len(plan["tasks"])) for arm in plan["arms"]}
    indexed = {result["episode"]: result for result in results}
    records = {event["key"]: event["body"] for event in events}
    episodes = [event["body"] for event in events if event["kind"] == "episode"]
    links, h_changes, rewards, policy_after_feedback = [], [], [], []
    previous_reward = None
    for episode in episodes:
        key = episode["episode"]
        chosen = episode["selection"]
        if (
            previous_reward
            and chosen.get("purpose") == "policy"
            and indexed.get(key, {}).get("status") == "scored"
            and chosen.get("policy_alternatives")
            == previous_reward["selection"]["next_distribution"]
        ):
            policy_after_feedback.append(key)
        result = indexed.get(key, {})
        reward = records.get(f"reward:{key}")
        if not reward or result.get("status") != "scored":
            continue
        outcome = result.get("outcome") or {}
        if (
            result.get("learning_reward") != reward
            or any(
                outcome.get(k) != reward.get(k)
                for k in ("resolved", "total", "submission_sha256")
            )
            or outcome.get("valid") is not True
            or reward["selection"]["credited_version"] != episode["parent"]
            or reward["selection"]["propensity"] != chosen["probability"]
        ):
            continue
        rewards.append(key)
        previous_reward = reward
        claim, proposal = records.get(f"claim:{key}"), records.get(f"proposal:{key}")
        trial = result.get("online") or {}
        worker = trial.get("research") or {}
        binding = worker.get("input_binding") or {}
        trace = result.get("native_context_evidence") or {}
        if (
            not claim
            or not proposal
            or worker.get("status") != "completed"
            or type(worker.get("native_exit")) is not int
            or worker["native_exit"] != 0
            or binding.get("packet_sha256") != claim["packet_sha256"]
            or binding.get("prompt_sha256")
            != hashlib.sha256(Packet(claim["packet"]).prompt().encode()).hexdigest()
            or claim["packet_sha256"] != digest(claim["packet"])
            or binding.get("producer_method") != claim["producer_method"]
            or claim["producer_method"]
            != digest(claim["packet"]["program"]["research"])
            or (trace.get("evidence") or {}).get("status") != "observed"
            or reward["selection"]["evidence"]["input_witness"] != digest(trace)
            or ((trial.get("dispatch") or {}).get("attempt") or {}).get("outcome")
            != "accepted"
        ):
            continue
        parent, child = episode["parent"], proposal["candidate"]
        if (
            child != reward["experimental_version"]
            or child != trial.get("candidate")
            or claim["packet"]["parent"] != parent
            or proposal["parent"] != parent
            or proposal["producer_method"] != claim["producer_method"]
            or reward["producer_method"] != claim["producer_method"]
            or parent not in versions
            or child not in versions
            or digest(versions[parent]) != parent
            or digest(versions[child]) != child
            or claim["packet"]["program"] != versions[parent]
        ):
            continue
        links.append({"episode": key, "parent": parent, "child": child})
        changed = trial.get("harness_decision_difference")
        if changed:
            try:
                before = harness.parse(encoded(versions[parent]["harness"]))
                after = harness.parse(encoded(versions[child]["harness"]))
                if (
                    changed.get("eligibility")
                    == {"eligible": True, "reason": "eligible"}
                    and changed["parent"] == before.digest
                    and changed["candidate"] == after.digest
                    and before.evaluate(changed["facts"]) == changed["parent_decision"]
                    and after.evaluate(changed["facts"])
                    == changed["candidate_decision"]
                    and changed["parent_decision"] != changed["candidate_decision"]
                ):
                    h_changes.append(key)
            except (KeyError, TypeError, ValueError):
                pass
    recursive = [
        (a["episode"], b["episode"])
        for i, a in enumerate(links)
        for b in links[i + 1 :]
        if a["child"] == b["parent"]
        and versions[a["parent"]]["research"] != versions[a["child"]]["research"]
    ]
    complete = (
        set(indexed) == planned
        and len(indexed) == len(results)
        and all(r.get("status") in ("scored", "failed") for r in results)
    )
    gates = {
        "planned_matrix_terminal": complete,
        "two_recursive_method_generations": bool(recursive),
        "changed_harness_decision_executed": bool(h_changes),
        "external_rewards": len(rewards) >= 2,
        "unforced_selection_after_feedback": bool(policy_after_feedback),
    }
    return {
        "evidence_kind": evidence_kind,
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gates": {k: "PASS" if v else "FAIL" for k, v in gates.items()},
        "planned_episodes": len(planned),
        "terminal_episodes": len(results),
        "failed_episodes": [
            r["episode"] for r in results if r.get("status") == "failed"
        ],
        "unreported_episodes": sorted(planned - set(indexed)),
        "recursive_links": recursive,
        "harness_witnesses": h_changes,
        "reward_episodes": rewards,
        "policy_after_feedback": policy_after_feedback,
        "benefit": "NOT_ESTABLISHED",
        "interactive_product": "NOT_TESTED",
        "scope": "mechanism evidence only; synthetic providers/graders do not prove live RSI or improvement",
    }


def collect(plan):
    root = Path(plan["root"])
    results = [
        json.loads(path.read_text())
        for path in sorted((root / "runs").glob("*/result.json"))
    ]
    events, versions = [], {}
    database = root / "lineage/lineage.sqlite"
    if database.exists():
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            events = [
                {"key": key, "kind": kind, "body": json.loads(body)}
                for key, kind, body in db.execute(
                    "SELECT key,kind,body FROM events ORDER BY seq"
                )
            ]
            versions = {
                key: json.loads(body)
                for key, body in db.execute("SELECT id,body FROM versions")
            }
        finally:
            db.close()
    return assess(plan, results, events, versions, evidence_kind="live")
