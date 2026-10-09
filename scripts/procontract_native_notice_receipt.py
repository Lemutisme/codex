"""Bounded, read-only evidence of notice presence in a completed native request.

This does not bound the native trace writer's disk use, enable tracing, send
requests, judge model behavior, or prove attention, obedience, or utility.
The host must bind the reader/limits and protect a private trace root separately.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid


@dataclass(frozen=True)
class Limits:
    max_bundles: int = 64
    max_manifest_bytes: int = 65536
    max_log_bytes: int = 16 * 1024 * 1024
    max_line_bytes: int = 65536
    max_events: int = 50000
    max_payload_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_candidates: int = 8
    max_seconds: float = 2.0
    max_notice_bytes: int = 2048
    max_receipt_bytes: int = 8192


@dataclass(frozen=True)
class Baseline:
    bundle: str
    trace_id: str
    thread_id: str
    turn_id: str
    manifest_sha256: str
    prefix_bytes: int
    prefix_sha256: str
    fence_seq: int
    started_seq: int
    inference_call_id: str
    request_path: str
    request_sha256: str
    notice_sha256: str


class _Unknown(Exception):
    pass


def _require(condition, reason):
    if not condition:
        raise _Unknown(reason)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _identifier(value):
    _require(isinstance(value, str) and 0 < len(value) <= 128, "invalid_identifier")
    return value


def _uuid(value):
    value = _identifier(value)
    _require(str(uuid.UUID(value)) == value, "invalid_identifier")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)


class _Scan:
    def __init__(self, reader):
        self.reader = reader
        self.bytes_read = 0
        self.started = time.monotonic()

    def check_time(self):
        # Cooperative only: a synchronous filesystem operation can itself block.
        _require(
            time.monotonic() - self.started <= self.reader.limits.max_seconds,
            "reader_time_limit",
        )

    def read(self, path, limit):
        self.check_time()
        root = self.reader.root
        _require(not root.is_symlink() and root.is_dir(), "unsafe_trace_root")
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            _require(not current.is_symlink(), "unsafe_path")
        _require(path.resolve().is_relative_to(root.resolve()), "unsafe_path")
        _require(stat.S_ISREG(path.lstat().st_mode), "not_regular_file")
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode), "not_regular_file")
            _require(info.st_size <= limit, "file_size_limit")
            remaining = self.reader.limits.max_total_bytes - self.bytes_read
            _require(info.st_size <= remaining, "reader_byte_limit")
            raw = stream.read(min(limit, remaining) + 1)
        self.bytes_read += len(raw)
        _require(len(raw) <= limit, "file_size_limit")
        _require(
            self.bytes_read <= self.reader.limits.max_total_bytes, "reader_byte_limit"
        )
        self.check_time()
        return raw

    def snapshot(self):
        _require(not self.reader.root.is_symlink(), "unsafe_trace_root")
        matches = []
        count = 0
        with os.scandir(self.reader.root) as iterator:
            for entry in iterator:
                count += 1
                _require(count <= self.reader.limits.max_bundles, "bundle_count_limit")
                bundle = self.reader.root / entry.name
                _require(not bundle.is_symlink() and bundle.is_dir(), "unsafe_bundle")
                raw_manifest = self.read(
                    bundle / "manifest.json", self.reader.limits.max_manifest_bytes
                )
                manifest = _json(raw_manifest)
                _require(isinstance(manifest, dict), "invalid_manifest")
                if manifest.get("root_thread_id") == self.reader.thread_id:
                    matches.append((bundle, manifest, raw_manifest))
        _require(len(matches) == 1, "missing_or_ambiguous_bundle")
        bundle, manifest, raw_manifest = matches[0]
        _require(
            type(manifest.get("schema_version")) is int
            and manifest["schema_version"] == 1,
            "unsupported_schema",
        )
        trace_id = _uuid(manifest.get("trace_id"))
        _require(
            bundle.name == f"trace-{trace_id}-{self.reader.thread_id}",
            "bundle_identity_mismatch",
        )
        _require(manifest.get("rollout_id") == self.reader.thread_id, "root_mismatch")
        _require(
            manifest.get("raw_event_log") == "trace.jsonl"
            and manifest.get("payloads_dir") == "payloads",
            "unsafe_manifest_path",
        )
        _require(type(manifest.get("started_at_unix_ms")) is int, "invalid_manifest")
        log = self.read(bundle / "trace.jsonl", self.reader.limits.max_log_bytes)
        _require(log.endswith(b"\n"), "partial_event_log")
        lines = log.splitlines()
        _require(0 < len(lines) <= self.reader.limits.max_events, "event_count_limit")
        events = []
        for seq, line in enumerate(lines, 1):
            self.check_time()
            _require(len(line) <= self.reader.limits.max_line_bytes, "event_size_limit")
            event = _json(line)
            _require(isinstance(event, dict), "invalid_event")
            _require(
                type(event.get("schema_version")) is int
                and event["schema_version"] == 1,
                "unsupported_schema",
            )
            _require(
                type(event.get("seq")) is int and event["seq"] == seq,
                "event_sequence_mismatch",
            )
            _require(event.get("rollout_id") == self.reader.thread_id, "root_mismatch")
            _require(
                type(event.get("wall_time_unix_ms")) is int
                and "thread_id" in event
                and "codex_turn_id" in event,
                "invalid_event",
            )
            _require(isinstance(event.get("payload"), dict), "invalid_event")
            _identifier(event["payload"].get("type"))
            events.append(event)
        roots = [
            event["payload"]
            for event in events
            if event["payload"]["type"] == "thread_started"
            and event["payload"].get("thread_id") == self.reader.thread_id
        ]
        _require(
            len(roots) == 1 and roots[0].get("agent_path") == "/root",
            "root_agent_mismatch",
        )
        return bundle, manifest, raw_manifest, log, events

    def payload(self, bundle, ref, kind):
        _require(
            isinstance(ref, dict) and set(ref) == {"raw_payload_id", "kind", "path"},
            "invalid_payload_ref",
        )
        _require(ref["kind"] == {"type": kind}, "payload_kind_mismatch")
        path = ref["path"]
        _require(isinstance(path, str) and len(path) <= 128, "invalid_payload_ref")
        match = re.fullmatch(r"payloads/([1-9][0-9]*)\.json", path)
        _require(
            match is not None and ref["raw_payload_id"] == f"raw_payload:{match[1]}",
            "invalid_payload_ref",
        )
        raw = self.read(bundle / path, self.reader.limits.max_payload_bytes)
        value = _json(raw)
        _require(isinstance(value, dict), "invalid_payload")
        return value, _hash(raw)


