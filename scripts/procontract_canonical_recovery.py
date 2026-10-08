"""Durable evaluator launch allowances and atomically published canonical artifacts."""

import json
import os
import uuid
from pathlib import Path

CLAIM = "evaluation-claim.json"
TERMINAL = "evaluation-receipt.json"


def _sync_directory(directory):
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_artifact(path, produce):
    """A failed producer never leaves a final pathname that looks complete."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    try:
        produce(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"incomplete canonical recovery record: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid canonical recovery record: {path}")
    return value


def claimed(directory, binding=None):
    claim = _read(directory / CLAIM)
    if (
        set(claim) != {"schema", "id", "binding"}
        or claim["schema"] != 1
        or not isinstance(claim["id"], str)
        or len(claim["id"]) != 32
        or not isinstance(claim["binding"], dict)
        or (binding is not None and claim["binding"] != binding)
    ):
        raise RuntimeError("canonical evaluator launch claim identity changed")
    return claim


def start(directory, binding):
    """Consume a launch before I/O; an existing unknown launch never authorizes another."""
    if (directory / CLAIM).exists():
        return claimed(directory, binding), False
    # A directory with old evaluator output but no claim is not an unused allowance.
    if any(path.name != "submission.tar.gz" for path in directory.iterdir()):
        raise RuntimeError(
            "unclaimed canonical evaluator artifacts require reconciliation"
        )
    claim = {"schema": 1, "id": uuid.uuid4().hex, "binding": binding}
    try:
        with (directory / CLAIM).open("x") as handle:
            handle.write(json.dumps(claim, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(directory)
    except FileExistsError:
        return claimed(directory, binding), False
    return claim, True


def terminal(directory, binding):
    claim = claimed(directory, binding)
    if not (directory / TERMINAL).exists():
        raise RuntimeError(
            "canonical evaluator launch is unresolved; preserve it and do not repurchase"
        )
    receipt = _read(directory / TERMINAL)
    if (
        receipt.get("schema") != 1
        or receipt.get("claim_id") != claim["id"]
        or any(receipt.get(key) != value for key, value in binding.items())
        or type(receipt.get("exit_code")) is not int
    ):
        raise RuntimeError(
            "canonical evaluator terminal evidence does not bind its launch"
        )
    return receipt


def enter_worker(directory, claim):
    """Even a directly repeated worker command cannot spend the same launch twice."""
    if claimed(directory, claim["binding"]) != claim:
        raise RuntimeError("canonical worker claim changed")
    try:
        with (directory / "evaluation-worker-started.json").open("x") as handle:
            handle.write(json.dumps({"claim_id": claim["id"]}))
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(directory)
    except FileExistsError as error:
        raise RuntimeError(
            "canonical evaluator worker already entered this launch"
        ) from error


def finish(directory, claim, fields):
    """Called by the worker on completion, or by a parent that observed process exit."""
    if (
        claimed(directory, claim["binding"]) != claim
        or fields.keys() & claim["binding"].keys()
    ):
        raise RuntimeError("canonical completion does not belong to this launch")
    receipt = {"schema": 1, "claim_id": claim["id"], **claim["binding"], **fields}
    path = directory / TERMINAL
    if path.exists():
        if _read(path) != receipt:
            raise RuntimeError(
                "conflicting canonical terminal evidence; preserve the first receipt"
            )
        return
    atomic_artifact(
        path,
        lambda target: target.write_text(json.dumps(receipt, sort_keys=True) + "\n"),
    )
