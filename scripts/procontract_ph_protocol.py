"""Shared immutable P/H episode terms and bounded receipts; no campaign execution."""

import hashlib
import json
import os
from pathlib import Path

PROTOCOL = "single_candidate_ph_v1"
PH = {"executor.md", "drafter.md", "prober.md", "reviewer.md", "harness.json"}
MAX_BYTES = 512 << 10
SUPERVISOR = Path(__file__).with_name("procontract_ph_supervisor.py").resolve()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def raw(path, limit=MAX_BYTES):
    require(
        not path.is_symlink() and path.is_file() and path.stat().st_size <= limit,
        f"unsafe or missing receipt: {path}",
    )
    with path.open("rb") as source:
        value = source.read(limit + 1)
    require(len(value) <= limit, "receipt exceeds bound")
    return value


def digest(path):
    return hashlib.sha256(raw(path)).hexdigest()


def document(path, limit=MAX_BYTES):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate receipt key")
            result[key] = value
        return result

    return json.loads(raw(path, limit), object_pairs_hook=object_pairs)


def publish(path, value):
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
    require(len(data) <= MAX_BYTES, "supervisor receipt exceeds bound")
    with path.open("xb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def plan_path(terms):
    value = terms.get("ph_supervisor")
    require(
        isinstance(value, dict) and set(value) == {"plan_path", "plan_sha256"},
        "missing P/H supervisor descriptor",
    )
    path = Path(value["plan_path"])
    require(
        path.is_absolute() and ".." not in path.parts and path.resolve() == path,
        "supervisor plan path is redirected",
    )
    require(digest(path) == value["plan_sha256"], "supervisor plan differs from pin")
    return path


def validate_plan(camp, terms):
    plan = document(plan_path(terms))
    require(
        plan
        == {
            "schema": 1,
            "protocol": PROTOCOL,
            "campaign": str(camp.resolve()),
            "source_sha256": digest(SUPERVISOR),
            "max_phases": 3,
        },
        "supervisor plan does not bind this episode/source",
    )
    expected = {
        "model": "gpt-5.6-luna",
        "effort": "max",
        "submission_policy": "rust-preinstalled-v1",
        "proposal_kind": "all",
        "adoption": "presumed",
        "task_deadline_secs": 18000,
        "analysis_deadline_secs": 3600,
        "research_deadline_secs": 3600,
        "confirmation_exposure_scope": "prospective_lineage",
    }
    stream, gates = terms["stream"], terms["gates"]
    require(
        all(terms.get(key) == value for key, value in expected.items())
        and set(terms["mutable"]) == PH
        and len(terms["mutable"]) == len(PH),
        "campaign differs from fixed P/H scope",
    )
    require(
        terms.get("checkpoint")
        and terms.get("canonical")
        and terms["budgets"]["task_attempts"] == 1
        and stream.get("mode") == "guarded"
        and stream.get("method_confirmation") == "defer"
        and stream["batch"] == stream["release_every"] == 1
        and len(stream["order"]) >= 4,
        "episode needs inherited state and guarded single-task phases with buffer",
    )
    require(
        len(terms["pools"]["confirm"]) == gates["confirm_tasks"] == 4
        and gates["confirm_min_wins"] == 3
        and gates["confirm_min_delta"] == 0.000001,
        "P/H confirmation gate differs",
    )
    return plan
