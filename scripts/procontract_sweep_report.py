"""Descriptive full-matrix reporting; missing outcomes are never imputed as zeros."""

import csv
import json
from pathlib import Path


def collect(plan):
    root = Path(plan["root"])
    rows = []
    for index, task in enumerate(plan["tasks"]):
        run = root / "runs" / f"{index}-successor"
        result = (
            json.loads((run / "result.json").read_text())
            if (run / "result.json").is_file()
            else {}
        )
        native = (
            json.loads((run / "run.json").read_text())
            if (run / "run.json").is_file()
            else {}
        )
        outcome = result.get("outcome") or {}
        succession = result.get("native_succession") or native.get("succession") or {}
        cost = result.get("native_cost") or native.get("cost") or {}
        quality = (
            outcome.get("pass_rate")
            if result.get("status") == "scored" and outcome.get("valid") is True
            else None
        )
        rows.append(
            {
                "instance": task,
                "episode": f"{index}-successor",
                "status": result.get("status", "pending"),
                "resolved": outcome.get("resolved"),
                "total": outcome.get("total"),
                "fraction": quality,
                "contract_phase": (
                    result.get("native_contract") or native.get("status") or {}
                ).get("phase"),
                "native_secs": native.get("elapsed_secs"),
                "grading_secs": result.get("grading_elapsed_secs"),
                "successor_sessions_reserved": succession.get("launches"),
                "successor_rollouts_recorded": (
                    cost.get("successors_included_in_workers") or {}
                ).get("rollouts"),
                "recorded_total_tokens": sum(
                    (cost.get(k) or {}).get("total_tokens", 0)
                    for k in ("executor", "workers")
                )
                if cost
                else None,
            }
        )
    scored = [r for r in rows if r["fraction"] is not None]
    known_sum = sum(r["fraction"] for r in scored)
    missing = len(rows) - len(scored)
    return {
        "planned": len(rows),
        "scored": len(scored),
        "missing_or_pending": missing,
        "scored_only_macro_fraction": known_sum / len(scored) if scored else None,
        "planned_macro_bounds": [
            known_sum / len(rows),
            (known_sum + missing) / len(rows),
        ],
        "fully_resolved": sum(r["fraction"] == 1 for r in scored),
        "at_least_95_percent": sum(r["fraction"] >= 0.95 for r in scored),
        "contracts_supported": sum(r["contract_phase"] == "supported" for r in rows),
        "benefit": "NOT_ESTABLISHED_BY_SINGLE_ARM",
        "rows": rows,
        "scope": "new version only; historical comparisons descriptive; bounds are mathematical bounds, not imputed scores or confidence intervals; successor usage is already included in worker totals",
    }


def write(plan):
    root = Path(plan["root"])
    summary = collect(plan)
    temporary = root / "SUMMARY.partial"
    temporary.write_text(json.dumps(summary, indent=2) + "\n")
    temporary.replace(root / "SUMMARY.json")
    with (root / "results.partial").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=list(summary["rows"][0]))
        writer.writeheader()
        writer.writerows(summary["rows"])
    (root / "results.partial").replace(root / "results.csv")
    return summary
