"""Bind benchmark admission and accounting to the native successor grant; no inference."""

import contextlib
import hashlib
import json
import sqlite3


def grant(sessions, seconds, arm):
    if type(sessions) is not int or not 0 <= sessions <= 16:
        raise ValueError("invalid successor session cap")
    if not sessions:
        return None
    if arm != "on" or type(seconds) is not int or not 60 <= seconds <= 14400:
        raise ValueError("succession requires ON and a finite native-task deadline")
    return {"max_sessions": sessions, "total_secs": seconds}


def validate(run, manifest):
    path = run / "codex-home/pro_contract/settings.json"
    actual = json.loads(path.read_text()).get("succession")
    if actual != manifest.get("succession"):
        raise ValueError("native successor grant differs from prepared manifest")
    if actual is not None:
        if manifest.get("arm") != "on" or hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != manifest.get("settings_sha256"):
            raise ValueError("native successor settings drifted")


def snapshot(home, thread, expected):
    if expected is None:
        return None
    database = home / "pro_contract/ledger_1.sqlite"
    if thread is None or not database.is_file():
        return {"configured": expected, "observed": False}
    with contextlib.closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    ) as db:
        row = db.execute(
            "SELECT json FROM records WHERE kind='succession' AND key=?", (thread,)
        ).fetchone()
        if row is None:
            return {"configured": expected, "observed": False}
        value = json.loads(row[0])
        commands = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT command_json FROM events WHERE contract_id=? ORDER BY seq",
                (thread + ".1",),
            )
        ]
    ids = value.get("executors")
    if (
        value.get("grant") != expected
        or type(value.get("launches")) is not int
        or not 0 <= value["launches"] <= expected["max_sessions"]
        or not isinstance(ids, list)
        or len(ids) != value["launches"]
        or any(not isinstance(i, str) or not i for i in ids)
        or len(set(ids)) != len(ids)
        or value["deadline_ms"] - value["started_ms"] != expected["total_secs"] * 1000
        or value.get("pending") not in [None, *ids]
    ):
        raise ValueError(
            "native successor accounting does not match the original grant"
        )
    return {
        "configured": expected,
        "observed": True,
        "launches": value["launches"],
        "executors": ids,
        "pending": value["pending"],
        "started_ms": value["started_ms"],
        "deadline_ms": value["deadline_ms"],
        "issue_count": sum(c["command"]["type"] == "issue" for c in commands),
        "accepted_commands": [c["command"]["type"] for c in commands],
        "budget_sha256": hashlib.sha256(row[0].encode()).hexdigest(),
    }
