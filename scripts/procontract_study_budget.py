"""Operator-pinned, durable runner-launch allowances; not HTTP, token or dollar metering.

A committed reservation consumes its entire deadline, including failed and unknown launches.
Only its first creator receives authorization. Reopening or changing a caller's directory never
refunds it; callers must keep the database path and study identity outside candidate authority.
"""

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path

MAX_INTEGER = (1 << 63) - 1
MAX_JSON_BYTES = 64 << 10
KINDS = {"task": "task_launches", "learning": "learning_launches"}
LIMIT_KEYS = ("task_launches", "learning_launches", "allocated_seconds")
SHA256 = re.compile(r"[0-9a-f]{64}")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS plan (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
    "study_sha256 TEXT NOT NULL, limits_json TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reservations (key TEXT PRIMARY KEY NOT NULL, "
    "kind TEXT NOT NULL, deadline_secs INTEGER NOT NULL, identity_json TEXT NOT NULL, "
    "receipt_id TEXT UNIQUE NOT NULL, binding_sha256 TEXT NOT NULL)",
)


class BudgetError(RuntimeError):
    """A budget decision failed closed before authorizing a runner."""


class AlreadyClaimed(BudgetError):
    """This key is already spent or unknown; it never authorizes another launch."""


class BudgetExceeded(BudgetError):
    """A new reservation would exceed the pinned study allowance."""


class PlanMismatch(BudgetError):
    """An existing database belongs to another study or another allowance."""


class CorruptBudget(BudgetError):
    """Persistent accounting cannot be trusted; never infer a zero balance."""


def _json(value):
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("budget identities must be finite JSON") from error
    if len(encoded) > MAX_JSON_BYTES:
        raise ValueError("budget identity exceeds its byte bound")
    return encoded


def _positive(value):
    return type(value) is int and 0 < value <= MAX_INTEGER


def _plan(study, limits):
    if not isinstance(study, str) or SHA256.fullmatch(study) is None:
        raise ValueError("study SHA-256 must be a lowercase hexadecimal digest")
    if (
        type(limits) is not dict
        or limits.keys() != set(LIMIT_KEYS)
        or not all(_positive(value) for value in limits.values())
    ):
        raise ValueError(
            "budget limits must contain exactly three bounded positive integers"
        )


def _binding(study, key, kind, deadline, limits, identity):
    if not isinstance(key, str) or not key or len(key) > 4096 or "\0" in key:
        raise ValueError("a bounded, nonempty reservation key is required")
    if not isinstance(kind, str) or kind not in KINDS or not _positive(deadline):
        raise ValueError("reservation kind or deadline is invalid")
    if type(identity) is not dict:
        raise ValueError("reservation identity must be a JSON object")
    identity_json = _json(identity)
    bound = _json(
        {
            "study_sha256": study,
            "key": key,
            "kind": kind,
            "deadline_secs": deadline,
            "limits": limits,
            "identity": identity,
        }
    )
    return identity_json, hashlib.sha256(bound.encode()).hexdigest()


def _state(connection, study, limits):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise CorruptBudget("budget schema is missing or unsupported")
    plan = connection.execute("SELECT study_sha256, limits_json FROM plan").fetchall()
    if len(plan) != 1:
        raise CorruptBudget("budget must have exactly one persistent plan")
    try:
        stored_limits = json.loads(plan[0][1])
        _plan(plan[0][0], stored_limits)
    except (TypeError, ValueError, RecursionError) as error:
        raise CorruptBudget("persistent budget plan is malformed") from error
    if plan[0][0] != study or stored_limits != limits:
        raise PlanMismatch(
            "study identity or limits differ from the authoritative plan"
        )
    used = dict.fromkeys(LIMIT_KEYS, 0)
    bindings = {}
    for key, kind, deadline, encoded, receipt_id, binding in connection.execute(
        "SELECT key, kind, deadline_secs, identity_json, receipt_id, binding_sha256 FROM reservations"
    ):
        try:
            identity = json.loads(encoded)
            _, expected = _binding(study, key, kind, deadline, limits, identity)
            if (
                binding != expected
                or not isinstance(receipt_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", receipt_id) is None
                or key in bindings
            ):
                raise ValueError("reservation binding differs")
        except (TypeError, ValueError, RecursionError) as error:
            raise CorruptBudget(
                "persistent reservation is malformed or rebound"
            ) from error
        bindings[key] = binding
        used[KINDS[kind]] += 1
        used["allocated_seconds"] += deadline
    if any(used[name] > limits[name] for name in LIMIT_KEYS):
        raise CorruptBudget("persistent reservations exceed the authoritative limits")
    return used, bindings


def _path(database):
    database = Path(database)
    if database.is_symlink() or database.exists() and not database.is_file():
        raise CorruptBudget("budget database must be a regular, non-linked file")
    return database


def initialize(database: Path, study_sha256: str, limits: dict) -> None:
    """Seal a NEW operator-owned database; never reset an existing or partial study."""
    _plan(study_sha256, limits)
    database = _path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with database.open("xb"):
            pass
    except FileExistsError as error:
        raise PlanMismatch(
            "budget database already exists; initialization cannot reset it"
        ) from error
    connection = None
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=rw",
            uri=True,
            timeout=30,
            isolation_level=None,
        )
        connection.execute("PRAGMA synchronous = EXTRA")
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO plan VALUES (1, ?, ?)", (study_sha256, _json(limits))
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except sqlite3.Error as error:
        # Preserve partial initialization: a missing plan never authorizes a fresh budget.
        raise CorruptBudget(f"budget initialization failed: {error}") from error
    finally:
        if connection is not None:
            connection.close()


def reserve(
    database: Path,
    study_sha256: str,
    key: str,
    kind: str,
    deadline_secs: int,
    limits: dict,
    identity: dict,
) -> dict:
    """Reserve one full runner deadline, returning authorization only on its first commit."""
    _plan(study_sha256, limits)
    encoded, binding = _binding(
        study_sha256, key, kind, deadline_secs, limits, identity
    )
    database = _path(database)
    connection = None
    try:
        connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=rw",
            uri=True,
            timeout=30,
            isolation_level=None,
        )
        connection.execute("PRAGMA synchronous = EXTRA")
        connection.execute("BEGIN IMMEDIATE")
        used, bindings = _state(connection, study_sha256, limits)
        if key in bindings:
            detail = (
                "same identity" if bindings[key] == binding else "different identity"
            )
            raise AlreadyClaimed(
                f"reservation already claimed ({detail}); no new authorization"
            )
        if (
            used[KINDS[kind]] >= limits[KINDS[kind]]
            or deadline_secs > limits["allocated_seconds"] - used["allocated_seconds"]
        ):
            raise BudgetExceeded(
                "study runner-launch or allocated-seconds budget is exhausted"
            )
        receipt_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO reservations VALUES (?, ?, ?, ?, ?, ?)",
            (key, kind, deadline_secs, encoded, receipt_id, binding),
        )
        connection.commit()
        return {
            "id": receipt_id,
            "key": key,
            "study_sha256": study_sha256,
            "kind": kind,
            "deadline_secs": deadline_secs,
            "binding_sha256": binding,
        }
    except sqlite3.Error as error:
        raise CorruptBudget(
            f"budget database is unavailable or malformed: {error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def status(database: Path, expectedStudy: str, limits: dict) -> dict:
    """Read a pinned balance without creating, repairing or refunding persistent state."""
    _plan(expectedStudy, limits)
    database = _path(database)
    connection = None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.execute("BEGIN")
        used, _ = _state(connection, expectedStudy, limits)
        return {
            "study_sha256": expectedStudy,
            "limits": dict(limits),
            "reserved": used,
            "remaining": {name: limits[name] - used[name] for name in LIMIT_KEYS},
        }
    except sqlite3.Error as error:
        raise CorruptBudget(
            f"budget database is unavailable or malformed: {error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()
