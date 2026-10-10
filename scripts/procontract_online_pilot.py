#!/usr/bin/env python3
"""Fresh, pinned native online-learning pilot. `prepare` is inference-free.

`run` requires a separately recorded operator budget decision. Exactly six task
slots, at most three one-attempt research turns; no terminal study restart.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_online as online
from procontract_online_lineage import Lineage
import procontract_online_plan as plans
from procontract_online_runtime import OnlineRuntime
import procontract_study_budget as budgets


def episode(plan, digest, index, arm):
    if type(index) is not int or not 0 <= index < 3 or arm not in plan["arms"]:
        raise ValueError("episode outside frozen plan")
    root = Path(plan["root"])
    if (root / "terminal.json").exists():
        raise ValueError("terminal pilot cannot launch another episode")
    launch = json.loads((root / "launch.json").read_text())
    if launch.get("plan_sha256") != digest:
        raise ValueError("episode requires its supervisor launch identity")
    task = plan["tasks"][index]
    key = f"{index}-{arm}"
    run = root / "runs" / key
    registry = canonical.configure(Path(plan["registry"]), plan["registry_sha256"])
    canonical.bind_pins(plan["pins_sha256"])
    canonical.preflight()
    research_secs = plan["research_secs"] if arm == "adaptive" else 0
    reservation = budgets.reserve(
        root / "budget.sqlite",
        digest,
        key,
        "task",
        plan["episode_secs"] - research_secs,
        plan["limits"],
        {
            "task": task,
            "arm": arm,
            "model": plan["model"],
            "native": plans.sha(Path(plan["binary"])),
        },
    )
    learning_reservation = None
    if arm == "adaptive":
        learning_reservation = budgets.reserve(
            root / "budget.sqlite",
            digest,
            key + ":research",
            "learning",
            research_secs,
            plan["limits"],
            {"episode": key, "one_attempt": True},
        )
    common = dict(
        arm="on",
        run_dir=run,
        instance=task,
        image=registry.tasks[task]["image"],
        codex_bin=Path(plan["binary"]),
        model=plan["model"],
        effort=plan["effort"],
        prompt=Path(plan["prompt"]),
        study_manifest=None,
        study_sha256=None,
        workspace_from=None,
        no_reference=False,
        instructions="executor.md",
        policy=None,
        stop_after_issue=False,
        delivery_reserve_secs=0,
    )
    # Both arms receive the same seed P. Adaptive successors are additionally
    # supplied through the recorded runtime input, never copied into the evaluator.
    policy = root / "seed-policy"
    common["policy"] = policy
    runner.prepare(SimpleNamespace(**common))
    plans.publish(
        run / "pilot-reservation.json",
        {"task": reservation, "research": learning_reservation},
    )
    # A frozen arm executes the same seed H without any learning calls.
    if arm == "frozen":
        (run / "policy/harness.json").write_bytes(
            online.encoded(plan["seed"]["harness"])
        )
        manifest = json.loads((run / "manifest.json").read_text())
        program = runner.harness_program.load(run / "policy")
        manifest["harness_program"] = {
            "sha256": program.digest,
            "interpreter": program.interpreter,
        }
        (run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    learning = None
    try:
        if arm == "adaptive":
            key_value = runner.current_key(os.environ)
            if not key_value:
                raise ValueError("no provider credential; task slot remains spent")
            learning = OnlineRuntime(
                Lineage(root / "lineage"),
                key,
                run / "online",
                Path(plan["binary"]),
                plan["provider"],
                key_value,
                total_secs=plan["inference_secs"],
                research_secs=research_secs,
            )
        runner.run(
            SimpleNamespace(
                **common, deadline_secs=plan["inference_secs"] - research_secs
            ),
            learning=learning,
        )
    finally:
        if learning is not None:
            learning.close()
    summary = json.loads((run / "run.json").read_text())
    if (
        summary.get("runner_error")
        or summary.get("server_exited_early")
        or (summary.get("turn_statuses") or [None])[-1] == "failed"
    ):
        raise RuntimeError(
            "native execution infrastructure failed; no replacement task run"
        )
    archive = canonical.package_submission(run)
    started = time.monotonic()
    command = canonical.worker_command(
        "evaluate", "--task", task, "--archive", archive, "--output", run / "eval"
    )
    with (run / "canonical.log").open("x") as log:
        subprocess.run(
            command,
            env=canonical.evaluator_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=plan["grading_secs"],
            check=True,
        )
    outcome = json.loads((run / "eval/canonical-result.json").read_text())
    if (
        outcome.get("valid") is not True
        or outcome["total"] != registry.tasks[task]["total"]
        or outcome["submission_sha256"] != plans.sha(archive)
    ):
        raise RuntimeError(
            "invalid frozen canonical outcome; never convert to reward 0"
        )
    if arm == "adaptive":
        Lineage(root / "lineage").reward(
            key,
            resolved=outcome["resolved"],
            total=outcome["total"],
            submission_sha256=outcome["submission_sha256"],
            evaluator_sha256=plan["pins_sha256"],
        )
    result = {
        "task": task,
        "arm": arm,
        "episode": key,
        "outcome": outcome,
        "grading_elapsed_secs": time.monotonic() - started,
        "native_contract": summary.get("status"),
        "native_cost": summary.get("cost"),
        "online": summary.get("online_learning"),
        "claims": "descriptive functional outcome; no stable promotion or independent compliance proof",
    }
    plans.publish(run / "result.json", result)
    return result


def run(plan, digest, authorization):
    root = Path(plan["root"])
    authorized = plans.authorize(plan, digest, authorization)
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
    (seed / "executor.md").write_text(plan["seed"]["execution"])
    terminal = {"status": "running", "episodes": [], "restarts": 0}
    process = None
    try:
        for index, task in enumerate(plan["tasks"]):
            # Alternate arm order; adaptive lineage sees only its own earlier feedback.
            for arm in plan["arms"] if index % 2 == 0 else list(reversed(plan["arms"])):
                key = f"{index}-{arm}"
                plans.verify(root / "online-plan.json", digest)
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "episode",
                    "--plan",
                    str(root / "online-plan.json"),
                    "--plan-sha256",
                    digest,
                    "--authorization",
                    str(authorization),
                    "--index",
                    str(index),
                    "--arm",
                    arm,
                ]
                with (root / f"{key}.log").open("x") as log:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    try:
                        code = process.wait(timeout=plan["episode_secs"])
                    except BaseException:
                        os.killpg(process.pid, signal.SIGINT)
                        try:
                            process.wait(timeout=45)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                        raise
                process = None
                if code != 0:
                    raise RuntimeError(f"{key} exited {code}; stop without replacement")
                terminal["episodes"].append({"task": task, "episode": key})
                print(json.dumps(terminal["episodes"][-1]), flush=True)
        terminal["status"] = "completed"
    except BaseException as error:
        terminal.update(
            status="stopped",
            error={"type": type(error).__name__, "message": str(error)[:500]},
        )
    terminal["budget"] = budgets.status(root / "budget.sqlite", digest, plan["limits"])
    plans.publish(root / "terminal.json", terminal)
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "episode"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--index", type=int)
    parser.add_argument("--arm", choices=("frozen", "adaptive"))
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "prepare":
        result = plans.prepare(
            args.root, args.source_registry, args.binary, args.prompt
        )
    else:
        plan = plans.verify(args.plan, args.plan_sha256)
        if plan["entrypoint"] != str(Path(__file__).resolve()):
            parser.error("run the frozen controller entrypoint recorded in the plan")
        plans.authorize(plan, args.plan_sha256, args.authorization)

        # Interruption must unwind native/research cleanup rather than leave a paid worker.
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt("pilot interrupted; no restart")

        signal.signal(signal.SIGTERM, interrupted)
        result = (
            run(plan, args.plan_sha256, args.authorization)
            if args.command == "run"
            else episode(plan, args.plan_sha256, args.index, args.arm)
        )
    print(json.dumps(result, indent=2))
    if result.get("status") == "stopped":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
