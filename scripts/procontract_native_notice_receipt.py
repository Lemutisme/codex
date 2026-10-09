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


class Reader:
    """Observe an already configured native trace; never modify task control flow.

    Call before_steer immediately before sending the one fixed notice. Retain its
    Baseline only in host state, then call after_run after native shutdown. Unknown
    is missing evidence, not proof of non-delivery or a task-validity decision.
    """

    def __init__(
        self,
        trace_root: Path,
        *,
        thread_id: str,
        turn_id: str,
        limits: Limits = Limits(),
    ):
        self.root = Path(trace_root).absolute()
        self.thread_id = _identifier(thread_id)
        self.turn_id = _identifier(turn_id)
        self.limits = limits
        defaults = Limits()
        for key, value in vars(limits).items():
            maximum = getattr(defaults, key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 < value <= maximum
            ):
                raise ValueError(
                    "reader limits must be positive and no larger than defaults"
                )
            if key != "max_seconds" and type(value) is not int:
                raise ValueError("byte and count limits must be integers")

    def _same_turn(self, event):
        return (
            event["thread_id"] == self.thread_id
            and event["codex_turn_id"] == self.turn_id
        )

    def _notice(self, notice):
        _require(isinstance(notice, str), "invalid_notice")
        raw = notice.encode("utf-8")
        _require(0 < len(raw) <= self.limits.max_notice_bytes, "notice_size_limit")
        return _hash(raw)

    def _request(self, scan, bundle, event, notice):
        payload = event["payload"]
        _require(
            self._same_turn(event)
            and payload.get("thread_id") == self.thread_id
            and payload.get("codex_turn_id") == self.turn_id,
            "request_identity_mismatch",
        )
        _uuid(payload.get("inference_call_id"))
        body, digest = scan.payload(
            bundle, payload.get("request_payload"), "inference_request"
        )
        metadata = body.get("client_metadata")
        _require(
            isinstance(metadata, dict)
            and metadata.get("thread_id") == self.thread_id
            and metadata.get("turn_id") == self.turn_id,
            "request_identity_mismatch",
        )
        _require(body.get("previous_response_id") is None, "incremental_request")
        _require(isinstance(body.get("input"), list), "invalid_request_input")
        found = False
        user_items = []
        for item in body["input"]:
            _require(isinstance(item, dict), "invalid_request_input")
            if item.get("type") == "message" and item.get("role") == "user":
                user_items.append(item)
                content = item.get("content")
                _require(isinstance(content, list), "invalid_request_input")
                for part in content:
                    _require(isinstance(part, dict), "invalid_request_input")
                    if part.get("type") == "input_text":
                        _require(
                            isinstance(part.get("text"), str), "invalid_request_input"
                        )
                        found |= part["text"] == notice
        return digest, found, user_items

    def _no_history_change(self, events, after, through=None):
        for event in events:
            if (
                event["seq"] <= after
                or (through is not None and event["seq"] > through)
                or event["thread_id"] not in (None, self.thread_id)
            ):
                continue
            payload = event["payload"]
            kind = (payload["type"] + " " + str(payload.get("event_type", ""))).lower()
            _require(
                not any(
                    word in kind
                    for word in (
                        "compact",
                        "history_replac",
                        "history_reset",
                        "rolled_back",
                        "rollback",
                        "thread_reset",
                    )
                ),
                "history_changed",
            )

    def _observe(self, operation):
        try:
            return operation()
        except _Unknown as error:
            return {"status": "unknown", "reason": error.args[0]}
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            UnicodeError,
            RecursionError,
            OverflowError,
        ):
            # Never return exception messages: paths/content may be confidential.
            return {"status": "unknown", "reason": "unreadable_or_invalid_trace"}

    def before_steer(self, notice: str) -> Baseline | dict:
        def observe():
            notice_hash = self._notice(notice)
            scan = _Scan(self)
            bundle, manifest, raw_manifest, log, events = scan.snapshot()
            starts = [
                event
                for event in events
                if event["payload"]["type"] == "inference_started"
                and self._same_turn(event)
            ]
            _require(bool(starts), "missing_baseline_request")
            event = starts[-1]
            digest, present, _ = self._request(scan, bundle, event, notice)
            _require(not present, "notice_already_present")
            self._no_history_change(events, event["seq"])
            return Baseline(
                bundle.name,
                manifest["trace_id"],
                self.thread_id,
                self.turn_id,
                _hash(raw_manifest),
                len(log),
                _hash(log),
                events[-1]["seq"],
                event["seq"],
                event["payload"]["inference_call_id"],
                event["payload"]["request_payload"]["path"],
                digest,
                notice_hash,
            )

        return self._observe(observe)

    def after_run(
        self, baseline: Baseline | dict, *, notice: str, accepted_turn_id: str | None
    ) -> dict:
        def observe():
            _require(isinstance(baseline, Baseline), "baseline_unavailable")
            _require(accepted_turn_id == self.turn_id, "steer_not_acknowledged")
            _require(
                baseline.thread_id == self.thread_id
                and baseline.turn_id == self.turn_id
                and baseline.notice_sha256 == self._notice(notice),
                "baseline_identity_mismatch",
            )
            scan = _Scan(self)
            bundle, manifest, raw_manifest, log, events = scan.snapshot()
            _require(
                bundle.name == baseline.bundle
                and manifest["trace_id"] == baseline.trace_id
                and _hash(raw_manifest) == baseline.manifest_sha256,
                "baseline_changed",
            )
            _require(
                len(log) >= baseline.prefix_bytes
                and _hash(log[: baseline.prefix_bytes]) == baseline.prefix_sha256,
                "baseline_changed",
            )
            _require(
                0 < baseline.started_seq <= baseline.fence_seq <= len(events),
                "invalid_baseline",
            )
            original = events[baseline.started_seq - 1]
            _require(
                original["payload"]["type"] == "inference_started"
                and original["payload"].get("inference_call_id")
                == baseline.inference_call_id
                and original["payload"].get("request_payload", {}).get("path")
                == baseline.request_path,
                "baseline_changed",
            )
            digest, present, baseline_users = self._request(
                scan, bundle, original, notice
            )
            _require(
                digest == baseline.request_sha256 and not present, "baseline_changed"
            )
            # Later ordinary work cannot invalidate an established witness, but
            # a duplicated native attempt identity makes this log inconsistent.
            seen_starts, seen_terminals = set(), set()
            for event in events:
                kind = event["payload"]["type"]
                if kind not in (
                    "inference_started",
                    "inference_completed",
                    "inference_failed",
                    "inference_cancelled",
                ):
                    continue
                identifier = _uuid(event["payload"].get("inference_call_id"))
                seen = seen_starts if kind == "inference_started" else seen_terminals
                _require(identifier not in seen, "duplicate_inference_event")
                seen.add(identifier)
            starts, candidates = {}, set()
            attempts_seen = 0
            for completed in events:
                kind = completed["payload"]["type"]
                if kind not in (
                    "inference_started",
                    "inference_completed",
                    "inference_failed",
                    "inference_cancelled",
                ):
                    continue
                identifier = _uuid(completed["payload"].get("inference_call_id"))
                if kind == "inference_started":
                    starts[identifier] = completed
                    if completed["seq"] > baseline.fence_seq and self._same_turn(
                        completed
                    ):
                        attempts_seen += 1
                        if attempts_seen <= self.limits.max_candidates:
                            candidates.add(identifier)
                    continue
                if kind != "inference_completed" or identifier not in candidates:
                    continue
                started = starts[identifier]
                _require(
                    self._same_turn(completed) and completed["seq"] > started["seq"],
                    "completion_identity_mismatch",
                )
                self._no_history_change(events, baseline.started_seq, completed["seq"])
                request_hash, present, current_users = self._request(
                    scan, bundle, started, notice
                )
                _require(
                    current_users[: len(baseline_users)] == baseline_users,
                    "user_history_changed",
                )
                if not present:
                    continue
                response, response_hash = scan.payload(
                    bundle,
                    completed["payload"].get("response_payload"),
                    "inference_response",
                )
                response_id = _identifier(completed["payload"].get("response_id"))
                _require(
                    response.get("response_id") == response_id,
                    "response_identity_mismatch",
                )
                receipt = {
                    "status": "observed",
                    "scope": "request_contains_notice_and_response_completed",
                    "notice_sha256": baseline.notice_sha256,
                    "thread_id": self.thread_id,
                    "turn_id": self.turn_id,
                    "inference_call_id": identifier,
                    "started_seq": started["seq"],
                    "completed_seq": completed["seq"],
                    "response_id": response_id,
                    "fence_seq": baseline.fence_seq,
                    "baseline_request_sha256": baseline.request_sha256,
                    "manifest_sha256": baseline.manifest_sha256,
                    "request": {
                        **started["payload"]["request_payload"],
                        "sha256": request_hash,
                    },
                    "response": {
                        **completed["payload"]["response_payload"],
                        "sha256": response_hash,
                    },
                }
                _require(
                    len(json.dumps(receipt).encode()) <= self.limits.max_receipt_bytes,
                    "receipt_size_limit",
                )
                scan.check_time()
                return receipt
            reason = (
                "candidate_count_limit"
                if attempts_seen > self.limits.max_candidates
                else "no_completed_notice_request"
            )
            return {"status": "unknown", "reason": reason}

        return self._observe(observe)
