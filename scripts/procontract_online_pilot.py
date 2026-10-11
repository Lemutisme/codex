#!/usr/bin/env python3
"""Fresh, pinned native online-learning pilot. `prepare` is inference-free.

`run` requires a recorded operator authorization. Three task slots by default;
six only for an explicitly selected paired plan. At most three one-attempt research
turns; no terminal study restart.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_online as online
from procontract_online_lineage import Lineage
from procontract_online_failure import ContractUnavailable, contained_contract_failure
import procontract_online_plan as plans
from procontract_online_runtime import OnlineRuntime
from procontract_online_trace import OnlineTrace
import procontract_study_budget as budgets
import procontract_owned_process as owned_process
import procontract_online_acceptance as acceptance


def episode(plan, digest, index, arm):
    if (
        type(index) is not int
        or not 0 <= index < len(plan["tasks"])
        or arm not in plan["arms"]
    ):
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
    # Benchmark dependencies belong to the registry-pinned evaluator interpreter,
    # not the generic Codex/controller Python environment.
    subprocess.run(
        canonical.worker_command("preflight"),
        env=canonical.evaluator_env(),
        stdout=subprocess.DEVNULL,
        check=True,
    )
    if run.exists():
        raise budgets.AlreadyClaimed("episode directory already exists; no restart")
    lineage = (
        Lineage(
            root / "lineage",
            selection_scope=digest,
            selection_mode=plan["selection_mode"],
        )
        if arm == "adaptive"
        else None
    )
    allocation = (
        lineage.begin(key, plan["inference_secs"], plan["research_secs"])
        if lineage
        else None
    )
    research_secs = allocation["research_secs"] if allocation else 0
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
    if research_secs:
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
    # Frozen and hold controllers execute seed/selected P without a fake checkpoint.
    # The same kernel and ProContract remain enabled in every arm.
    learning = None
    observed = OnlineTrace(run, digest)
    try:
        if arm == "adaptive":
            key_value = runner.current_key(os.environ)
            if not key_value:
                raise ValueError("no provider credential; task slot remains spent")
            learning = OnlineRuntime(
                lineage,
                key,
                run / "online",
                Path(plan["binary"]),
                plan["provider"],
                key_value,
                total_secs=plan["inference_secs"],
                research_secs=research_secs,
                allocation=allocation,
            )
        runner.run(
            SimpleNamespace(
                **common, deadline_secs=plan["inference_secs"] - research_secs
            ),
            learning=learning,
            online_trace=observed,
        )
    except ContractUnavailable:
        # Classify only AFTER both runtime and trace cleanup have succeeded.
        pass
    finally:
        try:
            if learning is not None:
                learning.close()
        finally:
            observed.close()
    summary = json.loads((run / "run.json").read_text())
    if failure := contained_contract_failure(summary):
        bound = plans.sha(run / "run.json")
        if lineage is not None:
            lineage.fail_episode(
                key,
                reason=failure["reason"],
                summary_sha256=bound,
                native_exit=summary["native_process_exit"],
            )
        result = {
            "task": task,
            "arm": arm,
            "episode": key,
            "status": "failed",
            "outcome": None,
            "failure": failure,
            "native_summary_sha256": bound,
            "native_contract": summary["status"],
            "online": summary.get("online_learning"),
            "claims": "contained failure; no canonical score, reward or refund",
        }
        plans.publish(run / "result.json", result)
        return result
    if (
        summary.get("runner_error")
        or summary.get("native_process_exit", {}).get("status") != "exited"
        or type(summary.get("native_process_exit", {}).get("returncode")) is not int
        or summary["native_process_exit"]["returncode"] != 0
        or summary.get("server_exited_early")
        or (summary.get("turn_statuses") or [None])[-1] == "failed"
    ):
        raise RuntimeError(
            "native execution infrastructure failed; no replacement task run"
        )
    if not (summary.get("status") or {}).get("contract_id"):
        raise RuntimeError("required ProContract task contract was never issued")
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
    grading_elapsed = time.monotonic() - started
    learning_reward = None
    if arm == "adaptive":
        terminal = summary["online_learning"]
        research = terminal.get("research")
        # Missing researcher timing is not free research. No attempted call means 0.
        research_elapsed = (
            research.get("elapsed_secs")
            if research
            else (None if learning.future is not None else 0)
        )
        trace = summary.get("native_notice_trace", {})
        witnessed = trace.get("evidence", {}).get("status") == "observed"
        learning_reward = lineage.reward(
            key,
            resolved=outcome["resolved"],
            total=outcome["total"],
            submission_sha256=outcome["submission_sha256"],
            evaluator_sha256=plan["pins_sha256"],
            selection_evidence={
                "native_secs": summary.get("elapsed_secs"),
                "research_secs": research_elapsed,
                "grading_secs": grading_elapsed,
                "episode_secs": plan["episode_secs"],
                **terminal["command_metrics"],
                "input_witness": online.digest(trace) if witnessed else None,
            },
        )
    result = {
        "task": task,
        "arm": arm,
        "episode": key,
        "status": "scored",
        "outcome": outcome,
        "grading_elapsed_secs": grading_elapsed,
        "learning_reward": learning_reward,
        "native_contract": summary.get("status"),
        "native_cost": summary.get("cost"),
        "online": summary.get("online_learning"),
        "native_context_evidence": summary.get("native_notice_trace"),
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
    (seed / "executor.md").write_text(online.instructions(plan["seed"]))
    terminal = {"status": "running", "episodes": [], "restarts": 0}
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
                    code = owned_process.run(
                        command, stdout=log, timeout=plan["episode_secs"]
                    )
                if code != 0:
                    raise RuntimeError(f"{key} exited {code}; stop without replacement")
                result = json.loads((root / "runs" / key / "result.json").read_text())
                if (result.get("task"), result.get("episode"), result.get("arm")) != (
                    task,
                    key,
                    arm,
                ) or result.get("status") not in ("scored", "failed"):
                    raise RuntimeError("episode result identity or status is invalid")
                terminal["episodes"].append(
                    {"task": task, "episode": key, "status": result["status"]}
                )
                print(json.dumps(terminal["episodes"][-1]), flush=True)
        terminal["status"] = (
            "completed_with_failures"
            if any(e["status"] == "failed" for e in terminal["episodes"])
            else "completed"
        )
    except BaseException as error:
        terminal.update(
            status="stopped",
            error={"type": type(error).__name__, "message": str(error)[:500]},
        )
    try:
        evidence = acceptance.collect(plan)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        evidence = {
            "status": "FAIL",
            "error": type(error).__name__,
            "scope": "acceptance evidence unavailable",
        }
    plans.publish(root / "acceptance.json", evidence)
    terminal["mechanism_acceptance"] = evidence["status"]
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
    parser.add_argument("--comparison", choices=("stream", "paired"), default="stream")
    parser.add_argument(
        "--selection-mode", choices=("deployment", "coverage"), default="deployment"
    )
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--index", type=int)
    parser.add_argument("--arm", choices=("frozen", "adaptive"))
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "prepare":
        result = plans.prepare(
            args.root,
            args.source_registry,
            args.binary,
            args.prompt,
            comparison=args.comparison,
            selection_mode=args.selection_mode,
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
    if (
        result.get("status") in ("stopped", "completed_with_failures")
        or args.command == "run"
        and plan["selection_mode"] == "coverage"
        and result.get("mechanism_acceptance") != "PASS"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
