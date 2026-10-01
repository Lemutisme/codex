"""Python access to a ProContract store through the `pro-contract-store` CLI, so that hashing,
capture and the experiment chain have exactly one implementation."""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BIN = REPO / "codex-rs" / "target" / "debug" / "pro-contract-store"


def store_bin() -> str:
    return os.environ.get("PRO_CONTRACT_STORE_BIN", str(DEFAULT_BIN))


def _run(args: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(
        [store_bin(), *args], input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pro-contract-store {args[0]} failed: {result.stderr.strip()}"
        )
    return result.stdout


def identities(
    harness: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    evaluator_epoch: str | None = None,
) -> dict:
    return {
        "harness": harness,
        "policies": {},
        "model": model,
        "effort": effort,
        "evaluator_epoch": evaluator_epoch,
    }


def capture(store: Path, root: Path, excluded: list[str]) -> dict:
    args = ["capture", "--store", str(store), "--root", str(root)]
    for path in excluded:
        args += ["--exclude", path]
    return json.loads(_run(args))


def materialize(store: Path, subject: str, dest: Path) -> None:
    _run(
        [
            "materialize",
            "--store",
            str(store),
            "--subject",
            subject,
            "--dest",
            str(dest),
        ]
    )


def append(store: Path, kind: str, identities: dict, body: dict) -> dict:
    event = {"kind": kind, "identities": identities, "body": body}
    return json.loads(_run(["append", "--store", str(store)], stdin=json.dumps(event)))


def events(store: Path) -> list[dict]:
    if not (store / "ledger_1.sqlite").exists():
        return []
    return json.loads(_run(["events", "--store", str(store)]))
