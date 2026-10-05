#!/usr/bin/env python3
"""The executor's trajectory, normalized from a codex rollout.

A verdict (the hidden outcome) says whether a run passed; the trajectory says why. This module reads
the executor's rollout into ordered events (turn boundaries, tool calls with the head and tail of
their output, agent messages, ProContract notes, compaction summaries), counts them, and renders them
as a readable trajectory.md beside an events.jsonl of the same records. It also copies the final
workspace's text files. Reasoning is encrypted in the rollouts, so intent can only be read from
actions, messages and the summaries the agent wrote for itself at compaction.

Everything is task-agnostic and pure apart from reading and writing files: a task family supplies
only its oracle patterns (how a call reaches the reference program)."""

import codecs
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import procontract_attribution as attribution

CALL_TYPES = attribution.CALL_TYPES
COMMAND_CAP = 8 << 10
OUTPUT_CAP = 4 << 10
USER_CAP = 4000
NOTE_MARKER = '<codex_internal_context source="pro_contract">'
CLIP_MARKER = "bytes omitted"
BOILERPLATE = ("<environment_context>", "<skills_instructions>", "<user_instructions>")
RESULT_HEADER = re.compile(r"^Script completed\nWall time [0-9.]+ seconds\nOutput:\n")
SKIP_DIRS = {".git", "target", "node_modules"}

RENDER_CALL = 700
RENDER_OUTPUT = 500
RENDER_MESSAGE = 2000
RENDER_FINAL = 3000

LEGEND = """Legend: each line starts with the elapsed time and the cumulative tokens; calls carry their \
index. Reasoning is encrypted in the rollouts, so intent is read from actions and messages, and the \
compaction summaries are the agent's own account of its beliefs. Calls and outputs are excerpts \
(head and tail); ProContract notes and compaction summaries are in full. events.jsonl holds the \
fuller records."""


def clip(text: str, limit: int) -> str:
    """At most `limit` characters: the head and the tail with an omission marker between them."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n…[{len(text) - 2 * half} chars omitted]…\n{text[-half:]}"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text") or "" for part in content or [] if isinstance(part, dict)
    )


def command_of(code: str) -> str:
    """The shell command inside an exec script, when it is a single exec_command call."""
    match = re.search(r'"?\bcmd"?\s*:\s*("(?:[^"\\]|\\.)*")', code)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return code


def executor_rollout(run_dir: Path, thread_id: str | None = None) -> Path | None:
    """The executor's rollout: the file named for its thread when that is given and found, else
    the largest, since the workers' rollouts beside it are small."""
    paths = sorted((Path(run_dir) / "codex-home" / "sessions").rglob("rollout-*.jsonl"))
    named = [path for path in paths if thread_id and thread_id in path.name]
    pool = named or paths
    return max(pool, key=lambda path: path.stat().st_size) if pool else None


def seconds_between(start: str, stamp: str) -> float:
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return round((b - a).total_seconds(), 3)
    except (ValueError, AttributeError):
        return 0.0


def read(rollout: Path, oracle_patterns: list[str]) -> list[dict]:
    """Ordered events of a rollout. Every event has `kind`, `turn` (1-based), `t` (seconds since
    the first record) and `tokens` (cumulative total tokens). Kinds: turn_start, turn_end (`text`
    is the final message), user (the task prompt, bounded), call (`index`, `command`, `oracle`,
    `output`), message (`text`), note (`text`, `bytes`, `clipped`), compaction (`text`)."""
    oracle = [re.compile(pattern) for pattern in oracle_patterns]
    events: list[dict] = []
    calls: dict[str, dict] = {}
    start = None
    tokens = 0
    turn = 0
    ncalls = 0
    with Path(rollout).open(errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            stamp = record.get("timestamp") or ""
            start = start or stamp
            kind, ptype = record.get("type"), payload.get("type")

            def add(event_kind: str, **fields) -> dict:
                event = {
                    "kind": event_kind,
                    "turn": max(turn, 1),
                    "t": seconds_between(start, stamp),
                    "tokens": tokens,
                    **fields,
                }
                events.append(event)
                return event

            if kind == "event_msg" and ptype == "token_count":
                usage = (payload.get("info") or {}).get("total_token_usage") or {}
                tokens = usage.get("total_tokens", tokens)
            elif kind == "event_msg" and ptype == "task_started":
                turn += 1
                add("turn_start")
            elif kind == "event_msg" and ptype == "task_complete":
                add("turn_end", text=payload.get("last_agent_message") or "")
            elif kind == "compacted":
                add("compaction", text=payload.get("message") or "")
            elif kind == "response_item" and ptype == "message":
                role, text = payload.get("role"), text_of(payload.get("content"))
                if role == "assistant":
                    add("message", text=text)
                elif role == "user" and NOTE_MARKER in text:
                    add(
                        "note",
                        text=text,
                        bytes=len(text.encode()),
                        clipped=CLIP_MARKER in text,
                    )
                elif role == "user" and not text.startswith(BOILERPLATE):
                    add("user", text=clip(text, USER_CAP))
            elif kind == "response_item" and ptype in CALL_TYPES:
                ncalls += 1
                text = attribution.call_text(payload)
                event = add(
                    "call",
                    index=ncalls,
                    command=clip(text, COMMAND_CAP),
                    output="",
                    oracle=attribution.reaches_oracle(text, oracle),
                )
                calls[payload.get("call_id")] = event
            elif kind == "response_item" and ptype in (
                "function_call_output",
                "custom_tool_call_output",
            ):
                event = calls.get(payload.get("call_id"))
                if event:
                    out = RESULT_HEADER.sub("", text_of(payload.get("output")))
                    event["output"] = clip(out, OUTPUT_CAP)
    return events


def stats(events: list[dict]) -> dict:
    """Counts over events; a turn's tokens are those spent between its start and its last event."""
    turns = []
    for n in range(1, max((e["turn"] for e in events), default=0) + 1):
        mine = [e for e in events if e["turn"] == n]
        began = next((e["tokens"] for e in mine if e["kind"] == "turn_start"), 0)
        calls = [e for e in mine if e["kind"] == "call"]
        turns.append(
            {
                "calls": len(calls),
                "oracle_calls": sum(e["oracle"] for e in calls),
                "tokens": max((e["tokens"] for e in mine), default=began) - began,
            }
        )
    calls = [e for e in events if e["kind"] == "call"]
    return {
        "calls": len(calls),
        "oracle_calls": sum(e["oracle"] for e in calls),
        "tokens": max((e["tokens"] for e in events), default=0),
        "wall_secs": max((e["t"] for e in events), default=0),
        "compactions": sum(e["kind"] == "compaction" for e in events),
        "turns": turns,
        "notes": [
            {"turn": e["turn"], "bytes": e["bytes"], "clipped": e["clipped"]}
            for e in events
            if e["kind"] == "note"
        ],
    }


def elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render(events: list[dict], header: str = "") -> str:
    """trajectory.md: the events in order with bounded excerpts."""
    out = [header.rstrip(), LEGEND] if header.strip() else [LEGEND]
    for e in events:
        at = f"[{elapsed(e['t'])}]"
        tok = f"tok={e['tokens']:,}"
        kind = e["kind"]
        if kind == "turn_start":
            out.append(f"\n## {at} TURN {e['turn']} START ({tok})\n")
        elif kind == "turn_end":
            out.append(
                f"\n## {at} TURN {e['turn']} END ({tok}); final message:\n"
                f"{clip(e['text'], RENDER_FINAL)}\n"
            )
        elif kind == "user":
            out.append(f"\n## {at} USER:\n{e['text']}\n")
        elif kind == "note":
            flag = " (clipped)" if e["clipped"] else ""
            out.append(
                f"\n## {at} PROCONTRACT NOTE, {e['bytes']} bytes{flag}:\n{e['text']}\n"
            )
        elif kind == "compaction":
            out.append(
                f"\n## {at} COMPACTION ({tok}), the agent's own summary:\n{e['text']}\n"
            )
        elif kind == "message":
            out.append(f"\n{at} {tok} AGENT SAYS: {clip(e['text'], RENDER_MESSAGE)}\n")
        elif kind == "call":
            mark = " [oracle]" if e["oracle"] else ""
            out.append(
                f"\n{at} #{e['index']} {tok}{mark} CALL: "
                f"{clip(command_of(e['command']), RENDER_CALL)}"
            )
            out.append(
                f"  -> {at} #{e['index']} {tok} OUT: {clip(e['output'], RENDER_OUTPUT)}"
            )
    return "\n".join(out) + "\n"


def write(
    run_dir: Path,
    dest: Path,
    oracle_patterns: list[str],
    thread_id: str | None = None,
) -> dict | None:
    """Write dest/trajectory.md and dest/events.jsonl for a run; its stats, or None without a
    rollout."""
    rollout = executor_rollout(run_dir, thread_id)
    if rollout is None:
        return None
    events = read(rollout, oracle_patterns)
    dest.mkdir(parents=True, exist_ok=True)
    header = f"# Trajectory of {Path(run_dir).name}\nexecutor rollout: {rollout.name}\n"
    (dest / "trajectory.md").write_text(render(events, header))
    (dest / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )
    return stats(events)


def utf8_text(path: Path, cap: int) -> tuple[bool, bool]:
    """(is UTF-8 text, is larger than `cap`), judged from at most cap+1 bytes."""
    with path.open("rb") as handle:
        data = handle.read(cap + 1)
    big = len(data) > cap
    try:
        codecs.getincrementaldecoder("utf-8")().decode(data[:cap], final=not big)
    except UnicodeDecodeError:
        return False, big
    return b"\0" not in data, big


def copy_final(
    workspace: Path,
    dest: Path,
    total_cap: int = 2 << 20,
    file_cap: int = 512 << 10,
) -> tuple[list[str], int]:
    """Copy the final workspace's UTF-8 text files into dest, keeping relative paths, in sorted
    order. Not candidates: .git, target and node_modules, symlinks, files named `executable`,
    files that are not UTF-8 text. Returns (copied relative paths, omitted), where omitted counts
    text files left out for size: over `file_cap`, or after `total_cap` would have been exceeded
    (nothing is added after that point)."""
    workspace = Path(workspace)
    found = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(root, name)
            if name != "executable" and not path.is_symlink():
                found.append(path)
    copied: list[str] = []
    omitted = 0
    total = 0
    full = False
    for path in sorted(found, key=lambda p: p.relative_to(workspace).as_posix()):
        text, big = utf8_text(path, file_cap)
        if not text:
            continue
        size = path.stat().st_size
        if big or full or total + size > total_cap:
            omitted += 1
            full = full or (not big and total + size > total_cap)
            continue
        rel = path.relative_to(workspace)
        target = Path(dest, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(rel.as_posix())
        total += size
    return copied, omitted
