"""Task-owned Responses gateway: one durable request/time budget for every role.

The provider client runs on the host. Execution containers use network=none and
never receive this endpoint or the upstream credential. This is an evaluation
adapter, not part of the ProContract responsibility kernel.
"""

import hashlib
import http.client
import http.server
import json
import os
import tempfile
from pathlib import Path
import socket
import sqlite3
import threading
import time
from urllib.parse import urlsplit


MAX_BODY = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def truncate_output(text):
    # Match ProgramBench's 5,000-character head and tail, not a token estimate.
    if len(text) < 10000:
        return text
    return (text[:5000] + f"\n<elided_chars>{len(text)-10000} characters elided</elided_chars>\n"
            + text[-5000:])


def prepare_payload(raw, model, effort):
    value = json.loads(raw)
    if (value.get("model") != model or value.get("reasoning", {}).get("effort") != effort
            or value.get("stream") is not True or value.get("background")
            or value.get("previous_response_id") or value.get("conversation")):
        raise ValueError("model, effort or foreground request differs from frozen profile")
    pending = list(value.get("tools", []))
    for item in value.get("input", []):
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            pending.extend(item.get("tools", []))
    while pending:
        tool = pending.pop()
        if tool.get("type") == "namespace":
            pending.extend(tool.get("tools", []))
        elif tool.get("type") not in ("function", "custom"):
            raise ValueError("provider-hosted tools are not admitted")
    outputs = []
    for item in value.get("input", []):
        if not isinstance(item, dict):
            raise ValueError("unexpected input item")
        if item.get("type") not in ("function_call_output", "custom_tool_call_output"):
            continue
        output = item.get("output")
        if isinstance(output, str):
            before = output
            item["output"] = truncate_output(output)
        elif isinstance(output, list):
            texts, unavailable = [], []
            for part in output:
                if not isinstance(part, dict):
                    raise ValueError("malformed tool observation")
                kind = part.get("type")
                if kind in ("input_text", "text") and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif kind in ("input_image", "input_file", "input_audio"):
                    unavailable.append(kind)
                else:
                    raise ValueError("malformed tool observation")
            before = "\n".join(texts)
            content = truncate_output(before)
            if unavailable:
                # A tool-result modality mismatch is feedback to the agent, not
                # a failed provider request or permission to widen the profile.
                # Keep the loss explicit and auditable; never forward these bytes.
                warning = ("Tool observation incomplete: this evaluation route accepts text only. "
                           + ", ".join(sorted(set(unavailable)))
                           + " content was not delivered. Use the available text execution/file interface.")
                content = warning + ("\n" + content if content else "")
                outputs.append({"call_id": item.get("call_id"), "kind": "unavailable_observation",
                                "content_types": unavailable,
                                "sha256": digest(json.dumps(output, sort_keys=True).encode())})
            item["output"] = [{"type": "input_text", "text": content}]
        else:
            raise ValueError("only text tool observations are admitted")
        if len(before) >= 10000:
            outputs.append({"call_id": item.get("call_id"), "original_characters": len(before),
                            "sha256": digest(before.encode())})
    # No externally fetched files or images can bypass the offline environment.
    pending = [value.get("input", [])]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            if any(key in item for key in ("file_url", "file_id", "image_url")):
                raise ValueError("remote or image input is not admitted by the text benchmark")
            pending.extend(item.values())
    return json.dumps(value, ensure_ascii=False).encode(), outputs


class Budget:
    """Account for every attempt; None independently removes a time or count ceiling."""

    def __init__(self, path, *, seconds=21600, requests=1000, model="gpt-5.6-luna", effort="max"):
        self.path = Path(path)
        self.resource_path = self.path.with_suffix(".resources.json")
        self.lock = threading.Lock()
        self.closed = False
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL, started REAL, deadline REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, started REAL, original_sha256 TEXT, forwarded_sha256 TEXT, truncations TEXT, finished REAL, http_status INTEGER, terminal TEXT, usage TEXT, failure TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS rejections (at REAL, reason TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS response_identity (request_id INTEGER PRIMARY KEY, model TEXT, effort TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS request_context (request_id INTEGER PRIMARY KEY, snapshot_json TEXT NOT NULL)")
        self.profile = dict(seconds=seconds, requests=requests, model=model, effort=effort)
        encoded = json.dumps(self.profile, sort_keys=True)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO budget(id,profile) VALUES(1,?)", (encoded,))
        if self.db.execute("SELECT profile FROM budget").fetchone()[0] != encoded:
            self.db.close()
            raise ValueError("durable budget profile changed")

    def arm(self):
        with self.lock:
            if self.closed:
                raise ValueError("budget_closed")
            with self.db:
                now = time.time()
                seconds = self.profile['seconds']
                self.db.execute("UPDATE budget SET started=?,deadline=? WHERE started IS NULL", (now, None if seconds is None else now+seconds))
            self._publish_resources_locked()
        return self.status()

    def _resource_snapshot_locked(self, current_request_included=False):
        started,deadline=self.db.execute("SELECT started,deadline FROM budget").fetchone()
        used=self.db.execute("SELECT count(*) FROM requests").fetchone()[0]
        unresolved=self.db.execute("SELECT count(*) FROM requests WHERE finished IS NULL").fetchone()[0]
        now=time.time();limit=self.profile['requests']
        return {
            'schema':'task_resources/v1','source':'task_allocator',
            'allocation_id':digest((str(self.path.resolve())+':'+str(started)).encode()),
            'observed_at':now,
            'model_requests':{'limit':limit,'reserved':used,'remaining':None if limit is None else max(0,limit-used),
                              'without_completion':unresolved,'current_request_included':current_request_included},
            'time':{'started_at':started,'deadline':deadline,'remaining_seconds':None if deadline is None else max(0,deadline-now)},
            'scope':'One original allocation shared by all task roles. Failed and interrupted calls stay charged. Counts without completion include calls whose outcome is unknown. Null means this allocator declares no limit in that dimension. This snapshot does not reserve future capacity or describe acceptance or user time preferences.',
        }

    def _publish_resources_locked(self):
        # The file is an optional host view of already committed allocator facts.
        # Serialize its publication with other database owners so an older view
        # cannot replace a newer reservation after a restart/concurrent dispatch.
        temporary=None
        try:
            self.db.execute('BEGIN IMMEDIATE')
            snapshot=self._resource_snapshot_locked()
            with tempfile.NamedTemporaryFile(mode='w',dir=self.path.parent,prefix='.resources-',delete=False) as f:
                temporary=f.name;json.dump(snapshot,f);f.flush();os.fsync(f.fileno())
            os.replace(temporary,self.resource_path);temporary=None
            self.db.commit()
        except (OSError, sqlite3.Error):
            self.db.rollback()  # The request transaction was already committed.
        finally:
            if temporary is not None:Path(temporary).unlink(missing_ok=True)

    def status(self):
        with self.lock:
            if self.closed:
                raise ValueError("budget_closed")
            started, deadline = self.db.execute("SELECT started,deadline FROM budget").fetchone()
            used = self.db.execute("SELECT count(*) FROM requests").fetchone()[0]
            rejection = self.db.execute("SELECT reason FROM rejections ORDER BY rowid DESC LIMIT 1").fetchone()
        return dict(**self.profile, started=started, deadline=deadline, used=used,
                    last_rejection=rejection[0] if rejection else None)

    def reject(self, reason):
        with self.lock:
            if self.closed:
                return
            with self.db:
                self.db.execute("INSERT INTO rejections(at,reason) VALUES(?,?)", (time.time(), reason))

    def observe_identity(self, request, response):
        model=response.get('model')
        effort=(response.get('reasoning') or {}).get('effort')
        with self.lock:
            if self.closed:
                return
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO response_identity VALUES(?,?,?)',(request,model,effort))
        if (model is not None and model!=self.profile['model']) or (effort is not None and effort!=self.profile['effort']):
            self.reject('upstream_model_or_effort_mismatch')
            raise ValueError('upstream_model_or_effort_mismatch')

    def reserve(self, original, forwarded, truncations):
        request, deadline, _ = self._reserve(original, forwarded, truncations, resource_context=False)
        return request, deadline

    def reserve_with_context(self, original, forwarded, truncations):
        """Reserve this call and project the allocator's actual state to every role."""
        return self._reserve(original, forwarded, truncations, resource_context=True)

    def _reserve(self, original, forwarded, truncations, *, resource_context):
        # A transaction precedes network dispatch. Concurrent roles and restarts
        # cannot exceed an explicit ceiling; failed/disconnected attempts count
        # even when the allocation has no request ceiling.
        with self.lock:
            if self.closed:
                raise ValueError("budget_closed")
            try:
                self.db.execute("BEGIN IMMEDIATE")
                started, deadline = self.db.execute("SELECT started,deadline FROM budget").fetchone()
                used = self.db.execute("SELECT count(*) FROM requests").fetchone()[0]
                if (started is None or (deadline is None and self.profile['seconds'] is not None)
                        or (deadline is not None and time.time() >= deadline)):
                    raise ValueError("wall_time_exhausted_or_unarmed")
                if self.profile['requests'] is not None and used >= self.profile['requests']:
                    raise ValueError("model_request_budget_exhausted")
                cursor = self.db.execute("INSERT INTO requests(started,original_sha256,forwarded_sha256,truncations) VALUES(?,?,?,?)",
                    (time.time(), digest(original), digest(forwarded), json.dumps(truncations)))
                request = cursor.lastrowid
                if resource_context:
                    snapshot = self._resource_snapshot_locked(current_request_included=True)
                    value = json.loads(forwarded)
                    # Append rather than rewriting the stable prompt prefix. This
                    # projection is refreshed at dispatch, never stored as user authority.
                    value.setdefault('input', []).append({
                        'type': 'message', 'role': 'developer',
                        'content': [{'type': 'input_text', 'text': '<task_resource_snapshot>\n'
                                    + json.dumps(snapshot, ensure_ascii=False)
                                    + '\n</task_resource_snapshot>'}],
                    })
                    forwarded = json.dumps(value, ensure_ascii=False).encode()
                    self.db.execute('UPDATE requests SET forwarded_sha256=? WHERE id=?', (digest(forwarded), request))
                    self.db.execute('INSERT INTO request_context VALUES(?,?)', (request, json.dumps(snapshot)))
                self.db.commit()
                self._publish_resources_locked()
                return request, deadline, forwarded
            except BaseException:
                self.db.rollback()
                raise

    def checkpoint(self, request, *, status=None, terminal=None, usage=None, failure=None, finished=False):
        with self.lock:
            if self.closed:
                return
            with self.db:
                self.db.execute("UPDATE requests SET http_status=COALESCE(?,http_status),terminal=COALESCE(?,terminal),usage=COALESCE(?,usage),failure=COALESCE(?,failure),finished=COALESCE(?,finished) WHERE id=?",
                    (status, terminal, json.dumps(usage) if usage is not None else None, failure, time.time() if finished else None, request))

    def close(self):
        # Socket cancellation can leave a late HTTP callback. Serialize SQLite
        # closure with every writer; late callbacks cannot touch the closed handle
        # or turn a retained incomplete request into an invented completion.
        with self.lock:
            if not self.closed:
                self.closed = True
                self.db.close()


class Gateway(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, budget, upstream, *, api_key=None):
        self.budget = budget
        self.upstream = urlsplit(upstream.rstrip('/'))
        if self.upstream.scheme not in ("http", "https") or self.upstream.username or self.upstream.query:
            raise ValueError("invalid upstream")
        if self.upstream.scheme == "http" and self.upstream.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("plaintext upstream must be loopback")
        self.api_key = api_key
        self.closing = threading.Event()
        self.connection_lock = threading.Lock()
        self.connections = set()
        super().__init__(("127.0.0.1", 0), Handler)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}/v1"

    def server_close(self):
        self.closing.set()
        with self.connection_lock:
            for endpoint in self.connections:
                try:
                    endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def refuse(self, message, status=400):
        self.close_connection = True
        body = json.dumps({"error": {"message": message}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.connection.settimeout(30)
        lengths = self.headers.get_all("Content-Length", [])
        if (self.path != "/v1/responses" or len(lengths) != 1 or not lengths[0].isdigit()
                or not 0 < int(lengths[0]) <= MAX_BODY or self.headers.get("Transfer-Encoding")):
            return self.refuse("request framing or endpoint is not admitted")
        raw = self.rfile.read(int(lengths[0]))
        if len(raw) != int(lengths[0]):
            return self.refuse("incomplete request")
        budget = self.server.budget
        try:
            forwarded, truncations = prepare_payload(raw, budget.profile['model'], budget.profile['effort'])
            request, deadline, forwarded = budget.reserve_with_context(raw, forwarded, truncations)
        except (ValueError, TypeError, AttributeError, sqlite3.Error) as error:
            budget.reject(str(error))
            return self.refuse(str(error), 409)
        upstream = self.server.upstream
        cls = http.client.HTTPSConnection if upstream.scheme == 'https' else http.client.HTTPConnection
        connection = cls(upstream.hostname, upstream.port, timeout=None if deadline is None else max(.001, deadline-time.time()))
        sockets = [self.connection]
        with self.server.connection_lock:
            self.server.connections.add(self.connection)
        expired = threading.Event()

        def expire():
            expired.set()
            for endpoint in sockets:
                try:
                    endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        timer = None
        if deadline is not None:
            timer = threading.Timer(max(0, deadline-time.time()), expire)
            timer.daemon = True
            timer.start()
        began = False
        try:
            connection.connect()
            sockets.append(connection.sock)
            with self.server.connection_lock:
                self.server.connections.add(connection.sock)
            if expired.is_set():
                raise TimeoutError("task deadline reached")
            if self.server.closing.is_set():
                raise TimeoutError("gateway closed before dispatch")
            headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
            if self.server.api_key:
                headers['Authorization'] = 'Bearer ' + self.server.api_key
            connection.request('POST', upstream.path+'/responses', body=forwarded, headers=headers)
            response = connection.getresponse()
            budget.checkpoint(request, status=response.status)
            if response.status != 200:
                return self.refuse(f"upstream_http_{response.status}", response.status if response.status >= 400 else 502)
            if not (response.getheader('Content-Type') or '').startswith('text/event-stream'):
                raise ValueError("upstream did not return an event stream")
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            began = True
            self.connection.settimeout(None if deadline is None else max(.001, deadline-time.time()))
            pending = bytearray()
            while chunk := response.read1(65536):
                pending.extend(chunk)
                while b'\n' in pending:
                    line, _, pending = pending.partition(b'\n')
                    if line.startswith(b'data: '):
                        try:
                            event = json.loads(line[6:])
                        except ValueError:
                            continue
                        if event.get('type') in ('response.completed', 'response.failed', 'response.incomplete'):
                            budget.observe_identity(request,event.get('response', {}))
                            budget.checkpoint(request, terminal=event['type'], usage=event.get('response', {}).get('usage'))
                if len(pending) > MAX_BODY:
                    raise ValueError('upstream frame too large')
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, ValueError, http.client.HTTPException) as error:
            budget.checkpoint(request, failure=type(error).__name__)
            if not began and not expired.is_set() and not self.server.closing.is_set():
                self.refuse('upstream transport failed', 502)
        finally:
            if timer:
                timer.cancel()
            with self.server.connection_lock:
                self.server.connections.difference_update(sockets)
            connection.close()
            self.close_connection = True
            budget.checkpoint(request, failure='task_deadline' if expired.is_set() else None, finished=True)

    def do_GET(self):
        self.refuse('method not admitted', 405)

    do_CONNECT = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
