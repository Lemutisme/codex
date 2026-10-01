#!/usr/bin/env python3
"""M0 report: estimands with task-clustered bootstrap CIs (RSI spec §10 item 11)."""

import argparse
import json
import random
import statistics
import subprocess
from pathlib import Path

import procontract_store as store


def clustered_ci(
    values: dict[str, list[float]], seed: int, resamples: int = 2000
) -> tuple[float, float, float]:
    flat = [v for vs in values.values() for v in vs]
    point = sum(flat) / len(flat)
    rng = random.Random(seed)
    tasks = sorted(values)
    means = []
    for _ in range(resamples):
        sample = [
            v for task in (rng.choice(tasks) for _ in tasks) for v in values[task]
        ]
        means.append(sum(sample) / len(sample))
    means.sort()
    return point, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def _proportion(rows: list[dict], predicate, seed: int) -> dict:
    values: dict[str, list[float]] = {}
    for row in rows:
        values.setdefault(row["task"], []).append(1.0 if predicate(row) else 0.0)
    if not values:
        return {"point": None, "low": None, "high": None, "n": 0}
    point, low, high = clustered_ci(values, seed)
    return {
        "point": point,
        "low": low,
        "high": high,
        "n": sum(len(v) for v in values.values()),
    }


def estimands(rows: list[dict], nulls: dict[str, float], seed: int = 0) -> dict:
    valid = [r for r in rows if r["validity"] == "valid" and r["solved"] is not None]
    judged = [r for r in valid if r["role"] == "judged"]
    supported = [r for r in judged if r["verdict"] == "support"]
    defeats = [r for r in judged if r["verdict"] == "defeat"]
    checked_defeats = [r for r in defeats if r["validated"] is not None]
    finals = [r for r in rows if r["role"] == "final_workspace"]
    by_arm = {}
    for arm in sorted({r["arm"] for r in finals}, reverse=True):
        arm_rows = [r for r in finals if r["arm"] == arm]
        by_arm[arm] = {
            "solved": sum(
                1 for r in arm_rows if r["validity"] == "valid" and r["solved"]
            ),
            "valid": sum(1 for r in arm_rows if r["validity"] == "valid"),
            "invalid": sum(1 for r in arm_rows if r["validity"] != "valid"),
        }
    above_null = {}
    for arm in by_arm:
        gaps = [
            r["score"] - nulls[r["task"]]
            for r in finals
            if r["arm"] == arm
            and r["validity"] == "valid"
            and r["score"] is not None
            and r["task"] in nulls
        ]
        above_null[arm] = statistics.fmean(gaps) if gaps else None
    p = _proportion(supported, lambda r: r["solved"], seed)
    missed = dict(
        p,
        point=None if p["point"] is None else 1 - p["point"],
        low=None if p["high"] is None else 1 - p["high"],
        high=None if p["low"] is None else 1 - p["low"],
    )
    return {
        "solved_by_arm": by_arm,
        "p_solved_given_supported": p,
        "missed_defect_rate": missed,
        "validated_defeats": _proportion(
            checked_defeats, lambda r: r["validated"], seed
        ),
        "disagreement": _proportion(defeats, lambda r: r["solved"], seed),
        "excluded": {
            "invalid": sum(1 for r in rows if r["validity"] != "valid"),
            "unknown": sum(
                1 for r in rows if r["validity"] == "valid" and r["solved"] is None
            ),
        },
        "score_above_null": above_null,
    }


def _score(score: str | None) -> float | None:
    if score == "✅":
        return 100.0
    return float(score) if score and score.isdigit() else None


def load_rows(batch_dir: Path) -> tuple[list[dict], dict[str, float]]:
    events = [record["event"] for record in store.events(batch_dir / "store")]
    assignments = {
        e["body"]["run_id"]: e["body"] for e in events if e["kind"] == "assignment"
    }
    costs = {
        e["body"]["run_id"]: e["body"].get("cost", {})
        for e in events
        if e["kind"] == "execution"
    }
    revalidation = batch_dir / "revalidation.json"
    validated = json.loads(revalidation.read_text()) if revalidation.exists() else {}
    rows, nulls = [], {}
    for event in events:
        if event["kind"] != "label":
            continue
        body = event["body"]
        outcome = body.get("outcome") or {}
        role = body["role"]
        if role["kind"] == "null_sentinel":
            if _score(outcome.get("score")) is not None:
                nulls[body["instance"]] = _score(outcome.get("score"))
            continue
        run = assignments.get(body["run_id"], {})
        cost = costs.get(body["run_id"], {})
        rows.append(
            {
                "task": body["instance"],
                "arm": run.get("arm"),
                "repeat": run.get("repeat", 1),
                "run_id": body["run_id"],
                "role": role["kind"],
                "verdict": role.get("verdict"),
                "validity": body["validity"],
                "solved": outcome.get("solved")
                if body["validity"] == "valid"
                else None,
                "score": _score(outcome.get("score")),
                "validated": validated.get(
                    f"{body['run_id']}:{role.get('contract_id')}:{role.get('generation')}"
                ),
                "cost_total": cost.get("executor", {}).get("total_tokens", 0)
                + cost.get("workers", {}).get("total_tokens", 0),
            }
        )
    return rows, nulls


def revalidate(batch_dir: Path) -> dict:
    """Re-runs each defeat's recorded pipeline; validated when every originally failing step fails again."""
    results: dict[str, bool] = {}
    for record in store.events(batch_dir / "store"):
        event = record["event"]
        role = event["body"].get("role", {})
        if (
            event["kind"] != "label"
            or role.get("kind") != "judged"
            or role.get("verdict") != "defeat"
        ):
            continue
        key = f"{event['body']['run_id']}:{role['contract_id']}:{role['generation']}"
        if key in results:
            continue
        attempt = sorted(
            (batch_dir / "runs" / event["body"]["run_id"]).glob("attempt-*")
        )[-1]
        run_store = attempt / "codex-home" / "pro_contract"
        original = set()
        for run_event in store.events(run_store):
            body = run_event["event"]["body"]
            if (
                run_event["event"]["kind"] == "verification"
                and body["contract_id"] == role["contract_id"]
                and body["generation"] == role["generation"]
                and body.get("receipts")
            ):
                original = {
                    step["step"]
                    for step in body["receipts"]["steps"]
                    if step["outcome"] == "fail"
                }
        work = (
            run_store
            / "work"
            / role["contract_id"].replace("/", "_").replace(".", "_")
            / str(role["generation"])
        )
        image = f"programbench/{event['body']['instance'].replace('__', '_1776_')}:task_cleanroom"
        output = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "1000:1000",
                "-v",
                f"{work / 'candidate'}:/candidate:ro",
                "-v",
                f"{work / 'candidate.pipeline'}:/pc:ro",
                "--entrypoint",
                "bash",
                image,
                "/pc/pipeline.sh",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        ).stdout
        failing = {
            line.split()[1]
            for line in output.splitlines()
            if line.startswith("@@PC ") and line.split()[2] == "fail"
        }
        results[key] = bool(original) and original <= failing
    (batch_dir / "revalidation.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def noise(rows: list[dict]) -> dict:
    finals = {
        (r["task"], r["arm"], r["repeat"]): r
        for r in rows
        if r["role"] == "final_workspace" and r["validity"] == "valid"
    }
    pairs = [
        (finals[(t, a, 1)], finals[(t, a, 2)])
        for (t, a, rep) in finals
        if rep == 2 and (t, a, 1) in finals
    ]
    if not pairs:
        return {"pairs": 0}
    return {
        "pairs": len(pairs),
        "solved_agreement": statistics.fmean(
            1.0 if x["solved"] == y["solved"] else 0.0 for x, y in pairs
        ),
        "mean_abs_score_diff": statistics.fmean(
            abs((x["score"] or 0) - (y["score"] or 0)) for x, y in pairs
        ),
    }


def costs(rows: list[dict]) -> dict:
    result = {}
    for arm in sorted({r["arm"] for r in rows if r["arm"]}):
        values = sorted(
            r["cost_total"]
            for r in rows
            if r["arm"] == arm and r["role"] == "final_workspace"
        )
        if values:
            result[arm] = {
                "median": statistics.median(values),
                "p90": values[int(0.9 * (len(values) - 1))],
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--batch-dir", type=Path, required=True)
    rep.add_argument("--out", type=Path, required=True)
    val = sub.add_parser("revalidate")
    val.add_argument("--batch-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "revalidate":
        print(json.dumps(revalidate(args.batch_dir), indent=2))
        return
    rows, nulls = load_rows(args.batch_dir)
    result = {
        **estimands(rows, nulls, seed=0),
        "costs": costs(rows),
        "noise": noise(rows),
        "null_floors": nulls,
    }
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# M0 report", ""]
    for name, value in result.items():
        lines += [f"## {name}", "", "```json", json.dumps(value, indent=2), "```", ""]
    args.out.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
