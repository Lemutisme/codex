#!/usr/bin/env python3
"""Frozen, experiment-only ProgramBench adapter. No model calls in CLI commands.

`freeze` pins evaluator/source fixtures/images/wheels/cached test blobs.
`preflight` verifies the pins. `null` evaluates an exit-1 sentinel, without Codex.
`score` validates a raw eval against the canonical fixed eligible-test denominator.
CanonicalProgramBench is imported by the protected RSI campaign driver.
"""

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SETUP = Path(__file__).resolve().parent
SCRIPTS = Path(
    os.environ.get(
        "PROCONTRACT_FROZEN_SCRIPTS",
        "/home/duozhou/codex-worktrees/procontract-rsi-integrated-20261007/scripts",
    )
)
PROGRAMBENCH = Path("/home/duozhou/ProgramBench-native-advisory")
PB_HEAD = "cdbe48cb88aad752ed099b4a4429ef9476c54c65"
HF_REVISION = "de0ddfb637590c7ecb54fa0b5301f6dc7dfbcee5"
CACHE = Path("/home/duozhou/run-artifacts/programbench-native-advisory-3-20261006")
WHEELHOUSE = CACHE / "evaluator-wheelhouse"
BLOBS = CACHE / "campaign/evaluation-blobs"
PINS_FILE = SETUP / "canonical-pins.json"
PB_PYTHON = PROGRAMBENCH / ".venv/bin/python"
TASKS = {
    "antonmedv__fx.86d0d34": {
        "total": 2044,
        "image": "sha256:3b3452e01006c3db9bd5681931519577ac229c7edfb77fa7c545a74a8faa8cf4",
    },
    "cheat__cheat.b8098dc": {
        "total": 297,
        "image": "sha256:bf2704bccabd5f13d0070921fd3904d095694b1af5ce7567b213c1efd11e30ba",
    },
    "hush-shell__hush.560c33a": {
        "total": 1201,
        "image": "sha256:e31041a5c2c1aad78e60b8a85b7a95099c94fa1ec963bc8412c3094b17a6142d",
    },
}

sys.path.insert(0, str(SCRIPTS))
import procontract_evaluation as packaging  # noqa: E402 (frozen checkout, not an installed package)
import procontract_rsi as rsi  # noqa: E402 (frozen checkout, not an installed package)
import procontract_store as store  # noqa: E402 (frozen checkout, not an installed package)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def pb_imports():
    sys.path.insert(0, str(PROGRAMBENCH))
    sys.path.insert(0, str(PROGRAMBENCH / "src"))
    from programbench.constants import TASKS_DIR
    from programbench.utils.load_data import (
        load_all_instances,
        get_active_branches,
        get_ignored_tests,
    )
    from scripts.campaign_evaluate import validate_evaluation

    return (
        TASKS_DIR,
        load_all_instances,
        get_active_branches,
        get_ignored_tests,
        validate_evaluation,
    )


def fixture(task):
    _, load, _, _, _ = pb_imports()
    return next(instance for instance in load() if instance["instance_id"] == task)


def image_tag(task):
    return f"programbench/{task.replace('__', '_1776_')}:task_cleanroom_v6"


def pin_state():
    tasks_dir, _, active, ignored, _ = pb_imports()
    head = subprocess.check_output(
        ["git", "-C", str(PROGRAMBENCH), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != PB_HEAD:
        raise RuntimeError(f"ProgramBench source revision drift: {head}")
    # Ignore generated untracked files; all tracked evaluator and fixture code must be pristine.
    for args in (["diff", "--quiet"], ["diff", "--cached", "--quiet"]):
        subprocess.run(["git", "-C", str(PROGRAMBENCH), *args], check=True)
    fixtures = {}
    images = {}
    for task, expected in TASKS.items():
        instance = fixture(task)
        eligible = {
            f"{branch}/{name}"
            for branch in active(instance)
            for name in instance["branches"][branch]["tests"]
            if f"{branch}/{name}" not in ignored(instance)
        }
        if len(eligible) != expected["total"]:
            raise RuntimeError(
                f"Canonical denominator drift for {task}: {len(eligible)}"
            )
        fixtures[task] = {
            "eligible_count": len(eligible),
            "files": {
                str(path.relative_to(tasks_dir)): sha256(path)
                for path in sorted((tasks_dir / task).iterdir())
                if path.is_file()
            },
        }
        actual = subprocess.check_output(
            ["docker", "image", "inspect", image_tag(task), "--format", "{{.Id}}"],
            text=True,
        ).strip()
        if actual != expected["image"]:
            raise RuntimeError(f"Cleanroom image drift for {task}: {actual}")
        subprocess.run(
            ["docker", "image", "inspect", actual],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        images[task] = {"tag": image_tag(task), "id": actual}
    cached = json.loads((CACHE / "campaign/evaluation-inputs.json").read_text())
    if cached["commit"] != HF_REVISION or Path(cached["blob_root"]) != BLOBS:
        raise RuntimeError("Cached fixture revision/root drift")
    blobs = {
        name: digest
        for name, digest in cached["blob_sha256"].items()
        if name.split("/")[0] in TASKS
    }
    for name, expected in blobs.items():
        path = BLOBS / name
        if path.is_symlink() or sha256(path) != expected:
            raise RuntimeError(f"Cached fixture hash mismatch: {name}")
    wheels = {
        path.name: sha256(path)
        for path in sorted(WHEELHOUSE.iterdir())
        if path.is_file()
    }
    if not wheels:
        raise RuntimeError("No offline evaluator wheels")
    return {
        "schema": 1,
        "programbench": str(PROGRAMBENCH),
        "programbench_head": head,
        "uv_lock_sha256": sha256(PROGRAMBENCH / "uv.lock"),
        "hf_revision": HF_REVISION,
        "fixtures": fixtures,
        "images": images,
        "blob_root": str(BLOBS),
        "blob_sha256": blobs,
        "wheelhouse": str(WHEELHOUSE),
        "wheel_sha256": wheels,
        "metric": "official_fixed_eligible_tests_last_outcome",
        "skipped_policy": "nonpassed",
        "branch_error_policy": "invalid",
        "evaluator_attempts": 2,
        "branch_workers": 1,
        "branch_retries": 1,
        "docker_cpus": 4,
    }


def preflight():
    expected = json.loads(PINS_FILE.read_text())
    current = pin_state()
    if current != expected:
        changed = sorted(
            key
            for key in set(current) | set(expected)
            if current.get(key) != expected.get(key)
        )
        raise RuntimeError(f"Frozen canonical evaluator pins drifted: {changed}")
    return {
        "valid": True,
        "pins_sha256": sha256(PINS_FILE),
        "totals": {task: spec["total"] for task, spec in TASKS.items()},
    }


def canonical_score(task, eval_json, output):
    preflight()
    _, _, active, ignored, validate = pb_imports()
    instance = fixture(task)
    validated = validate(Path(eval_json), instance)
    data = dataclasses.asdict(validated)
    utility = data.pop("utility")
    reasons = list(data["reasons"])
    if validated.total != TASKS[task]["total"]:
        reasons.append(f"canonical_denominator_mismatch:{validated.total}")
    valid = validated.valid and not reasons
    data.update(
        task=task,
        valid=valid,
        reasons=reasons,
        pass_rate=float(utility) if valid and utility is not None else None,
        utility_fraction=str(utility) if utility is not None else None,
        pins_sha256=sha256(PINS_FILE),
        eval_json=str(Path(eval_json).resolve()),
    )
    # Full eligible-case vector is only emitted after task delivery, never at prepare time.
    outcomes = {}
    if valid:
        raw = json.loads(Path(eval_json).read_text())
        branches = set(active(instance))
        excluded = ignored(instance)
        for record in raw["test_results"]:
            key = f"{record['branch']}/{record['name']}"
            if record["branch"] in branches and key not in excluded:
                outcomes[key] = {
                    "passed": record["status"] == "passed",
                    "message": str(
                        (record.get("extra") or {}).get("message") or record["status"]
                    )[: rsi.OUTCOME_MESSAGE_CAP],
                }
        if (
            len(outcomes) != validated.total
            or sum(row["passed"] for row in outcomes.values()) != validated.resolved
        ):
            raise RuntimeError("Canonical scalar and feedback vector disagree")
    write_json(output, data)
    write_json(Path(output).with_name("canonical-feedback.json"), outcomes)
    return data


def evaluator_env():
    # Model credentials are never forwarded to evaluator subprocesses.
    keep = (
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "XDG_RUNTIME_DIR",
        "PROCONTRACT_FROZEN_SCRIPTS",
    )
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(
        PROGRAMBENCH_HF_REVISION=HF_REVISION,
        PROGRAMBENCH_BLOB_DIR=str(BLOBS),
        PROGRAMBENCH_EVAL_WHEELHOUSE=str(WHEELHOUSE),
        PROGRAMBENCH_SAFE_REPORTING="1",
        PYTHONDONTWRITEBYTECODE="1",
        HF_HUB_OFFLINE="1",
    )
    return env


def evaluate_one(task, archive, eval_json):
    preflight()
    _, _, active, ignored, _ = pb_imports()
    from programbench.eval.eval import Evaluator
    from programbench.utils.load_data import get_ignored_branches

    instance = fixture(task)
    branches = active(instance)
    image_name, image_digest = TASKS[task]["image"].split(":", 1)
    evaluator = Evaluator(
        image_name=image_name,
        image_tag=image_digest,
        solution_branch="submission",
        submission_archive=Path(archive),
        blob_dir=BLOBS / task,
        tests_branches=branches,
        tests_by_branch={
            branch: instance["branches"][branch]["tests"] for branch in branches
        },
        ignored_tests=ignored(instance),
        ignored_branches=get_ignored_branches(instance),
        remove_hashes=instance.get("eval_clean_hashes", []),
        instance_id=task,
        docker_cpus=4,
        branch_workers=1,
        branch_retries=1,
    )
    result = evaluator.run()
    Path(eval_json).parent.mkdir(parents=True, exist_ok=True)
    Path(eval_json).write_text(result.model_dump_json(indent=2) + "\n")
    return canonical_score(
        task, eval_json, Path(eval_json).with_name("canonical-score.json")
    )


def evaluate_archive(task, archive, work):
    """Two maximum evaluator attempts; source package immutable, no inference reruns."""
    archive, work = Path(archive), Path(work)
    digest = sha256(archive)
    for attempt in (1, 2):
        directory = work / f"attempt-{attempt}" / task
        directory.mkdir(parents=True, exist_ok=True)
        frozen = directory / "submission.tar.gz"
        if not frozen.exists():
            shutil.copyfile(archive, frozen)
        if sha256(frozen) != digest:
            raise RuntimeError("Frozen evaluator subject changed across attempts")
        eval_json = directory / f"{task}.eval.json"
        score_file = directory / "canonical-score.json"
        receipt = directory / "evaluation-receipt.json"
        if not receipt.exists():
            command = [
                str(PB_PYTHON),
                str(Path(__file__).resolve()),
                "evaluate-one",
                "--task",
                task,
                "--archive",
                str(frozen),
                "--eval-json",
                str(eval_json),
            ]
            started = time.monotonic()
            with (directory / "eval.log").open("w") as log:
                process = subprocess.run(
                    command,
                    cwd=PROGRAMBENCH,
                    env=evaluator_env(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            write_json(
                receipt,
                {
                    "command": command,
                    "exit_code": process.returncode,
                    "elapsed_seconds": time.monotonic() - started,
                    "submission_sha256": digest,
                    "image": TASKS[task]["image"],
                    "pins_sha256": sha256(PINS_FILE),
                },
            )
        outcome = (
            json.loads(score_file.read_text())
            if score_file.exists()
            else {"valid": False, "reasons": ["evaluator_process_failed"]}
        )
        if outcome["valid"]:
            # Verify even on resume; never trust a stale scalar without its bound raw evidence.
            outcome = canonical_score_subprocess(task, eval_json, score_file)
            if not outcome["valid"]:
                raise RuntimeError("Completed evaluation failed revalidation")
            outcome.update(
                attempts=attempt,
                submission_sha256=digest,
                feedback_json=str(directory / "canonical-feedback.json"),
            )
            write_json(work / "canonical-result.json", outcome)
            return outcome
    write_json(work / "canonical-invalid.json", outcome)
    raise RuntimeError(
        f"Canonical evaluator invalid for {task} after 2 attempts on frozen submission; "
        f"no new model attempt permitted. See {work / 'canonical-invalid.json'}"
    )


def canonical_score_subprocess(task, eval_json, output):
    command = [
        str(PB_PYTHON),
        str(Path(__file__).resolve()),
        "score",
        "--task",
        task,
        "--eval-json",
        str(eval_json),
        "--output",
        str(output),
    ]
    subprocess.run(
        command,
        cwd=PROGRAMBENCH,
        env=evaluator_env(),
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return json.loads(Path(output).read_text())


class CanonicalProgramBench(rsi.ProgramBench):
    """Same ProContract harness, with image pinning and official canonical labels."""

    def evaluator(self):
        return {
            "programbench": PB_HEAD,
            "hf_revision": HF_REVISION,
            "metric": "official_fixed_eligible_tests_last_outcome",
            "pins_sha256": sha256(PINS_FILE),
        }

    def environment(self):
        return {
            **super().environment(),
            "cleanrooms": {task: spec["image"] for task, spec in TASKS.items()},
        }

    def run_and_label(self, host, bundle, task, run_dir):
        if task not in TASKS:
            raise RuntimeError(f"Task outside frozen three-program evaluation: {task}")
        subprocess.run(
            [str(PB_PYTHON), str(Path(__file__).resolve()), "preflight"],
            cwd=PROGRAMBENCH,
            env=evaluator_env(),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        if (
            self.terms["programbench_head"] != PB_HEAD
            or self.terms["hf_revision"] != HF_REVISION
        ):
            raise RuntimeError(
                "Campaign evaluator identity differs from frozen adapter"
            )
        earlier_paid = [
            path
            for path in run_dir.parent.glob("attempt-*/inference-started.json")
            if path.parent != run_dir
        ]
        if earlier_paid:
            raise RuntimeError(
                "An earlier paid attempt exists; reconcile its frozen output instead of rerunning inference"
            )
        common = [
            "--arm",
            "on",
            "--instance",
            task,
            "--run-dir",
            str(run_dir),
            "--codex-bin",
            self.terms["codex_bin"],
            "--image",
            TASKS[task]["image"],
        ]
        if not (run_dir / "run.json").exists():
            if (run_dir / "inference-started.json").exists():
                raise RuntimeError(
                    f"Inference attempt has no terminal receipt; manual reconciliation required: {run_dir}"
                )
            prepare = common + [
                "--prompt",
                self.terms["task_prompt"],
                "--policy",
                str(bundle),
                "--model",
                self.terms["model"],
                "--effort",
                self.terms["effort"],
            ]
            subprocess.run([*host.runner, "prepare", *prepare], check=True)
            write_json(
                run_dir / "inference-started.json",
                {"model": self.terms["model"], "effort": self.terms["effort"]},
            )
            subprocess.run(
                [
                    *host.runner,
                    "run",
                    *common,
                    "--deadline-secs",
                    str(self.terms["task_deadline_secs"]),
                ],
                check=False,
            )
        manifest = json.loads((run_dir / "manifest.json").read_text())
        if any(
            manifest.get(key) != self.terms[key]
            for key in ("model", "effort", "codex_sha256")
        ):
            raise RuntimeError(
                "Actual run binary/model/effort differs from campaign identity"
            )
        if manifest.get("prompt_sha256") != self.terms["task_prompt_sha256"]:
            raise RuntimeError("Actual task prompt differs from campaign identity")
        if manifest.get("image") != TASKS[task]["image"]:
            raise RuntimeError("Actual inference image differs from frozen cleanroom")
        summary = json.loads((run_dir / "run.json").read_text())
        if (summary.get("turn_statuses") or [""])[-1] == "failed" or summary.get(
            "server_exited_early"
        ):
            raise RuntimeError(f"Executor failed; no automatic paid rerun: {run_dir}")
        archive = run_dir / "submission.tar.gz"
        if not archive.exists():
            packaging.package(run_dir / "workspace", archive)
        outcome = evaluate_archive(task, archive, run_dir / "eval")
        shutil.copyfile(outcome["feedback_json"], run_dir / "canonical-feedback.json")
        rsi.compact(run_dir)
        failures = []
        for name, record in self.outcomes(run_dir).items():
            if not record["passed"] and len(failures) < 40:
                failures.append(
                    f"{name.rsplit('.', 1)[-1]}: {record['message'].splitlines()[0][:200] if record['message'] else 'nonpassed'}"
                )
        label = {
            "task": task,
            "evaluator_epoch": store.digest("epoch", self.evaluator()),
            "validity": "valid",
            "reason": "",
            "attempts": outcome["attempts"],
            "outcome": {
                "pass_rate": outcome["pass_rate"],
                "passed": outcome["resolved"],
                "counted": outcome["total"],
            },
            "canonical": outcome,
        }
        return {
            "validity": "valid",
            "pass_rate": outcome["pass_rate"],
            "status": summary.get("status"),
            "cost": summary.get("cost"),
            "failures": "\n".join(failures),
            "label": label,
        }

    def outcomes(self, run_dir):
        return json.loads((Path(run_dir) / "canonical-feedback.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["freeze", "preflight", "score", "evaluate-one", "evaluate", "null"],
    )
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--eval-json", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        if PINS_FILE.exists():
            result = preflight()
        else:
            write_json(PINS_FILE, pin_state())
            result = preflight()
    elif args.command == "preflight":
        result = preflight()
    elif args.command == "score":
        result = canonical_score(args.task, args.eval_json, args.output)
    elif args.command == "evaluate-one":
        result = evaluate_one(args.task, args.archive, args.eval_json)
    elif args.command == "evaluate":
        result = evaluate_archive(args.task, args.archive, args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        archive = packaging.null_package(args.output / "submission.tar.gz")
        result = evaluate_archive(args.task, archive, args.output / "eval")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
