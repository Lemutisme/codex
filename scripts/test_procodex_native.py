"""Opt-in real native/controller/evidence integration, exclusively against a local fake provider.

Set PROCODEX_NATIVE_PACKAGE and PROCODEX_TEST_IMAGE; no real credential or model is used.
"""

import http.server
import contextlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import tempfile
import threading
import time
import unittest

import procodex
from procontract_benchmark_runner import AppServer


def text_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)
    elif isinstance(value, str):
        yield value
        if value.startswith(("{", "[")):
            try:
                yield from text_values(json.loads(value))
            except ValueError:
                pass


def custom_call(body, code, name):
    roots = list(body.get("tools", []))
    for value in body.get("input", []):
        if value.get("type") == "additional_tools":
            roots.extend(value.get("tools", []))

    def walk(items, namespace=None):
        for item in items:
            if item.get("type") == "namespace":
                yield from walk(item.get("tools", []), item["name"])
            elif item.get("name") == "exec":
                yield item, namespace

    found = list(walk(roots))
    if len(found) != 1:
        raise AssertionError("one code-mode exec expected")
    tool, namespace = found[0]
    if tool["type"] != "custom":
        raise AssertionError("custom exec expected")
    return dict(
        type="custom_tool_call",
        call_id=name,
        name="exec",
        input=code,
        **({"namespace": namespace} if namespace else {}),
    )


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE"),
    "set native package for the isolated no-model integration",
)
class NativeEvidenceTest(unittest.TestCase):
    def test_real_executor_and_reviewer_use_frozen_handles(self):
        package = Path(os.environ["PROCODEX_NATIVE_PACKAGE"]).resolve()
        image = os.environ["PROCODEX_TEST_IMAGE"]
        with tempfile.TemporaryDirectory(prefix="procodex-native-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("not ready\n")
            source = root / "source"
            source.mkdir()
            counts = {}
            requests = []
            errors = []
            review_code = r"""
function decode(x) {
 if (typeof x === "string") { try { return decode(JSON.parse(x)); } catch (_) { return x; } }
 if (Array.isArray(x)) return decode(x[0]);
 if (x && (x.source_id !== undefined || x.entry !== undefined)) return x;
 if (x && x.text !== undefined) return decode(x.text);
 if (x && x.content !== undefined) return decode(x.content);
 if (x && x.content_items !== undefined) return decode(x.content_items);
 if (x && x.output !== undefined) return decode(x.output);
 return x;
}
for (const source of ["human_request", "contract_terms"]) {
 let offset = 0;
 for (let i = 0; i < 100; i++) {
  const value = decode(await tools.read_evidence({op:"read", source_id:source, offset}));
  if (value.eof) break; offset = value.next_offset;
 }
}
let denied;
try { denied = decode(await tools.read_evidence({op:"read",source_id:"/etc/passwd",offset:0})); }
catch (error) { denied = String(error); }
let id;
for (let offset = 0; offset < 50;) {
 const value = decode(await tools.read_evidence({op:"index",source_id:"",offset}));
 if (value.entry && value.entry.path === "answer.txt") { id = value.entry.source_id; break; }
 if (value.eof) break; offset = value.next_offset;
}
const artifact = decode(await tools.read_evidence({op:"read",source_id:id,offset:0}));
text({fixtureCitation:artifact.citation_id, artifact:artifact.text, denied});
"""

            class Provider(http.server.BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def log_message(self, *args):
                    pass

                def do_GET(self):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

                def do_POST(self):
                    try:
                        if (
                            self.headers.get("Authorization")
                            != "Bearer LOCAL_FIXTURE_ONLY"
                        ):
                            raise AssertionError("unexpected credential")
                        length = int(self.headers["Content-Length"])
                        if not 0 < length <= 2 << 20:
                            raise AssertionError("request bound")
                        body = json.loads(self.rfile.read(length))
                        requests.append(body)
                        if len(requests) > 16:
                            raise AssertionError("fixture request budget")
                        schema = (
                            body.get("text", {}).get("format", {}).get("schema", {})
                        )
                        props = schema.get("properties", {})
                        role = (
                            "draft"
                            if "differential_cases" in props
                            else "review"
                            if "coverage" in props
                            else "executor"
                        )
                        counts[role] = counts.get(role, 0) + 1
                        if role == "draft":
                            message = dict(
                                decision="contract",
                                reason="",
                                requirements=[
                                    dict(
                                        id="R1",
                                        text="answer.txt contains ready",
                                        source_id="request:0",
                                        inferred=False,
                                    )
                                ],
                                out_of_scope=[],
                                process_constraints=[],
                                differential_cases=[],
                                candidate_tests=False,
                            )
                        elif role == "review" and counts[role] % 2 == 1:
                            items = [custom_call(body, review_code, "review-evidence")]
                            message = None
                        elif role == "review":
                            candidates = [
                                match.group(1)
                                for value in text_values(body)
                                if (
                                    match := re.search(
                                        r'"fixtureCitation"\s*:\s*"(e[0-9]+)"', value
                                    )
                                )
                            ]
                            if not candidates:
                                raise AssertionError(
                                    "review evidence did not return a handle"
                                )
                            flattened = "\n".join(text_values(body))
                            if "ready" not in flattened or "Refused:" not in flattened:
                                raise AssertionError("missing artifact or refusal")
                            message = dict(
                                verdict="support",
                                coverage=[
                                    dict(requirement_id="R1", evidence=candidates[-1])
                                ],
                                findings=[],
                                terms_gap=[],
                                missing="",
                                residual="",
                            )
                        elif counts[role] == 1:
                            items = [
                                custom_call(
                                    body,
                                    """const r = await tools.exec_command({cmd:"printf 'ready\\n' > answer.txt",yield_time_ms:1000,max_output_tokens:1000});text(r);""",
                                    "write-answer",
                                )
                            ]
                            message = None
                        else:
                            message = "Fixture completed."
                        if message is not None:
                            items = [
                                dict(
                                    type="message",
                                    id=f"message-{len(requests)}",
                                    role="assistant",
                                    content=[
                                        dict(
                                            type="output_text",
                                            text=json.dumps(message)
                                            if isinstance(message, dict)
                                            else message,
                                        )
                                    ],
                                )
                            ]
                        response_id = f"local-{len(requests)}"
                        events = [
                            dict(type="response.created", response=dict(id=response_id))
                        ]
                        events += [
                            dict(type="response.output_item.done", item=item)
                            for item in items
                        ]
                        events += [
                            dict(
                                type="response.completed",
                                response=dict(
                                    id=response_id,
                                    usage=dict(
                                        input_tokens=10,
                                        output_tokens=10,
                                        total_tokens=20,
                                    ),
                                ),
                            )
                        ]
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        for event in events:
                            self.wfile.write(
                                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                            )
                        self.wfile.flush()
                    except Exception as error:
                        errors.append(str(error))
                        self.send_error(500, "fixture failure")

            provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            provider.daemon_threads = True
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            (source / "config.toml").write_text(
                procodex.toml(
                    dict(
                        model_provider="fixture",
                        model_providers=dict(
                            fixture=dict(
                                name="Local fixture",
                                base_url=f"http://127.0.0.1:{provider.server_port}/v1",
                                env_key="PROCODEX_FIXTURE_KEY",
                                wire_api="responses",
                                supports_websockets=False,
                                request_max_retries=0,
                                stream_max_retries=0,
                            )
                        ),
                    )
                )
            )
            home, native_config = procodex.configure(
                package,
                workspace,
                root / "state",
                source,
                image,
                'python3 -c \'from pathlib import Path; assert Path("answer.txt").read_text().strip() == "ready"\'',
                isolation="container-only",
            )
            env = {
                **os.environ,
                "CODEX_HOME": str(home),
                "PROCODEX_FIXTURE_KEY": "LOCAL_FIXTURE_ONLY",
            }
            for key in (
                "OPENAI_API_KEY",
                "OPENAI_API_KEY_FILE",
                "CODEX_ROLLOUT_TRACE_ROOT",
            ):
                env.pop(key, None)
            server = AppServer(
                [
                    str(package / "bin/codex"),
                    "--enable",
                    "pro_contract",
                    "--disable",
                    "hooks",
                    "app-server",
                ],
                env,
                root / "rpc.jsonl",
                root / "stderr.log",
                cwd=workspace,
            )

            def handle(value):
                if "id" in value and "method" in value:
                    server.refuse(value)

            status = None
            try:
                server.request(
                    "initialize",
                    dict(
                        clientInfo=dict(name="procodex-fixture", version="1"),
                        capabilities=dict(experimentalApi=True),
                    ),
                    handle,
                )
                server.notify("initialized")
                thread = server.request(
                    "thread/start",
                    dict(
                        model="gpt-5.6-luna",
                        cwd="/workspace",
                        sandbox=native_config["sandbox_mode"],
                        approvalPolicy="never",
                    ),
                    handle,
                )["thread"]["id"]
                server.request(
                    "turn/start",
                    dict(
                        threadId=thread,
                        input=[
                            dict(
                                type="text",
                                text="Make answer.txt contain ready.",
                                text_elements=[],
                            )
                        ],
                    ),
                    handle,
                )
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    try:
                        handle(server.messages.get(timeout=0.1))
                    except queue.Empty:
                        pass
                    database = home / "pro_contract/ledger_1.sqlite"
                    if database.exists():
                        with contextlib.closing(
                            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                        ) as connection:
                            row = connection.execute(
                                "SELECT json FROM records WHERE kind='status' AND key=?",
                                (thread,),
                            ).fetchone()
                        if row:
                            status = json.loads(row[0])
                            if status.get("resting"):
                                break
                self.assertEqual(errors, [])
                self.assertEqual((workspace / "answer.txt").read_text(), "ready\n")
                self.assertIsNotNone(status)
                self.assertEqual(status["phase"], "supported", status)
                self.assertGreaterEqual(counts.get("review", 0), 2)
            finally:
                server.close()
                server.process.stdout.close()
                server._log.close()
                provider.shutdown()
                provider.server_close()
                output = os.environ.get("PROCODEX_TEST_REPORT")
                if output:
                    import shutil

                    destination = Path(output)
                    destination.mkdir(parents=True, exist_ok=True)
                    for name in ("rpc.jsonl", "stderr.log"):
                        shutil.copy2(root / name, destination / name)
                    (destination / "result.json").write_text(
                        json.dumps(
                            dict(
                                status=status,
                                counts=counts,
                                errors=errors,
                                real_provider_calls=0,
                            ),
                            indent=2,
                        )
                    )
                    (destination / "requests.json").write_text(
                        json.dumps(requests, indent=2)
                    )


if __name__ == "__main__":
    unittest.main()
