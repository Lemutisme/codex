#!/usr/bin/env python3
"""One frozen 200-task successor-only sweep. No retries, refunds or RSI research."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time

import procontract_benchmark_runner as runner
import procontract_credential_gate as credentials
import procontract_online as online
import procontract_online_pilot as pilot
import procontract_online_plan as plans
import procontract_study_budget as budgets
import procontract_sweep_inputs as inputs
import procontract_sweep_jobs as jobs
import procontract_sweep_archive as archive
import procontract_sweep_report as report


def verify(path, digest, index=None):
    if plans.sha(path) != digest:
        raise ValueError("sweep plan differs from operator pin")
    plan = json.loads(path.read_text())
    if (
        plan.get("protocol") != "successor-full-v1"
        or plan.get("arms") != ["successor"]
        or len(plan["tasks"]) != 200
        or len(set(plan["tasks"])) != 200
        or plan["limits"]
        != {"task_launches": 200, "learning_launches": 0, "allocated_seconds": 3600000}
        or plan["model"] != "gpt-5.6-luna"
        or plan["effort"] != "max"
        or plan["succession"] != {"max_sessions": 3, "total_secs": 14400}
        or (
            plan["episode_secs"],
            plan["inference_secs"],
            plan["grading_secs"],
            plan["research_secs"],
        )
        != (18000, 14400, 3600, 0)
        or not 1 <= plan["parallel"] <= 4
        or set(plan["cases"]) != set(plan["tasks"])
        or Path(plan["root"]) != path.resolve().parent
        or plan["entrypoint"] != str(Path(__file__).resolve())
    ):
        raise ValueError("invalid full-sweep identity or budget")
    for name, wanted in plan["files"].items():
        if plans.sha(Path(name)) != wanted:
            raise ValueError("frozen sweep input drift")
    if index is not None:
        if type(index) is not int or not 0 <= index < 200:
            raise ValueError("episode outside full matrix")
        case = plan["cases"][plan["tasks"][index]]
        if set(case) != {"registry", "registry_sha256", "pins_sha256"}:
            raise ValueError("case binding cannot override full-sweep authority")
        plan.update(case)
    return plan


def episode(plan, digest, index):
    key = f"{index}-successor"
    root = Path(plan["root"])
    os.environ.update(
        PROCONTRACT_SWEEP_ID=digest,
        PROCONTRACT_SWEEP_EPISODE=key,
        PROGRAMBENCH_CONTAINER_PREFIX=f"pcfull-{digest[:10]}-{index}",
    )
    os.environ["PATH"] = str(root / "controller/bin") + os.pathsep + os.environ["PATH"]
    code = 0
    try:
        pilot.episode(plan, digest, index, "successor")
    except Exception as error:
        # No provider body or traceback is made a public result. Preserve local raw logs,
        # record missing quality, and stop new admission rather than buying replacements.
        result = {
            "task": plan["tasks"][index],
            "episode": key,
            "arm": "successor",
            "status": "infrastructure_failed",
            "outcome": None,
            "error_type": type(error).__name__,
            "claims": "unscored; no zero imputation, retry or refund",
        }
        run = root / "runs" / key
        run.mkdir(parents=True, exist_ok=True)
        if (run / "run.json").is_file():
            native = json.loads((run / "run.json").read_text())
            result.update(
                native_contract=native.get("status"),
                native_cost=native.get("cost"),
                native_succession=native.get("succession"),
            )
        if not (run / "result.json").exists():
            plans.publish(run / "result.json", result)
        print(
            json.dumps(
                {
                    "episode": key,
                    "error_type": type(error).__name__,
                    "status": "infrastructure_failed",
                }
            ),
            flush=True,
        )
        code = 2
    finally:
        plans.publish(
            root / f"{key}-cleanup.json", jobs.cleanup_containers(digest, key)
        )
    if code == 0:
        archive.archive_home(root / "runs" / key)
    return code


def run(plan, digest, authorization):
    root = Path(plan["root"])
    authorized = plans.authorize(plan, digest, authorization)
    # Admission is free and precedes the once-only study launch; recheck again per episode.
    credentials.inspect(
        plan["provider"], runner.current_key(os.environ), plan["episode_secs"]
    )
    plans.publish(
        root / "launch.json",
        {
            "plan_sha256": digest,
            "authorization": authorized,
            "at": time.time(),
            "restart": False,
        },
    )
    budgets.initialize(root / "budget.sqlite", digest, plan["limits"])
    seed = root / "seed-policy"
    seed.mkdir()
    (seed / "executor.md").write_text(online.instructions(plan["seed"]))
    active, completed, cursor, fatal = {}, [], 0, None
    try:
        while active or cursor < len(plan["tasks"]):
            while (
                fatal is None
                and cursor < len(plan["tasks"])
                and len(active) < plan["parallel"]
            ):
                if shutil.disk_usage(root).free < plan["disk_admission_gib"] * (
                    1 << 30
                ):
                    fatal = "disk admission floor reached; no task silently skipped"
                    break
                key = f"{cursor}-successor"
                command = [
                    sys.executable,
                    plan["entrypoint"],
                    "episode",
                    "--plan",
                    str(root / "plan.json"),
                    "--sha256",
                    digest,
                    "--authorization",
                    str(authorization),
                    "--index",
                    str(cursor),
                ]
                active[key] = jobs.Job(
                    command, root / f"{key}.log", plan["episode_secs"]
                )
                cursor += 1
            for key, job in list(active.items()):
                code = job.status()
                if code is None and time.monotonic() < job.deadline:
                    continue
                if code is None:
                    jobs.cancel_all([job])
                    code = -1
                else:
                    job.signal(signal.SIGTERM)
                    job.close()
                del active[key]
                cleanup = jobs.cleanup_containers(digest, key)
                plans.publish(root / f"{key}-supervisor-cleanup.json", cleanup)
                result_path = root / "runs" / key / "result.json"
                result = (
                    json.loads(result_path.read_text()) if result_path.is_file() else {}
                )
                index = int(key.split("-", 1)[0])
                identity_ok = (
                    result.get("episode"),
                    result.get("task"),
                    result.get("arm"),
                ) == (key, plan["tasks"][index], "successor")
                item = {
                    "episode": key,
                    "status": result.get("status", "unreported"),
                    "exit_code": code,
                    "wall_secs": time.monotonic() - job.started,
                }
                completed.append(item)
                print(json.dumps(item), flush=True)
                if (
                    code != 0
                    or not identity_ok
                    or result.get("status") not in ("scored", "failed")
                ):
                    fatal = f"{key} infrastructure/integrity failure; no replacement"
                report.write(plan)
            status = {
                "status": "draining" if fatal else "running",
                "active": {key: job.pid for key, job in active.items()},
                "completed": completed,
                "next_index": cursor,
                "error": fatal,
            }
            temporary = root / "supervisor.partial"
            temporary.write_text(json.dumps(status, indent=2) + "\n")
            temporary.replace(root / "supervisor.json")
            (root / "STATUS.md").write_text(
                f"# {status['status']}\n\nCompleted {len(completed)}/200; active {len(active)}; admitted indices 0..{cursor - 1}.\nNo retries. Research disabled.\nError: {fatal}\nSee supervisor.json, budget.sqlite and runs/.\n"
            )
            if fatal and not active:
                break
            time.sleep(2)
    except BaseException as error:
        fatal = type(error).__name__
    finally:
        cleanup_errors = []
        try:
            jobs.cancel_all(list(active.values()))
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
        for key in active:
            try:
                plans.publish(
                    root / f"{key}-supervisor-cleanup.json",
                    jobs.cleanup_containers(digest, key),
                )
            except Exception as error:
                cleanup_errors.append(f"{key}:{type(error).__name__}")
        if cleanup_errors:
            fatal = "cleanup unresolved; " + ", ".join(cleanup_errors)
    terminal = {
        "status": "stopped" if fatal else "completed",
        "episodes": completed,
        "error": fatal,
        "budget": budgets.status(root / "budget.sqlite", digest, plan["limits"]),
        "benefit": "NOT_ESTABLISHED_BY_SINGLE_ARM",
        "restarts": 0,
        "scored_tasks": sum(item["status"] == "scored" for item in completed),
        "cleanup_errors": cleanup_errors,
    }
    plans.publish(root / "terminal.json", terminal)
    report.write(plan)
    (root / "STATUS.md").write_text(
        f"# {terminal['status']}\n\nTerminal slots: {len(completed)}/200. No further launches.\nError: {fatal}\nSee terminal.json; missing scores are not zeros.\n"
    )
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "seal", "run", "episode"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "stage":
        print(json.dumps(inputs.stage(args.root, args.source_registry)))
        return
    if args.command == "seal":
        print(json.dumps(inputs.seal(args.root, args.binary)))
        return
    plan = verify(
        args.plan, args.sha256, args.index if args.command == "episode" else None
    )
    plans.authorize(plan, args.sha256, args.authorization)

    def interrupted(_number, _frame):
        raise KeyboardInterrupt("owned sweep interrupted; no automatic restart")

    signal.signal(signal.SIGTERM, interrupted)
    if args.command == "episode":
        raise SystemExit(episode(plan, args.sha256, args.index))
    result = run(plan, args.sha256, args.authorization)
    print(json.dumps(result))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
