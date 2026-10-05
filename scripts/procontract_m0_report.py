#!/usr/bin/env python3
"""M0 report: estimands with task-clustered bootstrap CIs (RSI spec §10 item 11)."""

import argparse
import json
import random
import statistics
import subprocess
from pathlib import Path

import procontract_store as store

MISSED_DEFECT_THRESHOLD = 0.95


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


def _first_repeat(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("repeat", 1) == 1]


def _mean(values: list[float]) -> dict:
    return {"mean": statistics.fmean(values), "n": len(values)}


def estimands(
    rows: list[dict],
    nulls: dict[str, float],
    seed: int = 0,
    assigned: list[dict] | None = None,
) -> dict:
    """Per-arm and task-level statistics use repeat 1 only; repeat 2 feeds `noise`."""
    rows = _first_repeat(rows)
    valid = [r for r in rows if r["validity"] == "valid" and r["solved"] is not None]
    judged = [r for r in valid if r["role"] == "judged"]
    supported = [r for r in judged if r["verdict"] == "support"]
    defeats = [r for r in judged if r["verdict"] == "defeat"]
    checked_defeats = [
        r
        for r in rows
        if r["role"] == "judged"
        and r["verdict"] == "defeat"
        and r.get("validated") is not None
    ]
    finals = [r for r in rows if r["role"] == "final_workspace"]
    final_runs = {r["run_id"] for r in finals}
    first_assigned = _first_repeat(assigned or [])
    arms = {r["arm"] for r in finals} | {r["arm"] for r in first_assigned}
    by_arm = {}
    for arm in sorted(arms, reverse=True):
        arm_rows = [r for r in finals if r["arm"] == arm]
        by_arm[arm] = {
            "solved": sum(
                1 for r in arm_rows if r["validity"] == "valid" and r["solved"]
            ),
            "valid": sum(1 for r in arm_rows if r["validity"] == "valid"),
            "invalid": sum(1 for r in arm_rows if r["validity"] != "valid"),
            "missing": sum(
                1
                for a in first_assigned
                if a["arm"] == arm and a["run_id"] not in final_runs
            ),
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


def pass_rate_estimands(
    rows: list[dict],
    null_pass_rates: dict[str, float],
    threshold: float = MISSED_DEFECT_THRESHOLD,
    seed: int = 0,
) -> dict:
    """Pass-rate estimands over valid labels of repeat 1. A supported subject whose pass rate is
    below `threshold` counts as a missed defect."""
    rows = [
        r
        for r in _first_repeat(rows)
        if r["validity"] == "valid" and r.get("pass_rate") is not None
    ]
    finals = [r for r in rows if r["role"] == "final_workspace"]
    by_arm, above_null = {}, {}
    for arm in sorted({r["arm"] for r in finals}, reverse=True):
        arm_rows = [r for r in finals if r["arm"] == arm]
        by_arm[arm] = _mean([r["pass_rate"] for r in arm_rows])
        gaps = [
            r["pass_rate"] - null_pass_rates[r["task"]]
            for r in arm_rows
            if r["task"] in null_pass_rates
        ]
        above_null[arm] = statistics.fmean(gaps) if gaps else None
    judged = [r for r in rows if r["role"] == "judged"]
    by_verdict = {
        verdict: _mean([r["pass_rate"] for r in judged if r["verdict"] == verdict])
        for verdict in sorted({r["verdict"] for r in judged})
    }
    supported = [r for r in judged if r["verdict"] == "support"]
    missed = _proportion(supported, lambda r: r["pass_rate"] < threshold, seed)
    return {
        "pass_rate_by_arm": by_arm,
        "pass_rate_above_null": above_null,
        "pass_rate_by_verdict": by_verdict,
        "missed_defect_rate_at_threshold": {**missed, "threshold": threshold},
    }


def _score(score: str | None) -> float | None:
    if score == "✅":
        return 100.0
    return float(score) if score and score.isdigit() else None


def load_rows(
    batch_dir: Path,
) -> tuple[list[dict], dict[str, float], list[dict], dict[str, float]]:
    """Returns label rows, null-sentinel scores, the assignments and null-sentinel pass rates."""
    records = store.events(batch_dir / "store")
    events = [dict(record["event"], seq=record["seq"]) for record in records]
    assignments = {
        e["body"]["run_id"]: e["body"] for e in events if e["kind"] == "assignment"
    }
    costs = {
        e["body"]["run_id"]: e["body"].get("cost", {})
        for e in events
        if e["kind"] == "execution"
    }
    # A run whose last executor turn failed (a provider or transport error) never finished:
    # its final workspace is excluded as infrastructure, never scored.
    turn_failed = {
        e["body"]["run_id"]
        for e in events
        if e["kind"] == "execution"
        and (e["body"].get("turn_statuses") or [""])[-1] == "failed"
    }
    revalidation = batch_dir / "revalidation.json"
    validated = json.loads(revalidation.read_text()) if revalidation.exists() else {}
    latest: dict[tuple, dict] = {}
    for event in events:
        if event["kind"] != "label":
            continue
        role = event["body"]["role"]
        key = (
            event["body"].get("run_id"),
            event["body"]["instance"],
            role["kind"],
            role.get("contract_id"),
            role.get("generation"),
        )
        if key not in latest or event["seq"] > latest[key]["seq"]:
            latest[key] = event
    rows, nulls, null_pass_rates = [], {}, {}
    for event in sorted(latest.values(), key=lambda e: e["seq"]):
        body = event["body"]
        outcome = body.get("outcome") or {}
        role = body["role"]
        if role["kind"] == "null_sentinel":
            if _score(outcome.get("score")) is not None:
                nulls[body["instance"]] = _score(outcome.get("score"))
            if outcome.get("pass_rate") is not None:
                null_pass_rates[body["instance"]] = outcome["pass_rate"]
            continue
        run = assignments.get(body["run_id"], {})
        cost = costs.get(body["run_id"], {})
        validity = body["validity"]
        if role["kind"] == "final_workspace" and body["run_id"] in turn_failed:
            validity = "invalid"
        rows.append(
            {
                "task": body["instance"],
                "arm": run.get("arm"),
                "repeat": run.get("repeat", 1),
                "run_id": body["run_id"],
                "seq": event["seq"],
                "role": role["kind"],
                "verdict": role.get("verdict"),
                "validity": validity,
                "solved": outcome.get("solved") if validity == "valid" else None,
                "score": _score(outcome.get("score")),
                "pass_rate": outcome.get("pass_rate") if validity == "valid" else None,
                "validated": validated.get(
                    f"{body['run_id']}:{role.get('contract_id')}:{role.get('generation')}"
                ),
                "cost_total": cost.get("executor", {}).get("total_tokens", 0)
                + cost.get("workers", {}).get("total_tokens", 0),
            }
        )
    return rows, nulls, list(assignments.values()), null_pass_rates


def _failing_steps(stdout: str) -> set[str]:
    """Steps reported by `@@PC <step> <outcome> ...` lines; any outcome but pass fails, except
    `unqualified`, which is no evidence either way. Malformed lines are skipped."""
    failing = set()
    for line in stdout.splitlines():
        parts = line.split()
        if (
            len(parts) >= 3
            and parts[0] == "@@PC"
            and parts[2] not in ("pass", "unqualified")
        ):
            failing.add(parts[1])
    return failing


def _latest_attempt(run_root: Path) -> Path | None:
    attempts = []
    for path in run_root.glob("attempt-*"):
        suffix = path.name.removeprefix("attempt-")
        if suffix.isdigit():
            attempts.append((int(suffix), path))
    return max(attempts)[1] if attempts else None


def _revalidate_one(batch_dir: Path, body: dict) -> bool | None:
    """True when the failing mechanical steps fail again, False when they do not,
    None when the defeat cannot be checked (reviewer-only or infrastructure failure)."""
    role = body["role"]
    attempt = _latest_attempt(batch_dir / "runs" / body["run_id"])
    if attempt is None:
        return None
    run_store = attempt / "codex-home" / "pro_contract"
    original: set[str] = set()
    for run_event in store.events(run_store):
        event = run_event["event"]
        receipts = event["body"].get("receipts")
        if (
            event["kind"] == "verification"
            and event["body"]["contract_id"] == role["contract_id"]
            and event["body"]["generation"] == role["generation"]
            and receipts
        ):
            original = {
                step["step"]
                for step in receipts["steps"]
                if step["outcome"] not in ("pass", "unqualified")
            }
    if not original:
        return None
    work = (
        run_store
        / "work"
        / role["contract_id"].replace("/", "_").replace(".", "_")
        / str(role["generation"])
    )
    image = f"programbench/{body['instance'].replace('__', '_1776_')}:task_cleanroom"
    # Pipelines from the case runner run every case over the base workspace; older ones ignore it.
    base = work.parent / "base"
    base_mount = ["-v", f"{base}:/pc-base:ro"] if base.is_dir() else []
    try:
        completed = subprocess.run(
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
                *base_mount,
                "--entrypoint",
                "bash",
                image,
                "/pc/pipeline.sh",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return original <= _failing_steps(completed.stdout)


def revalidate(batch_dir: Path) -> dict:
    """Re-runs each defeat's recorded pipeline. The result is written after every
    defeat so a crash keeps the work done so far."""
    results: dict[str, bool | None] = {}
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
        results[key] = _revalidate_one(batch_dir, event["body"])
        (batch_dir / "revalidation.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )
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
    rated = [
        (x["pass_rate"], y["pass_rate"])
        for x, y in pairs
        if x.get("pass_rate") is not None and y.get("pass_rate") is not None
    ]
    return {
        "pairs": len(pairs),
        "solved_agreement": statistics.fmean(
            1.0 if x["solved"] == y["solved"] else 0.0 for x, y in pairs
        ),
        "mean_abs_score_diff": statistics.fmean(
            abs((x["score"] or 0) - (y["score"] or 0)) for x, y in pairs
        ),
        "mean_abs_pass_rate_diff": statistics.fmean(abs(x - y) for x, y in rated)
        if rated
        else None,
    }


def costs(rows: list[dict]) -> dict:
    result = {}
    rows = _first_repeat(rows)
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
    rep.add_argument("--threshold", type=float, default=MISSED_DEFECT_THRESHOLD)
    val = sub.add_parser("revalidate")
    val.add_argument("--batch-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "revalidate":
        print(json.dumps(revalidate(args.batch_dir), indent=2))
        return
    rows, nulls, assigned, null_pass_rates = load_rows(args.batch_dir)
    result = {
        **estimands(rows, nulls, seed=0, assigned=assigned),
        **pass_rate_estimands(rows, null_pass_rates, args.threshold, seed=0),
        "costs": costs(rows),
        "noise": noise(rows),
        "null_floors": nulls,
        "null_pass_rates": null_pass_rates,
    }
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# M0 report", ""]
    for name, value in result.items():
        lines += [f"## {name}", "", "```json", json.dumps(value, indent=2), "```", ""]
    args.out.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
