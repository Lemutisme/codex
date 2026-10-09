"""Bounded host receipts, not explanations or evidence that a harness helped.

Only future observations use this projection. Missing fields are unobservable, never
zero/false. Explicit delivery attempt=null means the host recorded no action attempt.
The caller owns the trusted run directory; no provenance paths are followed.
"""

import json
import math
import os
import re
import stat
from pathlib import Path

MAX_SOURCE_BYTES = 256 << 10
MAX_PROJECTION_BYTES = 2048
MAX_NUMBER = (1 << 53) - 1


def _unknown(reason):
    return {"status": "unobservable", "reason": reason}


def _number(value):
    return (
        type(value) in (int, float)
        and 0 <= value <= MAX_NUMBER
        and math.isfinite(value)
    )


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_NUMBER


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON number")


def _section(raw, fields):
    if raw is None:
        return _unknown("missing")
    if not isinstance(raw, dict) or any(
        key not in raw or not valid(raw[key]) for key, valid in fields.items()
    ):
        return _unknown("malformed")
    return {"status": "observed", **{key: raw[key] for key in fields}}


def _harness(raw):
    facts = ("deadline_secs", "remaining_secs", "turns_completed", "repairs_used")
    section = _section(
        raw,
        {
            "sha256": lambda v: isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v),
            "interpreter": lambda v: v == "convergence-v1",
            "evaluations": _integer,
            "last_input": lambda v: (
                v is None
                or (
                    isinstance(v, dict)
                    and all(k in v and _integer(v[k]) for k in facts)
                )
            ),
            "last_decision": lambda v: v is None or type(v) is bool,
        },
    )
    if section.get("last_input") is not None:
        section["last_input"] = {key: section["last_input"][key] for key in facts}
    return section


def _delivery(raw):
    section = _section(
        raw,
        {
            "reserve_secs": _integer,
            "attempt": lambda v: v is None or isinstance(v, dict),
        },
    )
    if section.get("attempt") is not None:
        section["attempt"] = _section(
            section["attempt"],
            {
                "remaining_secs": _number,
                "outcome": lambda v: (
                    v in ("unacknowledged", "timeout", "error", "accepted")
                ),
            },
        )
    return section


def read(run_dir: Path) -> dict:
    """Return a fixed-schema projection; unsafe, oversized or legacy files stay unknown."""
    path = run_dir / "run.json"
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return _unknown("unsafe_file")
        if before.st_size > MAX_SOURCE_BYTES:
            return _unknown("oversize")
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as source:
            opened = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                return _unknown("unsafe_file")
            data = source.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            return _unknown("oversize")
        raw = json.loads(
            data, object_pairs_hook=_object, parse_constant=_invalid_constant
        )
    except FileNotFoundError:
        return _unknown("missing")
    except OSError:
        return _unknown("unreadable")
    except (ValueError, RecursionError):
        return _unknown("malformed")
    fields = {
        "deadline_secs": _integer,
        "elapsed_secs": _number,
        "deadline_hit": lambda v: type(v) is bool,
        "turns_completed": _integer,
        "server_exited_early": lambda v: type(v) is bool,
    }
    if not isinstance(raw, dict):
        return _unknown("malformed")
    if not any(key in raw for key in fields):
        return _unknown("legacy")
    if any(key in raw and not valid(raw[key]) for key, valid in fields.items()):
        return _unknown("malformed")
    projection = {
        "status": "observed",
        "kind": "host_runtime_facts_v1",
        "null_means": "unobservable (except delivery attempt: explicitly no attempt)",
        **{key: raw.get(key) for key in fields},
        "harness_program": _harness(raw.get("harness_program")),
        "delivery_budget": _delivery(raw.get("delivery_budget")),
        "execution_environment": _section(
            raw.get("execution_environment"),
            {
                "disconnect_observed": lambda v: type(v) is bool,
                "disconnect_count": _integer,
                "events_omitted": _integer,
            },
        ),
    }
    return (
        projection
        if len(json.dumps(projection)) <= MAX_PROJECTION_BYTES
        else _unknown("oversize")
    )
