"""Bounded fileChange observations, not proof of filesystem effects or an OS audit.

Patch previews may precede execution or never execute. Failed/declined patch phases
are not proof that no side effects occurred. Preserve every observed phase/path,
including rename source and target; the caller binds omitted diff bodies by raw log hash.
"""

import json

MAX_BYTES = 1 << 20
MAX_PHASES = 4096
MAX_CHANGES = 1024


def _require(condition, message):
    if not condition:
        raise ValueError(f"native mutation evidence: {message}")


def _text(value, cap):
    _require(
        isinstance(value, str) and 0 < len(value.encode()) <= cap and "\0" not in value,
        "missing or oversized identity/path",
    )


def _json(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _changes(rows, *, fields):
    _require(
        isinstance(rows, list) and len(rows) <= MAX_CHANGES, "invalid changes inventory"
    )
    result, paths, size = [], set(), 2
    for row in rows:
        _require(isinstance(row, dict) and set(row) == fields, "invalid change fields")
        _text(row["path"], 4096)
        _require(row["path"] not in paths, "duplicate change path")
        paths.add(row["path"])
        if "diff" in fields:
            _require(
                isinstance(row["diff"], str) and len(row["diff"].encode()) <= 1 << 20,
                "invalid raw diff",
            )
        kind = row["kind"]
        _require(isinstance(kind, dict), "missing change kind")
        if kind.get("type") == "update":
            _require(set(kind) == {"type", "move_path"}, "invalid update/rename kind")
            if kind["move_path"] is not None:
                _text(kind["move_path"], 4096)
        else:
            _require(
                set(kind) == {"type"} and kind["type"] in ("add", "delete"),
                "unknown change kind",
            )
        projected = dict(path=row["path"], kind=dict(kind))
        size += len(_json(projected)) + bool(result)
        _require(size <= MAX_BYTES, "changes exceed byte bound")
        result.append(projected)
    return result


class Capture:
    """Accumulate observed root phases; do not flatten changing previews into final paths."""

    def __init__(self):
        self.rows, self.states, self.size = [], {}, 2

    def observe(self, *, turn_id, item_id, phase, status, changes):
        self.append(
            dict(
                turn_id=turn_id,
                item_id=item_id,
                phase=phase,
                status=status,
                changes=_changes(changes, fields={"path", "kind", "diff"}),
            )
        )

    def append(self, row):
        _require(
            isinstance(row, dict)
            and set(row) == {"turn_id", "item_id", "phase", "status", "changes"},
            "invalid mutation observation",
        )
        _text(row["turn_id"], 128)
        _text(row["item_id"], 256)
        changes = _changes(row["changes"], fields={"path", "kind"})
        key, phase = (row["turn_id"], row["item_id"]), row["phase"]
        previous = self.states.get(key)
        if phase == "patch_updated":
            _require(
                row["status"] is None and previous != "completed",
                "invalid/late patch preview",
            )
            state = previous or "preview"
        elif phase == "started":
            _require(
                row["status"] == "inProgress" and previous in (None, "preview"),
                "duplicate/invalid mutation start",
            )
            state = "started"
        else:
            _require(
                phase == "completed"
                and row["status"] in ("completed", "failed", "declined")
                and previous == "started",
                "orphan/duplicate mutation completion",
            )
            state = "completed"
        projected = {**row, "changes": changes}
        size = self.size + len(_json(projected)) + bool(self.rows)
        _require(
            len(self.rows) < MAX_PHASES and size <= MAX_BYTES,
            "mutation projection exceeds bound",
        )
        self.rows.append(projected)
        self.states[key], self.size = state, size

    def finish(self):
        # A preview without a start is legitimate (parsing/verification may fail).
        # Its null status never asserts application or absence of filesystem effects.
        _require("started" not in self.states.values(), "mutation lifecycle incomplete")
        return self.rows


def encode(rows):
    """Revalidate independent auditor-pack input, including its ordered lifecycle."""
    _require(
        isinstance(rows, list) and len(rows) <= MAX_PHASES, "invalid mutation inventory"
    )
    capture = Capture()
    for row in rows:
        capture.append(row)
    return _json(capture.finish())
