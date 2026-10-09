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

from procontract_delivery_budget import ELIGIBILITY_REASONS
from procontract_harness_program import MAX_INTEGER

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


def _counter(value):
    return _integer(value) and value <= MAX_INTEGER


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
    version_two = (
        isinstance(raw, dict) and raw.get("interpreter") == "bounded-steering-v2"
    )
    facts = ("deadline_secs", "remaining_secs", "turns_completed", "repairs_used")
    if version_two:
        facts += ("executor_command_completions_observed",)
    fields = {
        "sha256": lambda v: isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v),
        "interpreter": lambda v: v in ("convergence-v1", "bounded-steering-v2"),
        "evaluations": _integer,
        "last_input": lambda v: (
            v is None
            or (
                isinstance(v, dict)
                and all(k in v and _integer(v[k]) for k in facts)
                and (
                    not version_two
                    or (
                        v.keys() == set(facts)
                        and v["deadline_secs"] > 0
                        and all(value <= MAX_INTEGER for value in v.values())
                    )
                )
            )
        ),
        "last_decision": lambda v: v is None or type(v) is bool,
    }
    if version_two:
        fields.update(
            evaluations=_counter,
            action=lambda v: v in ("checkpoint", "converge"),
            last_eligibility=lambda v: (
                v is None
                or (
                    isinstance(v, dict)
                    and v.keys() == {"eligible", "reason"}
                    and type(v["eligible"]) is bool
                    and isinstance(v["reason"], str)
                    and v["reason"] in ELIGIBILITY_REASONS
                    and v["eligible"] == (v["reason"] == "eligible")
                )
            ),
        )
    section = _section(raw, fields)
    if section.get("last_input") is not None:
        section["last_input"] = {key: section["last_input"][key] for key in facts}
    return section


def _delivery(raw, *, version_two=False):
    section = _section(
        raw,
        {
            "reserve_secs": _integer,
            "attempt": lambda v: v is None or isinstance(v, dict),
        },
    )
    if section.get("attempt") is not None:
        fields = {
            "remaining_secs": _number,
            "outcome": lambda v: (
                v in ("unacknowledged", "timeout", "error", "accepted")
            ),
        }
        if version_two:
            fields["action"] = lambda v: v in ("checkpoint", "converge")
        section["attempt"] = _section(section["attempt"], fields)
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
    version_two = (
        isinstance(raw.get("harness_program"), dict)
        and raw["harness_program"].get("interpreter") == "bounded-steering-v2"
    )
    projection = {
        "status": "observed",
        "kind": "host_runtime_facts_v1",
        "null_means": "unobservable (except delivery attempt: explicitly no attempt)",
        **{key: raw.get(key) for key in fields},
        "harness_program": _harness(raw.get("harness_program")),
        "delivery_budget": _delivery(
            raw.get("delivery_budget"), version_two=version_two
        ),
        "execution_environment": _section(
            raw.get("execution_environment"),
            {
                "disconnect_observed": lambda v: type(v) is bool,
                "disconnect_count": _integer,
                "events_omitted": _integer,
            },
        ),
    }
    if version_two or "execution_activity" in raw:
        projection["execution_activity"] = _section(
            raw.get("execution_activity"),
            {"executor_command_completions_observed": _counter},
        )
    return (
        projection
        if len(json.dumps(projection)) <= MAX_PROJECTION_BYTES
        else _unknown("oversize")
    )
