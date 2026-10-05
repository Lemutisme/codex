#!/usr/bin/env python3
"""Offline calibration of sealed evidence (evidence spec §9, V1).

  evidence  for each task, run the real lane with `--stop-after-issue`: drafting, probing and Issue
            are real, the executor is interrupted at intake. Yields each task's evidence policy.
  replay    run `pro-contract-check` (the lane's own check pipeline) for every labelled frozen
            subject of the given batches, plus a negative control (the reference against itself)
            and a positive control (a constant-output candidate).
  report    join the receipts with hidden-test pass rates, choose θ_s on a calibration split,
            report it on the held-out split, and check the preregistered gate.

Execution and comparison belong to the lane (`pro-contract-check`); this script only orchestrates,
joins and counts. Long phases should run detached (`setsid nohup … &`)."""

import argparse
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_evaluation as evaluation
import procontract_store as store

SCRIPTS = Path(__file__).resolve().parent
RUNNER = SCRIPTS / "procontract_benchmark_runner.py"
DEFAULT_CHECK_BIN = (
    SCRIPTS.parent / "codex-rs" / "target" / "debug" / "pro-contract-check"
)
HIDDEN_THRESHOLD = 0.95
THETA_GRID = list(range(800, 1001, 10))
GATE = {"false_alarm_max": 0.01, "spearman_min": 0.6, "holdout_missed_max": 0.20}
CALIBRATION_MISSED_MAX = 0.10
CONSTANT_CANDIDATE = (
    "#!/bin/sh\nprintf '#!/bin/sh\\nexit 0\\n' > executable && chmod +x executable\n"
)


def tasks(batch_dir: Path) -> list[str]:
    return sorted(json.loads((batch_dir / "batch.json").read_text())["pins"])


def check_bin() -> str:
    return os.environ.get("PRO_CONTRACT_CHECK_BIN", str(DEFAULT_CHECK_BIN))


# ---------------------------------------------------------------------------------------------
# evidence


def evidence_one(instance: str, out: Path, codex_bin: Path, prompt: Path) -> str:
    run_dir = out / "evidence" / instance
    summary = run_dir / "run.json"
    if (
        summary.exists()
        and json.loads(summary.read_text()).get("stopped") == "after_issue"
    ):
        return f"{instance}: kept"
    shutil.rmtree(run_dir, ignore_errors=True)
    log = out / "evidence" / f"{instance}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    common = ["--arm", "on", "--instance", instance, "--run-dir", str(run_dir)]
    common += ["--codex-bin", str(codex_bin), "--prompt", str(prompt)]
    with log.open("w") as output:
        for command in (
            ["prepare"],
            ["run", "--stop-after-issue", "--deadline-secs", "3600"],
        ):
            done = subprocess.run(
                [sys.executable, str(RUNNER), *command, *common],
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if done.returncode != 0:
                return f"{instance}: {command[0]} failed (see {log})"
    stopped = json.loads(summary.read_text()).get("stopped")
    return f"{instance}: {stopped}"


def cmd_evidence(args) -> None:
    instances = args.instances or tasks(args.batch_dir)
    with ThreadPoolExecutor(args.parallel) as pool:
        for line in pool.map(
            lambda instance: evidence_one(
                instance, args.out, args.codex_bin, args.prompt
            ),
            instances,
        ):
            print(line, flush=True)


def issued(run_dir: Path) -> dict | None:
    """The evidence run's issued policy, settings file, run store and base subject."""
    run_store = run_dir / "codex-home" / "pro_contract"
    if not (run_store / "ledger_1.sqlite").exists():
        return None
    events = [record["event"] for record in store.events(run_store)]
    issue = next((e["body"] for e in events if e["kind"] == "issue"), None)
    intake = next((e["body"] for e in events if e["kind"] == "intake"), None)
    if issue is None or intake is None:
        return None
    return {
        "policy": issue["evidence_policy"],
        "settings": run_store / "settings.json",
        "store": run_store,
        "base_subject": intake["base_subject"],
    }


# ---------------------------------------------------------------------------------------------
# replay


def hidden_pass_rate(batch_dir: Path, body: dict) -> float | None:
    outcome = body.get("outcome") or {}
    if outcome.get("pass_rate") is not None:
        return outcome["pass_rate"]
    instance, attempts = body["instance"], body["attempts"]
    pattern = (
        f"{batch_dir}/runs/{body['run_id']}/attempt-*/labels/{body['subject_hash']}"
        f"/eval/attempt-{attempts}/{instance}/{instance}.eval.json"
    )
    paths = sorted(glob.glob(pattern))
    if not paths:
        return None
    results = json.loads(Path(paths[-1]).read_text())["test_results"]
    programbench = Path(
        json.loads((batch_dir / "batch.json").read_text())["programbench"]
    )
    return evaluation.pass_rate(
        results, *evaluation.ignored_tests(programbench, instance)
    )["pass_rate"]


def subjects(batch_dirs: list[Path]) -> list[dict]:
    """Every valid judged or final subject with its hidden pass rate, once per (task, subject)."""
    found: dict[tuple[str, str], dict] = {}
    for batch_dir in batch_dirs:
        for record in store.events(batch_dir / "store"):
            event = record["event"]
            body = event["body"]
            if event["kind"] != "label" or body["validity"] != "valid":
                continue
            if body["role"]["kind"] not in ("judged", "final_workspace"):
                continue
            key = (body["instance"], body["subject_hash"])
            if key in found:
                continue
            sources = sorted(
                glob.glob(
                    f"{batch_dir}/runs/{body['run_id']}/attempt-*/labels/{body['subject_hash']}/source"
                )
            )
            hidden = hidden_pass_rate(batch_dir, body)
            if sources and hidden is not None:
                found[key] = {
                    "instance": body["instance"],
                    "subject": body["subject_hash"],
                    "source": sources[-1],
                    "hidden": hidden,
                    "run_id": body["run_id"],
                }
    return sorted(found.values(), key=lambda row: (row["instance"], row["subject"]))


def run_check(
    settings: Path,
    policy: Path,
    subject: Path,
    base: Path,
    out: Path,
    reference: bool = False,
) -> str:
    if out.exists():
        return "kept"
    command = [check_bin(), "--settings", str(settings), "--policy", str(policy)]
    command += ["--subject", str(subject), "--base", str(base)]
    if reference:
        command.append("--candidate-is-reference")
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return f"failed: {done.stderr.strip()[:300]}"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(done.stdout)
    tmp.replace(out)
    return "ran"


def replay_task(
    instance: str, rows: list[dict], out: Path, lock: threading.Lock
) -> list[str]:
    evidence = issued(out / "evidence" / instance)
    if evidence is None:
        return [f"{instance}: no issued evidence"]
    task_dir = out / "replay" / instance
    base = task_dir / "base"
    policy = task_dir / "policy.json"
    if not base.exists():
        task_dir.mkdir(parents=True, exist_ok=True)
        store.materialize(evidence["store"], evidence["base_subject"], base)
        policy.write_text(json.dumps(evidence["policy"]))
    lines = []
    settings = evidence["settings"]
    scratch = task_dir / "scratch"

    def fresh(name: str) -> Path:
        path = scratch / name
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        return path

    negative = fresh("negative")
    lines.append(
        f"{instance} negative: {run_check(settings, policy, negative, base, task_dir / 'negative.json', reference=True)}"
    )
    positive = fresh("positive")
    (positive / "compile.sh").write_text(CONSTANT_CANDIDATE)
    (positive / "compile.sh").chmod(0o755)
    lines.append(
        f"{instance} positive: {run_check(settings, policy, positive, base, task_dir / 'positive.json')}"
    )
    for row in rows:
        target = task_dir / "subjects" / f"{row['subject']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        candidate = scratch / "candidate"
        shutil.rmtree(candidate, ignore_errors=True)
        shutil.copytree(row["source"], candidate, symlinks=True)
        status = run_check(settings, policy, candidate, base, target)
        lines.append(f"{instance} {row['subject'][:12]}: {status}")
    shutil.rmtree(scratch, ignore_errors=True)
    with lock:
        (task_dir / "subjects.json").write_text(json.dumps(rows, indent=2) + "\n")
    return lines


def cmd_replay(args) -> None:
    rows = subjects(args.batch_dir)
    by_task: dict[str, list[dict]] = {}
    for row in rows:
        by_task.setdefault(row["instance"], []).append(row)
    lock = threading.Lock()
    with ThreadPoolExecutor(args.parallel) as pool:
        for lines in pool.map(
            lambda item: replay_task(item[0], item[1], args.out, lock),
            sorted(by_task.items()),
        ):
            print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------------------------
# report


def tally(receipts: dict) -> dict:
    """The mechanical facts of one check run; sealed counting mirrors the lane's SealedTally."""
    steps = receipts["steps"]
    sealed = [step for step in steps if step["step"].startswith("sealed:")]
    qualified = [step for step in sealed if step["outcome"] in ("pass", "fail")]
    others = [step for step in steps if not step["step"].startswith("sealed:")]
    return {
        "complete": receipts["complete"],
        "mechanical_ok": all(step["outcome"] != "fail" for step in others),
        "qualified": len(qualified),
        "passed": sum(step["outcome"] == "pass" for step in qualified),
        "succeeded": sum(step.get("reference_exit") == 0 for step in qualified),
        "unqualified": len(sealed) - len(qualified),
    }


def sealed_rate(facts: dict) -> float | None:
    return facts["passed"] / facts["qualified"] if facts["qualified"] else None


def mechanically_supported(facts: dict, policy: dict, theta_permille: int) -> bool:
    """The lane's mechanical gate (decision::mechanical_verdict passes) at threshold θ."""
    sufficient = (
        facts["qualified"] >= policy["min_sealed_qualified"]
        and facts["succeeded"] * 1000
        >= policy["min_success_permille"] * facts["qualified"]
    )
    return (
        facts["complete"]
        and facts["mechanical_ok"]
        and sufficient
        and facts["passed"] * 1000 >= theta_permille * facts["qualified"]
    )


def missed_rate(rows: list[dict], theta: int) -> tuple[float | None, int]:
    supported = [
        row
        for row in rows
        if mechanically_supported(row["facts"], row["policy"], theta)
    ]
    if not supported:
        return None, 0
    missed = sum(row["hidden"] < HIDDEN_THRESHOLD for row in supported)
    return missed / len(supported), len(supported)


def choose_theta(rows: list[dict]) -> int | None:
    """The smallest θ whose supported calibration subjects are mostly truly good."""
    for theta in THETA_GRID:
        rate, n = missed_rate(rows, theta)
        if n and rate is not None and rate <= CALIBRATION_MISSED_MAX:
            return theta
    return None


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while (
            end + 1 < len(order) and values[order[end + 1]] == values[order[position]]
        ):
            end += 1
        average = (position + end) / 2 + 1
        for index in order[position : end + 1]:
            result[index] = average
        position = end + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def clustered_spearman(rows: list[dict], seed: int, resamples: int = 2000) -> dict:
    """Spearman ρ of sealed vs hidden pass rate with a task-clustered bootstrap interval."""
    usable = [row for row in rows if sealed_rate(row["facts"]) is not None]
    point = spearman(
        [sealed_rate(r["facts"]) for r in usable], [r["hidden"] for r in usable]
    )
    by_task: dict[str, list[dict]] = {}
    for row in usable:
        by_task.setdefault(row["instance"], []).append(row)
    names = sorted(by_task)
    rng = random.Random(seed)
    samples = []
    for _ in range(resamples if names else 0):
        picked = [
            row for name in (rng.choice(names) for _ in names) for row in by_task[name]
        ]
        value = spearman(
            [sealed_rate(r["facts"]) for r in picked], [r["hidden"] for r in picked]
        )
        if value is not None:
            samples.append(value)
    samples.sort()
    interval = (
        (samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples)) - 1])
        if samples
        else (None, None)
    )
    return {"point": point, "low": interval[0], "high": interval[1], "n": len(usable)}


def split(
    instances: list[str], seed: int, calibration: int = 20
) -> tuple[list[str], list[str]]:
    shuffled = sorted(instances)
    random.Random(seed).shuffle(shuffled)
    return sorted(shuffled[:calibration]), sorted(shuffled[calibration:])


def control_rate(receipts: dict, outcome: str) -> tuple[int, int]:
    """(count of qualified sealed cases with `outcome`, qualified sealed cases)."""
    qualified = [
        step
        for step in receipts["steps"]
        if step["step"].startswith("sealed:") and step["outcome"] in ("pass", "fail")
    ]
    return sum(step["outcome"] == outcome for step in qualified), len(qualified)


def load_replay(out: Path) -> tuple[list[dict], dict, list[str]]:
    """Rows and controls of every replayed task, and the tasks left out because their prober
    froze no sealed cases (there is nothing to calibrate)."""
    rows, controls, excluded = [], {}, []
    for task_dir in sorted((out / "replay").glob("*")):
        if not (task_dir / "subjects.json").exists():
            continue
        policy = json.loads((task_dir / "policy.json").read_text())
        if not policy.get("sealed"):
            excluded.append(task_dir.name)
            continue
        for row in json.loads((task_dir / "subjects.json").read_text()):
            receipts_path = task_dir / "subjects" / f"{row['subject']}.json"
            if receipts_path.exists():
                facts = tally(json.loads(receipts_path.read_text()))
                rows.append({**row, "facts": facts, "policy": policy})
        controls[task_dir.name] = {
            name: json.loads((task_dir / f"{name}.json").read_text())
            for name in ("negative", "positive")
            if (task_dir / f"{name}.json").exists()
        }
    return rows, controls, excluded


def report(rows: list[dict], controls: dict, seed: int) -> dict:
    instances = sorted({row["instance"] for row in rows})
    calibration, holdout = split(instances, seed)
    cal_rows = [row for row in rows if row["instance"] in calibration]
    hold_rows = [row for row in rows if row["instance"] in holdout]
    theta = choose_theta(cal_rows)
    false_alarms = [
        control_rate(c["negative"], "fail")
        for c in controls.values()
        if "negative" in c
    ]
    caught = [
        control_rate(c["positive"], "fail")
        for c in controls.values()
        if "positive" in c
    ]
    false_alarm_rate = sum(f for f, _ in false_alarms) / max(
        1, sum(n for _, n in false_alarms)
    )
    holdout_missed, holdout_supported = (
        missed_rate(hold_rows, theta) if theta is not None else (None, 0)
    )
    rho = clustered_spearman(hold_rows, seed)
    gate = {
        "false_alarm": false_alarm_rate <= GATE["false_alarm_max"],
        "spearman": rho["point"] is not None and rho["point"] >= GATE["spearman_min"],
        "holdout_missed": holdout_missed is not None
        and holdout_missed <= GATE["holdout_missed_max"],
        "theta_found": theta is not None,
    }
    qualified = [row["facts"]["qualified"] for row in rows]
    return {
        "seed": seed,
        "tasks": {"calibration": calibration, "holdout": holdout},
        "subjects": {"calibration": len(cal_rows), "holdout": len(hold_rows)},
        "theta_permille": theta,
        "calibration_curve": [
            {
                "theta": t,
                "missed": missed_rate(cal_rows, t)[0],
                "supported": missed_rate(cal_rows, t)[1],
            }
            for t in THETA_GRID
        ],
        "holdout": {
            "spearman": rho,
            "missed_rate": holdout_missed,
            "supported": holdout_supported,
            "support_rate": holdout_supported / len(hold_rows) if hold_rows else None,
        },
        "all_subjects_spearman": clustered_spearman(rows, seed),
        "controls": {
            "negative_false_alarm_rate": false_alarm_rate,
            "positive_catch_rate": sum(f for f, _ in caught)
            / max(1, sum(n for _, n in caught)),
        },
        "qualified_sealed": {
            "min": min(qualified, default=None),
            "median": sorted(qualified)[len(qualified) // 2] if qualified else None,
            "max": max(qualified, default=None),
        },
        "gate": {**gate, "passed": all(gate.values())},
        "note": "offline replay judges the mechanical gate only; the reviewer is not replayed",
    }


def cmd_report(args) -> None:
    rows, controls, excluded = load_replay(args.out)
    result = {
        **report(rows, controls, args.seed),
        "excluded_tasks_without_sealed_cases": excluded,
    }
    args.report.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "rows.json").write_text(
        json.dumps(
            [{k: v for k, v in row.items() if k != "policy"} for row in rows], indent=2
        )
        + "\n"
    )
    lines = ["# Sealed evidence calibration (V1)", ""]
    for name, value in result.items():
        lines += [f"## {name}", "", "```json", json.dumps(value, indent=2), "```", ""]
    args.report.write_text("\n".join(lines))
    print(json.dumps(result["gate"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    evidence = sub.add_parser("evidence")
    evidence.add_argument("--batch-dir", type=Path, required=True)
    evidence.add_argument("--out", type=Path, required=True)
    evidence.add_argument("--codex-bin", type=Path, required=True)
    evidence.add_argument("--prompt", type=Path, required=True)
    evidence.add_argument("--instances", nargs="+")
    evidence.add_argument("--parallel", type=int, default=4)
    replay = sub.add_parser("replay")
    replay.add_argument("--batch-dir", type=Path, action="append", required=True)
    replay.add_argument("--out", type=Path, required=True)
    replay.add_argument("--parallel", type=int, default=4)
    rep = sub.add_parser("report")
    rep.add_argument("--out", type=Path, required=True)
    rep.add_argument("--report", type=Path, required=True)
    rep.add_argument("--seed", type=int, default=20261005)
    args = parser.parse_args()
    {"evidence": cmd_evidence, "replay": cmd_replay, "report": cmd_report}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
