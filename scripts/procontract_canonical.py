#!/usr/bin/env python3
"""Registry-pinned canonical ProgramBench adapter. No model calls in CLI commands.

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
from pathlib import PurePosixPath

import procontract_canonical_registry as registries
import procontract_canonical_recovery as recovery
import procontract_evaluation as packaging
import procontract_rsi as rsi

SCRIPTS = Path(__file__).resolve().parent
_REGISTRY = None
_EXPECTED_PINS = None


def configure(path: Path, expected_sha256: str):
    """Bind this process once to an explicitly trusted, frozen registry."""
    global _REGISTRY, PROGRAMBENCH, PB_HEAD, HF_REVISION, PB_PYTHON
    global TASKS, WHEELHOUSE, BLOBS, BLOB_MANIFEST, PINS_FILE
    loaded = registries.load(path, expected_sha256)
    if _REGISTRY is not None and (_REGISTRY.path, _REGISTRY.digest) != (
        loaded.path,
        loaded.digest,
    ):
        raise RuntimeError("a canonical process cannot switch registries")
    _REGISTRY = loaded
    PROGRAMBENCH, PB_HEAD = loaded.programbench, loaded.programbench_head
    HF_REVISION, PB_PYTHON = loaded.hf_revision, loaded.python
    TASKS, WHEELHOUSE, BLOBS = loaded.tasks, loaded.wheelhouse, loaded.blob_root
    BLOB_MANIFEST, PINS_FILE = loaded.blob_manifest, loaded.pins_file
    return loaded


def registry():
    if _REGISTRY is None:
        raise RuntimeError("configure the frozen canonical registry first")
    _REGISTRY.verify_source()
    return _REGISTRY


def checked_pins():
    frozen = registry()
    if _EXPECTED_PINS is not None and sha256(PINS_FILE) != _EXPECTED_PINS:
        raise RuntimeError("canonical pins identity changed")
    pins = json.loads(PINS_FILE.read_text())
    if (pins.get("registry_sha256"), pins.get("adapter_sha256")) != (
        frozen.digest,
        sha256(Path(__file__).resolve()),
    ):
        raise RuntimeError("canonical pins do not bind this registry and adapter")
    return pins


def bind_pins(expected):
    global _EXPECTED_PINS
    if sha256(PINS_FILE) != expected or (
        _EXPECTED_PINS is not None and _EXPECTED_PINS != expected
    ):
        raise RuntimeError("canonical pins identity changed")
    _EXPECTED_PINS = expected


def validate_identity(terms):
    """Static identity gate for campaign entry, cache reads and adoption; no Docker."""
    identity = terms["canonical"]
    frozen = configure(Path(identity["registry_path"]), identity["registry_sha256"])
    frozen.validate_campaign(terms)
    if (sha256(PINS_FILE), sha256(Path(__file__).resolve())) != (
        identity["pins_sha256"],
        identity["adapter_sha256"],
    ):
        raise RuntimeError("frozen canonical pins or adapter identity changed")
    bind_pins(identity["pins_sha256"])
    checked_pins()


def worker_command(command, *args):
    frozen = registry()
    checked_pins()
    return [
        str(PB_PYTHON),
        str(Path(__file__).resolve()),
        command,
        "--registry",
        str(frozen.path),
        "--registry-sha256",
        frozen.digest,
        "--pins-sha256",
        _EXPECTED_PINS or sha256(PINS_FILE),
        *map(str, args),
    ]


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
    return TASKS[task]["image_tag"]


def pin_state():
    frozen = registry()
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
    required_blobs = set()
    for task, expected in TASKS.items():
        instance = fixture(task)
        required_blobs.update(
            f"{task}/tests/{branch}.tar.gz" for branch in active(instance)
        )
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
    cached = json.loads(BLOB_MANIFEST.read_text())
    if cached["commit"] != HF_REVISION or Path(cached["blob_root"]) != BLOBS:
        raise RuntimeError("Cached fixture revision/root drift")
    for name in cached["blob_sha256"]:
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in name
            or str(relative) != name
        ):
            raise RuntimeError("Offline blob path escapes its declared root")
    blobs = {
        name: digest
        for name, digest in cached["blob_sha256"].items()
        if name.split("/")[0] in TASKS
    }
    if missing := required_blobs - blobs.keys():
        raise RuntimeError(
            f"Missing {len(missing)} required offline test blobs: {sorted(missing)[:3]}"
        )
    if BLOBS.is_symlink() or not BLOBS.is_dir():
        raise RuntimeError("Offline blob root must be a regular directory")
    for name, expected in blobs.items():
        relative = PurePosixPath(name)
        path = BLOBS / name
        prefix = BLOBS
        for part in relative.parts:
            prefix = prefix / part
            if prefix.is_symlink():
                raise RuntimeError("Offline blob path contains a symlink")
        if (
            not path.is_file()
            or not path.resolve().is_relative_to(BLOBS.resolve())
            or sha256(path) != expected
        ):
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
        "registry_sha256": frozen.digest,
        "adapter_sha256": sha256(Path(__file__).resolve()),
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
    expected = checked_pins()
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


def attempt_binding(task, archive, attempt):
    return {
        "task": task,
        "attempt": attempt,
        "submission_sha256": sha256(archive),
        "image": TASKS[task]["image"],
        "pins_sha256": _EXPECTED_PINS or sha256(PINS_FILE),
        "registry_sha256": registry().digest,
        "adapter_sha256": sha256(Path(__file__).resolve()),
    }


def terminal_fields(directory, task, exit_code, elapsed):
    paths = {
        "raw_eval_sha256": directory / f"{task}.eval.json",
        "score_sha256": directory / "canonical-score.json",
        "feedback_sha256": directory / "canonical-feedback.json",
    }
    return {
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        **{key: sha256(path) if path.exists() else None for key, path in paths.items()},
    }


def validate_receipt(task, archive, directory):
    """Read-only evidence binding, shared by evaluation resume and Host cache reads."""
    checked_pins()
    digest = sha256(archive)
    if sha256(directory / "submission.tar.gz") != digest:
        raise RuntimeError("Frozen evaluator subject changed across attempts")
    paths = {
        "raw_eval_sha256": directory / f"{task}.eval.json",
        "score_sha256": directory / "canonical-score.json",
        "feedback_sha256": directory / "canonical-feedback.json",
    }
    expected = {
        "submission_sha256": digest,
        "image": TASKS[task]["image"],
        "pins_sha256": sha256(PINS_FILE),
        "registry_sha256": registry().digest,
        "adapter_sha256": sha256(Path(__file__).resolve()),
        **{key: sha256(path) if path.exists() else None for key, path in paths.items()},
    }
    claim = recovery.claimed(directory)
    attempt = claim["binding"].get("attempt")
    if (
        type(attempt) is not int
        or attempt not in (1, 2)
        or directory.parent.name != f"attempt-{attempt}"
    ):
        raise RuntimeError("canonical evaluator attempt identity changed")
    bound = recovery.terminal(directory, attempt_binding(task, archive, attempt))
    if (
        not isinstance(bound, dict)
        or not expected.keys() <= bound.keys()
        or any(bound[key] != value for key, value in expected.items())
    ):
        raise RuntimeError(
            "unbound or changed canonical evaluation receipt; reconcile without rerunning"
        )
    return bound


def evaluate_claimed(task, archive, eval_json):
    """The evaluator worker publishes its own terminal evidence, even if its parent has exited."""
    checked_pins()
    directory = eval_json.parent
    claim = recovery.claimed(directory)
    attempt = claim["binding"].get("attempt")
    if (
        type(attempt) is not int
        or attempt not in (1, 2)
        or directory.parent.name != f"attempt-{attempt}"
        or archive.resolve() != (directory / "submission.tar.gz").resolve()
        or eval_json.name != f"{task}.eval.json"
    ):
        raise RuntimeError("evaluator worker does not match its claimed paths")
    recovery.claimed(directory, attempt_binding(task, archive, attempt))
    if (directory / recovery.TERMINAL).exists():
        raise RuntimeError("evaluator worker already has terminal evidence")
    recovery.enter_worker(directory, claim)
    started = time.monotonic()
    try:
        outcome = evaluate_one(task, archive, eval_json)
    except Exception:
        recovery.finish(
            directory,
            claim,
            terminal_fields(directory, task, 1, time.monotonic() - started),
        )
        raise
    recovery.finish(
        directory,
        claim,
        terminal_fields(directory, task, 0, time.monotonic() - started),
    )
    return outcome


def evaluate_archive(task, archive, work):
    """Two maximum evaluator attempts; source package immutable, no inference reruns."""
    checked_pins()
    archive, work = Path(archive), Path(work)
    digest = sha256(archive)
    for attempt in (1, 2):
        directory = work / f"attempt-{attempt}" / task
        directory.mkdir(parents=True, exist_ok=True)
        frozen = directory / "submission.tar.gz"
        if not frozen.exists():
            recovery.atomic_artifact(
                frozen, lambda target: shutil.copyfile(archive, target)
            )
        if sha256(frozen) != digest:
            raise RuntimeError("Frozen evaluator subject changed across attempts")
        eval_json = directory / f"{task}.eval.json"
        score_file = directory / "canonical-score.json"
        receipt = directory / "evaluation-receipt.json"
        claim, launch = recovery.start(
            directory, attempt_binding(task, archive, attempt)
        )
        if launch:
            command = worker_command(
                "evaluate-one",
                "--task",
                task,
                "--archive",
                frozen,
                "--eval-json",
                eval_json,
            )
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
            # A reaped child is terminal evidence even when it died before publishing its receipt.
            if not receipt.exists():
                recovery.finish(
                    directory,
                    claim,
                    terminal_fields(
                        directory, task, process.returncode, time.monotonic() - started
                    ),
                )
            elif (
                recovery.terminal(directory, claim["binding"])["exit_code"]
                != process.returncode
            ):
                raise RuntimeError(
                    "canonical evaluator exit conflicts with its terminal evidence"
                )
        bound = validate_receipt(task, archive, directory)
        outcome = (
            json.loads(score_file.read_text())
            if score_file.exists()
            else {"valid": False, "reasons": ["evaluator_process_failed"]}
        )
        if bound["exit_code"] != 0:
            outcome = {"valid": False, "reasons": ["evaluator_process_failed"]}
        if outcome["valid"]:
            # Verify even on resume; never trust a stale scalar without its bound raw evidence.
            rechecked = directory / "recheck" / "canonical-score.json"
            outcome = canonical_score_subprocess(task, eval_json, rechecked)
            if outcome != json.loads(score_file.read_text()) or sha256(
                rechecked.with_name("canonical-feedback.json")
            ) != sha256(directory / "canonical-feedback.json"):
                raise RuntimeError(
                    "canonical revalidation differs from the bound score"
                )
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
    command = worker_command(
        "score", "--task", task, "--eval-json", eval_json, "--output", output
    )
    subprocess.run(
        command,
        cwd=PROGRAMBENCH,
        env=evaluator_env(),
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return json.loads(Path(output).read_text())


def package_submission(run_dir):
    """Only canonical submissions use this atomic publication and explicit completeness receipt."""
    archive, receipt = (
        run_dir / "submission.tar.gz",
        run_dir / "submission-receipt.json",
    )
    if archive.exists():
        if not receipt.exists() or json.loads(receipt.read_text()) != {
            "sha256": sha256(archive)
        }:
            raise RuntimeError(
                "canonical submission is partial or unbound; preserve it for reconciliation"
            )
        return archive
    if receipt.exists():
        raise RuntimeError("canonical submission receipt has no archive")
    recovery.atomic_artifact(
        archive, lambda target: packaging.package(run_dir / "workspace", target)
    )
    recovery.atomic_artifact(
        receipt,
        lambda target: target.write_text(json.dumps({"sha256": sha256(archive)})),
    )
    return archive


class CanonicalProgramBench(rsi.ProgramBench):
    """Same ProContract harness, with image pinning and official canonical labels."""

    def __init__(self, terms):
        validate_identity(terms)
        super().__init__(terms)

    def evaluator(self):
        validate_identity(self.terms)
        return {
            "registry_sha256": registry().digest,
            "programbench": PB_HEAD,
            "hf_revision": HF_REVISION,
            "metric": "official_fixed_eligible_tests_last_outcome",
            "pins_sha256": sha256(PINS_FILE),
        }

    def environment(self):
        validate_identity(self.terms)
        return {
            **super().environment(),
            "cleanrooms": {task: spec["image"] for task, spec in TASKS.items()},
        }

    def _label(self, task, outcome):
        return {
            "task": task,
            "evaluator_epoch": packaging.epoch(self.evaluator()),
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

    def validate_cached(self, result):
        """Accept only the unchanged, canonically labelled subject; never start a process."""
        validate_identity(self.terms)
        if result.get("validity") != "valid":
            return
        task = result.get("task")
        if not isinstance(task, str) or task not in TASKS:
            raise RuntimeError("cached task is outside the canonical registry")
        run_dir = Path(result["run_dir"])
        outcome = json.loads((run_dir / "eval" / "canonical-result.json").read_text())
        attempt = outcome.get("attempts")
        if type(attempt) is not int or attempt not in (1, 2):
            raise RuntimeError("cached canonical attempt is invalid")
        directory = run_dir / "eval" / f"attempt-{attempt}" / task
        archive = run_dir / "submission.tar.gz"
        bound = validate_receipt(task, archive, directory)
        if bound["exit_code"] != 0:
            raise RuntimeError(
                "cached canonical evaluator did not complete successfully"
            )
        score = json.loads((directory / "canonical-score.json").read_text())
        raw = directory / f"{task}.eval.json"
        expected = {
            **score,
            "attempts": attempt,
            "submission_sha256": sha256(archive),
            "feedback_json": str(directory / "canonical-feedback.json"),
        }
        if (
            outcome != expected
            or score.get("valid") is not True
            or score.get("reasons") != []
            or score.get("task") != task
            or score.get("total") != TASKS[task]["total"]
            or score.get("eval_json") != str(raw.resolve())
            or score.get("eval_sha256") != sha256(raw)
            or score.get("pins_sha256") != sha256(PINS_FILE)
        ):
            raise RuntimeError("cached canonical result differs from its bound score")
        resolved, total = score.get("resolved"), score.get("total")
        if (
            type(resolved) is not int
            or type(total) is not int
            or not 0 <= resolved <= total
            or type(result.get("pass_rate")) not in (int, float)
            or score.get("pass_rate") != resolved / total
            or result["pass_rate"] != score["pass_rate"]
            or result.get("label") != self._label(task, outcome)
        ):
            raise RuntimeError("cached canonical scalar or evaluator epoch differs")
        if sha256(run_dir / "canonical-feedback.json") != sha256(
            directory / "canonical-feedback.json"
        ):
            raise RuntimeError(
                "cached learning feedback differs from the bound evaluation"
            )

    def run_and_label(self, host, bundle, task, run_dir):
        validate_identity(self.terms)
        if task not in TASKS:
            raise RuntimeError(f"Task outside frozen canonical registry: {task}")
        subprocess.run(
            worker_command("preflight"),
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
        archive = package_submission(run_dir)
        outcome = evaluate_archive(task, archive, run_dir / "eval")
        shutil.copyfile(outcome["feedback_json"], run_dir / "canonical-feedback.json")
        rsi.compact(run_dir)
        failures = []
        for name, record in self.outcomes(run_dir).items():
            if not record["passed"] and len(failures) < 40:
                failures.append(
                    f"{name.rsplit('.', 1)[-1]}: {record['message'].splitlines()[0][:200] if record['message'] else 'nonpassed'}"
                )
        return {
            "validity": "valid",
            "pass_rate": outcome["pass_rate"],
            "status": summary.get("status"),
            "cost": summary.get("cost"),
            "failures": "\n".join(failures),
            "label": self._label(task, outcome),
        }

    def outcomes(self, run_dir):
        return json.loads((Path(run_dir) / "canonical-feedback.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["freeze", "preflight", "score", "evaluate-one", "evaluate", "null"],
    )
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--pins-sha256")
    parser.add_argument("--task")
    parser.add_argument("--eval-json", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configure(args.registry, args.registry_sha256)
    if args.command != "freeze":
        if args.pins_sha256 is None:
            parser.error("this command requires --pins-sha256")
        bind_pins(args.pins_sha256)
    if args.task is not None and args.task not in TASKS:
        parser.error("task is outside the frozen registry")
    if (
        args.command in ("score", "evaluate-one", "evaluate", "null")
        and args.task is None
    ):
        parser.error("this command requires --task")
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
        result = evaluate_claimed(args.task, args.archive, args.eval_json)
    elif args.command == "evaluate":
        result = evaluate_archive(args.task, args.archive, args.output)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        archive = packaging.null_package(args.output / "submission.tar.gz")
        result = evaluate_archive(args.task, archive, args.output / "eval")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
