"""Functional ON/OFF control evidence, never a responsibility-kernel certification."""

import json
from pathlib import Path


def collect(plan):
    root = Path(plan["root"])
    results = [
        json.loads(p.read_text()) for p in sorted((root / "runs").glob("*/result.json"))
    ]
    planned = {f"{i}-{arm}" for i in range(len(plan["tasks"])) for arm in plan["arms"]}
    indexed = {r["episode"]: r for r in results}
    complete = set(indexed) == planned and len(indexed) == len(results)
    off = [r for r in results if r["arm"] == "vanilla"]
    gates = {
        "planned_matrix_scored": complete
        and all(r["status"] == "scored" for r in results),
        "procontract_off_observed": len(off) == len(plan["tasks"])
        and all(
            r.get("native_control") == {"arm": "off", "learning": False}
            and r.get("native_contract") is None
            and (r.get("native_cost") or {}).get("worker_rollouts") == 0
            for r in off
        ),
        "research_disabled": plan["limits"]["learning_launches"] == 0
        and not (root / "lineage").exists()
        and all(r.get("online") is None for r in results),
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "scope": "functional ProContract ON/OFF ablation with fixed seed P, not stock upstream defaults",
        "gates": {k: "PASS" if v else "FAIL" for k, v in gates.items()},
        "terminal_episodes": len(results),
        "unreported_episodes": sorted(planned - set(indexed)),
        "responsibility_kernel": "NOT_ESTABLISHED_BY_FUNCTIONAL_SCORES",
        "benefit": "NOT_ESTABLISHED",
    }
