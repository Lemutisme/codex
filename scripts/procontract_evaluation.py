"""Evaluator pins, packaging and labelling of exact subjects (RSI spec §10, M0).

Labels attach to materialized subjects, never to live workspaces. Evaluation follows the frozen
M0 protocol: up to 2 re-evaluations for branch errors that the instance's null sentinel does
not explain, then `invalid`."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import procontract_store as store

ATTEMPTS = 3  # one evaluation plus up to 2 re-evaluations
SUBMISSION_EXCLUDED = ["./executable", "./target"]
HF_REF = "datasets--programbench--ProgramBench-Tests/refs/main"


class PinDrift(Exception):
    pass


def epoch(pins: dict) -> str:
    return hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()


def current_pins(programbench: Path, instance: str, hf_cache: Path, image_id) -> dict:
    head = subprocess.run(
        ["git", "-C", str(programbench), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    base = f"programbench/{instance.replace('__', '_1776_')}"
    return {
        "programbench_head": head,
        "uv_lock_sha256": hashlib.sha256(
            (programbench / "uv.lock").read_bytes()
        ).hexdigest(),
        "hf_revision": (hf_cache / HF_REF).read_text().strip(),
        "images": {
            "task_cleanroom": image_id(f"{base}:task_cleanroom"),
            "task": image_id(f"{base}:task"),
        },
    }


def check_pins(pinned: dict, current: dict) -> None:
    if pinned != current:
        changed = sorted(
            key
            for key in set(pinned) | set(current)
            if pinned.get(key) != current.get(key)
        )
        raise PinDrift(f"evaluator pins drifted: {changed}")


def package(workspace: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    excludes = [f"--exclude={path}" for path in SUBMISSION_EXCLUDED]
    subprocess.run(
        [
            "tar",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "--anchored",
            *excludes,
            "-czf",
            str(dest),
            "-C",
            str(workspace),
            ".",
        ],
        check=True,
    )


def null_package(dest: Path) -> Path:
    source = dest.parent / "null-src"
    source.mkdir(parents=True, exist_ok=True)
    (source / "compile.sh").write_text(
        "#!/bin/sh\nprintf '#!/bin/sh\\nexit 1\\n' > executable\nchmod +x executable\n"
    )
    package(source, dest)
    return dest


def parse_eval(eval_json: Path, log_text: str, instance: str) -> dict:
    data = json.loads(eval_json.read_text())
    statuses: dict[str, int] = {}
    for result in data.get("test_results") or []:
        statuses[result["status"]] = statuses.get(result["status"], 0) + 1
    match = re.search(rf"^\s*{re.escape(instance)}\s+(✅|\d+)", log_text, re.MULTILINE)
    score = match.group(1) if match else None
    errors = data.get("test_branch_errors") or {}
    return {
        "solved": score == "✅",
        "score": score,
        "resolved": statuses.get("passed", 0),
        "total": sum(statuses.values()),
        "statuses": statuses,
        "branch_errors": sorted(errors),
    }


def classify(outcome: dict | None, known_branch_errors: set[str]) -> str:
    if outcome is None or outcome["score"] is None:
        return "retry"
    return "retry" if set(outcome["branch_errors"]) - known_branch_errors else "valid"


def evaluate_package(
    package_path: Path,
    instance: str,
    work: Path,
    programbench_cmd: list[str],
    programbench: Path,
    hf_revision: str,
    known_branch_errors: set[str],
    attempts: int = ATTEMPTS,
) -> dict:
    outcome = None
    for attempt in range(1, attempts + 1):
        eval_dir = work / f"attempt-{attempt}"
        (eval_dir / instance).mkdir(parents=True, exist_ok=True)
        shutil.copy(package_path, eval_dir / instance / "submission.tar.gz")
        log = eval_dir / "eval.log"
        with log.open("w") as out:
            done = subprocess.run(
                [
                    *programbench_cmd,
                    "eval",
                    str(eval_dir),
                    "--filter",
                    f"^{re.escape(instance)}$",
                    "-w",
                    "1",
                    "-b",
                    "1",
                    "--docker-cpus",
                    "4",
                ],
                cwd=programbench,
                stdout=out,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PROGRAMBENCH_HF_REVISION": hf_revision},
                check=False,
            )
        eval_json = eval_dir / instance / f"{instance}.eval.json"
        outcome = (
            parse_eval(eval_json, log.read_text(), instance)
            if done.returncode == 0 and eval_json.exists()
            else None
        )
        if classify(outcome, known_branch_errors) == "valid":
            return {
                "outcome": outcome,
                "validity": "valid",
                "reason": "",
                "attempts": attempt,
            }
    reason = (
        "evaluator failed"
        if outcome is None
        else f"branch errors {outcome['branch_errors']}"
    )
    return {
        "outcome": outcome,
        "validity": "invalid",
        "reason": reason,
        "attempts": attempts,
    }


def label_key(run_id: str, subject: str, role: dict, evaluator_epoch: str) -> str:
    payload = json.dumps([run_id, subject, role, evaluator_epoch], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


CAPTURE_EXCLUDED = ["executable", "target", ".git"]


def label_run(
    run_dir: Path,
    batch_store: Path,
    run_id: str,
    instance: str,
    evaluator_epoch: str,
    programbench_cmd: list[str],
    programbench: Path,
    hf_revision: str,
    known_branch_errors: set[str],
    identities: dict,
) -> list[dict]:
    """Labels every judged subject and the final workspace of one run; returns the new labels."""
    run_store = run_dir / "codex-home" / "pro_contract"
    existing = {
        event["event"]["body"].get("label_key")
        for event in store.events(batch_store)
        if event["event"]["kind"] == "label"
    }
    targets: list[tuple[dict, str | None, str]] = []
    for event in store.events(run_store):
        body = event["event"]["body"]
        if event["event"]["kind"] == "verification":
            role = {
                "kind": "judged",
                "contract_id": body["contract_id"],
                "generation": body["generation"],
                "verdict": body["verdict"],
            }
            targets.append((role, body["subject_hash"], ""))
    try:
        final = store.capture(run_store, run_dir / "workspace", CAPTURE_EXCLUDED)[
            "subject_hash"
        ]
        store.append(
            batch_store,
            "capture",
            identities,
            {"run_id": run_id, "subject_hash": final, "purpose": "final_workspace"},
        )
        targets.append(({"kind": "final_workspace"}, final, ""))
    except RuntimeError as error:
        targets.append(({"kind": "final_workspace"}, None, f"capture failed: {error}"))
    results: dict[str, dict] = {}
    labels = []
    for role, subject, failure in targets:
        key = label_key(run_id, subject or "", role, evaluator_epoch)
        if key in existing:
            continue
        if subject is None:
            result = {
                "outcome": None,
                "validity": "invalid",
                "reason": failure,
                "attempts": 0,
            }
        elif subject not in results:
            source = run_dir / "labels" / subject / "source"
            try:
                shutil.rmtree(source, ignore_errors=True)
                store.materialize(run_store, subject, source)
                archive = run_dir / "labels" / subject / "submission.tar.gz"
                package(source, archive)
                results[subject] = evaluate_package(
                    archive,
                    instance,
                    run_dir / "labels" / subject / "eval",
                    programbench_cmd,
                    programbench,
                    hf_revision,
                    known_branch_errors,
                )
            except RuntimeError as error:
                results[subject] = {
                    "outcome": None,
                    "validity": "invalid",
                    "reason": str(error),
                    "attempts": 0,
                }
            result = results[subject]
        else:
            result = results[subject]
        body = {
            "label_key": key,
            "run_id": run_id,
            "instance": instance,
            "subject_hash": subject,
            "role": role,
            **result,
        }
        store.append(
            batch_store,
            "label",
            {**identities, "evaluator_epoch": evaluator_epoch},
            body,
        )
        labels.append(body)
    return labels
