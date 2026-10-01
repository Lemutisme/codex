#!/usr/bin/env python3
"""M0 batch orchestration: a seeded plan, detached execution, batch-level reconciliation.

Launch long batches detached: `setsid nohup python3 procontract_batch.py run ... &`.
"Resumable" means batch-level reconciliation: completed runs are kept; interrupted attempts
are recorded and charged against the frozen crash budget (one rerun)."""

import argparse
import fcntl
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_benchmark_runner as runner
import procontract_evaluation as evaluation
import procontract_store as store

PROTOCOL = {
    "retries": {"eval_branch_error": 2, "run_crash": 1},
    "duplicates_per_arm": 4,
    "pool_ratios": [40, 30, 30],
    "exposure": "every corpus instance",
}

OPERATOR = Path.home() / ".procontract-operator"
ARCHIVE = (
    Path.home() / ".procontract-archive"
)  # outside ~/run-artifacts, out of any cleanup's reach
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
PROGRAMBENCH_CMD = ["uv", "run", "programbench"]


def plan_runs(
    dev: list[str],
    difficulty: dict[str, str],
    n: int,
    duplicates: int,
    seed: int,
    instances: list[str] | None = None,
    arms: tuple[str, ...] = ("on", "off"),
) -> list[dict]:
    rng = random.Random(seed)
    if instances is not None:
        outside = sorted(set(instances) - set(dev))
        if outside:
            raise ValueError(f"instances not in the dev pool: {outside}")
        chosen = sorted(set(instances))
    else:
        strata: dict[str, list[str]] = {}
        for instance in sorted(dev):
            strata.setdefault(difficulty.get(instance, "unknown"), []).append(instance)
        chosen = []
        for name in sorted(strata):
            quota = round(n * len(strata[name]) / len(dev))
            chosen += rng.sample(strata[name], min(quota, len(strata[name])))
        chosen = sorted(chosen)[:n]
        while len(chosen) < n:
            chosen.append(rng.choice(sorted(set(dev) - set(chosen))))
    if duplicates > len(chosen):
        raise ValueError(
            f"cannot plan {duplicates} duplicates from {len(chosen)} chosen instances"
        )
    doubled = set(rng.sample(sorted(chosen), duplicates))
    runs = [
        {
            "run_id": f"{instance}-{arm}-{repeat}",
            "instance": instance,
            "arm": arm,
            "repeat": repeat,
        }
        for instance in chosen
        for arm in arms
        for repeat in ((1, 2) if instance in doubled else (1,))
    ]
    order = list(range(len(runs)))
    rng.shuffle(order)
    for run, position in zip(runs, order):
        run["order"] = position
    return sorted(runs, key=lambda run: run["order"])


def next_action(state: dict, protocol: dict) -> str:
    phase = state["phase"]
    if phase == "planned":
        return "prepare"
    if phase == "prepared":
        return "run"
    if phase == "ran":
        return "label"
    if phase == "labelled":
        return "done"
    if phase == "invalid":
        return "invalid"
    # Interrupted mid-prepare or mid-run: charge the crash budget.
    return (
        "prepare" if state["attempt"] <= protocol["retries"]["run_crash"] else "invalid"
    )


class BatchLock:
    def __init__(self, batch_dir: Path):
        self.path = batch_dir / ".lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.handle.close()
            raise RuntimeError(
                f"batch {self.path.parent} is already running"
            ) from error
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def _state(run_dir: Path) -> dict:
    path = run_dir / "state.json"
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"phase": "planned", "attempt": 1, "reason": ""}
    )


def _save(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")


def drive(
    run: dict,
    batch_dir: Path,
    protocol: dict,
    runner_cmd: list[str],
    label,
    extra_args: list[str],
    stop: threading.Event,
) -> dict:
    run_root = batch_dir / "runs" / run["run_id"]
    state = _state(run_root)
    while True:
        action = next_action(state, protocol)
        attempt_dir = run_root / f"attempt-{state['attempt']}"
        if action in ("done", "invalid"):
            if action == "invalid" and state["phase"] != "invalid":
                state.update(
                    phase="invalid", reason=state.get("reason") or "run crashed twice"
                )
                _save(run_root, state)
            return state
        if action in ("prepare", "run") and stop.is_set():
            return state
        if action == "prepare":
            if state["phase"] != "planned":
                state["attempt"] += 1
                attempt_dir = run_root / f"attempt-{state['attempt']}"
            state["phase"] = "preparing"
            _save(run_root, state)
            done = subprocess.run(
                [
                    *runner_cmd,
                    "prepare",
                    "--arm",
                    run["arm"],
                    "--instance",
                    run["instance"],
                    "--run-dir",
                    str(attempt_dir),
                    *extra_args,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if done.returncode != 0:
                state.update(
                    phase="invalid",
                    reason=f"prepare failed: {done.stderr.strip()[-500:]}",
                )
                _save(run_root, state)
                return state
            state["phase"] = "prepared"
        elif action == "run":
            state["phase"] = "running"
            _save(run_root, state)
            done = subprocess.run(
                [
                    *runner_cmd,
                    "run",
                    "--arm",
                    run["arm"],
                    "--instance",
                    run["instance"],
                    "--run-dir",
                    str(attempt_dir),
                    *extra_args,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if done.returncode != 0 or not (attempt_dir / "run.json").exists():
                _save(run_root, state)
                continue
            state["phase"] = "ran"
        elif action == "label":
            try:
                label(run, attempt_dir)
            except BaseException:
                # The run stays `ran`; the next launch relabels it.
                stop.set()
                raise
            state["phase"] = "labelled"
        _save(run_root, state)


def run_batch(
    batch_dir: Path,
    runs: list[dict],
    protocol: dict,
    runner_cmd: list[str],
    label,
    parallel: int,
    extra_args: list[str] = (),
) -> list[dict]:
    stop = threading.Event()
    errors: list[BaseException] = []

    def work(run: dict) -> dict:
        try:
            return drive(
                run, batch_dir, protocol, runner_cmd, label, list(extra_args), stop
            )
        except BaseException as error:
            errors.append(error)
            return _state(batch_dir / "runs" / run["run_id"])

    with BatchLock(batch_dir):
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            states = list(pool.map(work, runs))
    if errors:
        raise errors[0]
    return states


def missing_known(manifest_runs: list[dict], known: dict) -> list[str]:
    return sorted({run["instance"] for run in manifest_runs} - set(known))


def append_execution(
    batch_store: Path, identities: dict, run: dict, run_dir: Path
) -> None:
    """Append the execution event once per (run_id, attempt), so relabelling is idempotent."""
    attempt = int(run_dir.name.removeprefix("attempt-"))
    for event in store.events(batch_store):
        body = event["event"]["body"]
        if event["event"]["kind"] == "execution" and (
            body.get("run_id"),
            body.get("attempt"),
        ) == (run["run_id"], attempt):
            return
    summary = json.loads((run_dir / "run.json").read_text())
    body = {
        "run_id": run["run_id"],
        "instance": run["instance"],
        "arm": run["arm"],
        "repeat": run["repeat"],
        "attempt": attempt,
        **summary,
    }
    store.append(batch_store, "execution", identities, body)


def archive_run(source: Path, archive: Path) -> None:
    """Hard-link (copy across filesystems) into a tmp dir, then move it into place atomically."""
    if not source.exists() or archive.exists():
        return
    tmp = archive.with_name(f"{archive.name}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    archive.parent.mkdir(parents=True, exist_ok=True)

    def link_or_copy(src, dst):
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)

    shutil.copytree(source, tmp, copy_function=link_or_copy)
    os.replace(tmp, archive)


def _image_id(image: str) -> str:
    return subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _phase_counts(states: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for state in states:
        counts[state["phase"]] = counts.get(state["phase"], 0) + 1
    return counts


def cmd_plan(args) -> None:
    pools = json.loads(args.pools.read_text())
    try:
        runs = plan_runs(
            pools["dev"],
            pools["difficulty"],
            args.n,
            args.duplicates,
            args.seed,
            instances=args.instances,
            arms=("on", "off") if args.arms == "both" else (args.arms,),
        )
    except ValueError as err:
        raise SystemExit(f"plan: {err}") from err
    instances = sorted({run["instance"] for run in runs})
    pins = {}
    for instance in instances:
        runner.ensure_images(instance)
        subprocess.run(
            [*PROGRAMBENCH_CMD, "blob", "sync", instance],
            cwd=args.programbench,
            check=True,
            capture_output=True,
        )
        pins[instance] = evaluation.current_pins(
            args.programbench, instance, HF_CACHE, _image_id
        )
    args.batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": PROTOCOL,
        "seed": args.seed,
        "codex_bin": str(args.codex_bin.resolve()),
        "codex_sha256": _sha256(args.codex_bin),
        "prompt": str(args.prompt.resolve()),
        "prompt_sha256": _sha256(args.prompt),
        "programbench": str(args.programbench),
        "pins": pins,
        "runs": runs,
    }
    (args.batch_dir / "batch.json").write_text(json.dumps(manifest, indent=2) + "\n")
    identities = store.identities(
        harness=manifest["codex_sha256"], model=runner.MODEL, effort=runner.EFFORT
    )
    for run in runs:
        store.append(
            args.batch_dir / "store",
            "assignment",
            identities,
            {**run, "pool": "dev", "seed": args.seed},
        )
    OPERATOR.mkdir(parents=True, exist_ok=True)
    exposed_path = OPERATOR / "exposed.json"
    exposed = (
        set(json.loads(exposed_path.read_text())) if exposed_path.exists() else set()
    )
    exposed_path.write_text(
        json.dumps(sorted(exposed | set(instances)), indent=2) + "\n"
    )


def cmd_null(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    programbench = Path(manifest["programbench"])
    known = {}
    failed = []
    for instance, pins in sorted(manifest["pins"].items()):
        work = args.batch_dir / "null" / instance
        archive = evaluation.null_package(work / "submission.tar.gz")
        # The null's own branch errors define the instance's known errors, so one attempt suffices.
        result = evaluation.evaluate_package(
            archive,
            instance,
            work / "eval",
            PROGRAMBENCH_CMD,
            programbench,
            pins["hf_revision"],
            set(),
            attempts=1,
        )
        if result["outcome"] is not None:
            result.update(validity="valid", reason="")
        if result["outcome"] is None:
            failed.append(instance)
        known[instance] = (result["outcome"] or {}).get("branch_errors", [])
        evaluator_epoch = evaluation.epoch(pins)
        role = {"kind": "null_sentinel"}
        body = {
            "label_key": evaluation.label_key("null", instance, role, evaluator_epoch),
            "run_id": None,
            "instance": instance,
            "subject_hash": None,
            "role": role,
            **result,
        }
        store.append(
            args.batch_dir / "store",
            "label",
            store.identities(evaluator_epoch=evaluator_epoch),
            body,
        )
    if failed:
        sys.exit(f"null evaluation produced no outcome for: {', '.join(failed)}")
    (args.batch_dir / "known_branch_errors.json").write_text(
        json.dumps(known, indent=2) + "\n"
    )


def cmd_run(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    known_path = args.batch_dir / "known_branch_errors.json"
    if not known_path.exists():
        sys.exit("known_branch_errors.json is missing; run `null` first")
    known = json.loads(known_path.read_text())
    if missing := missing_known(manifest["runs"], known):
        sys.exit(
            f"known_branch_errors.json lacks planned instances: {', '.join(missing)}"
        )
    programbench = Path(manifest["programbench"])
    batch_store = args.batch_dir / "store"
    identities = store.identities(
        harness=manifest["codex_sha256"], model=runner.MODEL, effort=runner.EFFORT
    )

    def label(run: dict, run_dir: Path) -> None:
        pins = manifest["pins"][run["instance"]]
        evaluation.check_pins(
            pins,
            evaluation.current_pins(programbench, run["instance"], HF_CACHE, _image_id),
        )
        append_execution(batch_store, identities, run, run_dir)
        evaluation.label_run(
            run_dir,
            batch_store,
            run["run_id"],
            run["instance"],
            evaluation.epoch(pins),
            PROGRAMBENCH_CMD,
            programbench,
            pins["hf_revision"],
            set(known.get(run["instance"], [])),
            identities,
        )
        archive_run(
            run_dir / "codex-home" / "pro_contract",
            ARCHIVE / args.batch_dir.name / run["run_id"],
        )

    runner_cmd = [
        sys.executable,
        str(Path(__file__).parent / "procontract_benchmark_runner.py"),
    ]
    extra = [
        "--codex-bin",
        manifest["codex_bin"],
        "--prompt",
        manifest["prompt"],
        "--deadline-secs",
        str(args.deadline_secs),
    ]
    states = run_batch(
        args.batch_dir,
        manifest["runs"],
        manifest["protocol"],
        runner_cmd,
        label,
        args.parallel,
        extra,
    )
    print(json.dumps(_phase_counts(states), indent=2))


def cmd_status(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    by_arm: dict[str, list[dict]] = {}
    for run in manifest["runs"]:
        by_arm.setdefault(run["arm"], []).append(
            _state(args.batch_dir / "runs" / run["run_id"])
        )
    print(
        json.dumps(
            {arm: _phase_counts(states) for arm, states in sorted(by_arm.items())},
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--pools", type=Path, required=True)
    plan.add_argument("--batch-dir", type=Path, required=True)
    plan.add_argument("--n", type=int, default=30)
    plan.add_argument("--instances", nargs="+")
    plan.add_argument("--duplicates", type=int, default=PROTOCOL["duplicates_per_arm"])
    plan.add_argument("--arms", choices=["on", "off", "both"], default="both")
    plan.add_argument("--seed", type=int, required=True)
    plan.add_argument("--codex-bin", type=Path, required=True)
    plan.add_argument("--prompt", type=Path, required=True)
    plan.add_argument("--programbench", type=Path, default=Path.home() / "ProgramBench")
    run = sub.add_parser("run")
    run.add_argument("--batch-dir", type=Path, required=True)
    run.add_argument("--parallel", type=int, default=4)
    run.add_argument("--deadline-secs", type=int, default=5 * 3600)
    null = sub.add_parser("null")
    null.add_argument("--batch-dir", type=Path, required=True)
    status = sub.add_parser("status")
    status.add_argument("--batch-dir", type=Path, required=True)
    args = parser.parse_args()
    {"plan": cmd_plan, "run": cmd_run, "null": cmd_null, "status": cmd_status}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
