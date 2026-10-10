"""Private bounded native app-server transport. No CLI, retries or task capabilities.

This is capability minimization, not an OS sandbox proof. Native code and its V8
host remain trusted. Logs are private evidence and have hard local writer caps.
"""

import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time

import procontract_fixed_auditor_role as role

MAX_LINE = 3 << 20
MAX_LOG = 64 << 20
MAX_STDERR = 4 << 20
MAX_QUEUE = 256


class NativeSession:
    def __init__(self, process, service, root, cwd, deadline, *, worker_role=role):
        self.role = worker_role
        self.cancellation = None
        self.process, self.service, self.root, self.deadline = (
            process,
            service,
            root,
            deadline,
        )
        self.cwd = cwd
        self.queue = queue.Queue(MAX_QUEUE)
        self.failed = threading.Event()
        self.threads = []
        self.seq = 0
        self.thread_id = self.turn_id = None
        self.finals, self.usage = [], None
        self.terminal = None
        self.pending, self.pending_bytes = [], 0
        self.log_bytes = 0
        self.log = (root / "rpc.jsonl").open("xb")
        self.served = (root / "evidence-served.jsonl").open("xb")
        self.served_bytes = 0
        for stream, name, limit in (
            (process.stdout, "stdout", MAX_LOG),
            (process.stderr, "stderr", MAX_STDERR),
        ):
            worker = threading.Thread(
                target=self._reader, args=(stream, name, limit), daemon=True
            )
            worker.start()
            self.threads.append(worker)

    def _reader(self, stream, name, limit):
        consumed = 0
        try:
            with (self.root / f"{name}.log").open("xb") as log:
                while raw := stream.readline(MAX_LINE + 1):
                    consumed += len(raw)
                    if len(raw) > MAX_LINE or consumed > limit:
                        raise RuntimeError("native output exceeds writer bound")
                    log.write(raw)
                    log.flush()
                    if name == "stdout":
                        value = json.loads(raw, object_pairs_hook=_unique)
                        if not isinstance(value, dict):
                            raise ValueError("non-object native RPC")
                        self.queue.put(value, timeout=1)
            if name == "stdout":
                self.queue.put({"eof": True}, timeout=1)
        except (OSError, ValueError, RuntimeError, queue.Full):
            self.failed.set()

    def send(self, value):
        raw = role.encoded(value) + b"\n"
        if len(raw) > MAX_LINE:
            raise ValueError("outgoing native RPC exceeds bound")
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def receive(self):
        while True:
            if self.cancellation is not None and self.cancellation.is_set():
                raise RuntimeError("native worker cancelled")
            if self.failed.is_set():
                raise RuntimeError("native reader failed or exceeded a hard bound")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("fixed auditor deadline")
            try:
                value = self.queue.get(timeout=min(0.2, remaining))
                break
            except queue.Empty:
                pass
        if value.get("eof"):
            raise RuntimeError("native stdout ended before completion")
        raw = role.encoded(value) + b"\n"
        self.log_bytes += len(raw)
        if self.log_bytes > MAX_LOG:
            raise RuntimeError("native RPC log exceeds writer bound")
        self.log.write(raw)
        self.log.flush()
        params = value.get("params", {})
        if (
            self.thread_id is not None
            and self.turn_id is None
            and "method" in value
            and isinstance(params, dict)
            and params.get("threadId") == self.thread_id
            and ("turnId" in params or "turn" in params)
        ):
            self.pending_bytes += len(raw)
            if len(self.pending) >= 64 or self.pending_bytes > 4 << 20:
                raise RuntimeError("native pre-ACK turn queue exceeds bound")
            self.pending.append(value)
            return value
        return self.handle(value)

    def handle(self, value):
        method, params = value.get("method"), value.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("native RPC params must be an object")
        if method == "item/tool/call" and "id" in value:
            authorized = (
                params.get("threadId") == self.thread_id
                and params.get("turnId") == self.turn_id
                and params.get("tool") == "read_evidence"
                and params.get("namespace") is None
            )
            if not authorized:
                text, success = (
                    "Refused: unexpected tool or thread/turn identity.",
                    False,
                )
            else:
                text, success = self.service.call(params.get("arguments"))
            self.send(
                {
                    "id": value["id"],
                    "result": {
                        "contentItems": [{"type": "inputText", "text": text}],
                        "success": success,
                    },
                }
            )
            row = (
                role.encoded(
                    {
                        "arguments": params.get("arguments"),
                        "authorized": authorized,
                        "success": success,
                        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
                + b"\n"
            )
            self.served_bytes += len(row)
            if self.served_bytes > MAX_LOG:
                raise RuntimeError("evidence service log exceeds writer bound")
            self.served.write(row)
            self.served.flush()
        elif "id" in value and method:
            self.send(
                {
                    "id": value["id"],
                    "error": {
                        "code": -32601,
                        "message": "No capability granted by this fixed audit host",
                    },
                }
            )
        elif "id" not in value and params.get("threadId") == self.thread_id:
            if (
                method == "thread/tokenUsage/updated"
                and params.get("turnId") == self.turn_id
            ):
                usage = params.get("tokenUsage")
                total = usage.get("total") if isinstance(usage, dict) else None
                if not isinstance(total, dict) or any(
                    type(total.get(key)) is not int or total[key] < 0
                    for key in (
                        "totalTokens",
                        "inputTokens",
                        "cachedInputTokens",
                        "outputTokens",
                        "reasoningOutputTokens",
                    )
                ):
                    raise ValueError("malformed native token usage")
                self.usage = total
            if params.get("turnId") == self.turn_id and method == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage" and item.get("phase") in (
                    None,
                    "final_answer",
                ):
                    text = item.get("text")
                    if (
                        not isinstance(text, str)
                        or len(text.encode())
                        > min(MAX_LINE, (256 << 10) * len(self.service.packs))
                        or self.finals
                    ):
                        raise ValueError(
                            "missing, excessive or ambiguous native final result"
                        )
                    self.finals.append(text)
            if (
                method == "turn/completed"
                and params.get("turn", {}).get("id") == self.turn_id
            ):
                self.terminal = params["turn"]
        return value

    def request(self, method, params):
        self.seq += 1
        wanted = self.seq
        self.send({"id": wanted, "method": method, "params": params})
        while True:
            value = self.receive()
            if value.get("id") == wanted and "method" not in value:
                if "error" in value or "result" not in value:
                    raise RuntimeError(f"native request failed: {method}")
                return value["result"]

    def run(self):
        self.request(
            "initialize",
            {
                "clientInfo": {"name": "fixed-compliance-auditor", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized", "params": {}})
        thread = self.request(
            "thread/start",
            {
                "model": self.role.MODEL,
                "config": {"model_reasoning_effort": self.role.EFFORT},
                "cwd": str(self.cwd),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "baseInstructions": self.role.BASE,
                "developerInstructions": self.role.DEVELOPER,
                "ephemeral": True,
                "environments": [],
                "dynamicTools": getattr(self.role, "TOOLS", [self.role.TOOL]),
                "selectedCapabilityRoots": [],
            },
        )
        self.thread_id = thread["thread"]["id"]
        prompt = self.service.prompt()
        turn = self.request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "environments": [],
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "outputSchema": self.role.output_schema(self.service.packs),
            },
        )
        self.turn_id = turn["turn"]["id"]
        for value in self.pending:
            self.handle(value)
        self.pending.clear()
        while self.terminal is None:
            self.receive()
        if self.terminal.get("status") != "completed" or len(self.finals) != 1:
            raise RuntimeError(
                "auditor turn did not produce exactly one completed final result"
            )
        return self.finals[0].encode()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate native JSON key")
        value[key] = item
    return value


def ambient_preflight():
    """Linux snapshot admission, not a race-proof filesystem isolation guarantee."""
    if (
        sys.platform != "linux"
        or Path("/tmp").resolve() != Path("/tmp")
        or any(
            os.path.lexists(path)
            for path in ("/etc/codex", "/.codex/config.toml", "/tmp/.codex/config.toml")
        )
    ):
        raise RuntimeError(
            "fixed auditor requires Linux, real /tmp, and absent system/temporary-ancestor Codex layers"
        )
    return {
        "profile": "linux-empty-global-config-envless-v1",
        "system_directory_absent": True,
        "scope": "host snapshot; not an OS-level race-proof absence guarantee",
    }


def run(
    binary,
    root,
    service,
    provider,
    credential,
    *,
    deadline_secs=role.DEADLINE,
    worker_role=role,
    cancellation=None,
):
    """One native process, no retries. Caller must reserve and durably claim first.

    Test fixtures may pass a shorter deadline; the sealed paid caller cannot. Credential
    bodies are never written to configuration, logs or receipts by this host.
    """
    root = Path(root)
    ambient = ambient_preflight()
    for name in ("home", "codex-home", "tmp"):
        (root / name).mkdir(mode=0o700)
    (root / "codex-home/config.toml").write_text(worker_role.config(provider))
    (root / "codex-home/environments.toml").write_text("include_local = false\n")
    # Fresh explicit environment excludes hooks, proxies, trace roots, inherited CODEX settings,
    # model routing and credentials other than this separately supplied frozen provider key.
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "TMPDIR": str(root / "tmp"),
        "RUST_LOG": "warn",
        worker_role.CHILD_CREDENTIAL_KEY: credential,
    }
    cwd = Path(tempfile.mkdtemp(prefix="procontract-fixed-auditor-", dir="/tmp"))
    started = time.monotonic()
    process, session, result, timer = None, None, None, None
    timed_out = threading.Event()
    receipt = {
        "schema": 1,
        "status": "unknown",
        "final_usage": None,
        "usage_scope": "unavailable",
        "final_sha256": None,
        "thread_id": None,
        "turn_id": None,
        "native_exit": None,
        "ambient_config": ambient,
        "cwd": str(cwd),
    }
    try:
        process = subprocess.Popen(
            [str(binary), "app-server"],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

        def expire():
            timed_out.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(
            max(0, started + deadline_secs - time.monotonic()), expire
        )
        timer.daemon = True
        timer.start()
        session = NativeSession(
            process,
            service,
            root,
            cwd,
            started + deadline_secs,
            worker_role=worker_role,
        )
        session.cancellation = cancellation
        result = session.run()
        receipt.update(
            status="completed", final_sha256=hashlib.sha256(result).hexdigest()
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
        KeyError,
        TypeError,
    ) as error:
        if isinstance(error, TimeoutError):
            timed_out.set()
        receipt.update(
            status="timeout" if isinstance(error, TimeoutError) else "failed",
            error_type=type(error).__name__,
        )
    finally:
        if process is not None:
            if receipt["status"] != "completed" and process.poll() is None:
                try:
                    os.killpg(
                        process.pid,
                        signal.SIGKILL
                        if timed_out.is_set() or receipt["status"] == "timeout"
                        else signal.SIGTERM,
                    )
                except ProcessLookupError:
                    pass
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            # Clean only this newly-created process group, including a lingering V8 host.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # A descendant may retain stdout after the leader exits. Escalate the owned
            # group before joining reader threads; never close a buffered stream whose
            # reader can still hold its lock indefinitely.
            time.sleep(0.05)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            receipt["native_exit"] = process.returncode
            if session is not None:
                for worker in session.threads:
                    worker.join(timeout=2)
                for stream, worker in zip(
                    (process.stdout, process.stderr), session.threads, strict=True
                ):
                    if not worker.is_alive():
                        stream.close()
                session.log.close()
                session.served.close()
                receipt.update(
                    thread_id=session.thread_id,
                    turn_id=session.turn_id,
                    final_usage=session.usage,
                    evidence_calls=service.calls,
                    usage_scope="reported_native_total_not_billing"
                    if session.usage
                    else "unavailable",
                )
                if session.failed.is_set() or any(
                    worker.is_alive() for worker in session.threads
                ):
                    receipt["status"] = "failed"
            if process.returncode != 0:
                receipt["status"] = "failed"
        if timer is not None:
            timer.cancel()
        if timed_out.is_set():
            receipt["status"] = "timeout"
        try:
            cwd.rmdir()
            receipt["cwd_cleanup"] = "removed_empty_private_directory"
        except OSError:
            receipt["cwd_cleanup"] = "preserved_nonempty_or_unavailable"
            receipt["status"] = "failed"
        receipt["elapsed_secs"] = round(time.monotonic() - started, 3)
    return result, receipt
