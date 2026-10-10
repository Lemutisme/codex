"""Opt-in native steering/request witness, with only a localhost fake provider."""

import http.server
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest

import procontract_benchmark_runner as runner
from procontract_online_trace import OnlineTrace
from procontract_online_worker import ResearchRole
from test_procodex_native import custom_call


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE"),
    "set package for localhost native trace test",
)
class NativeTraceTests(unittest.TestCase):
    def test_steered_text_reaches_a_completed_native_model_request(self):
        requests = []
        first, release = threading.Event(), threading.Event()

        class Provider(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer LOCAL_FIXTURE_ONLY":
                    self.send_error(403)
                    return
                length = int(self.headers["Content-Length"])
                if not 0 < length < 2 << 20 or len(requests) >= 2:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(length))
                requests.append(body)
                number = len(requests)
                if number == 1:
                    first.set()
                    if not release.wait(20):
                        self.send_error(500)
                        return
                    item = custom_call(
                        body, "text('local fixture only');", "fixture-code"
                    )
                else:
                    item = {
                        "type": "message",
                        "id": "final",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Synthetic continuation completed.",
                            }
                        ],
                    }
                response = f"fixture-{number}"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                for event in [
                    {"type": "response.created", "response": {"id": response}},
                    {"type": "response.output_item.done", "item": item},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": response,
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 10,
                                "total_tokens": 20,
                            },
                        },
                    },
                ]:
                    self.wfile.write(
                        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                    )
                    self.wfile.flush()

        with tempfile.TemporaryDirectory(prefix="online-native-trace-") as temporary:
            root = Path(temporary)
            provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            provider.daemon_threads = True
            thread = threading.Thread(target=provider.serve_forever, daemon=True)
            thread.start()
            home = root / "codex-home"
            home.mkdir()
            (root / "home").mkdir()
            (home / "config.toml").write_text(
                ResearchRole.config(
                    {
                        "base_url": f"http://127.0.0.1:{provider.server_port}/v1",
                        "env_key": "LOCAL",
                    }
                )
            )
            (home / "environments.toml").write_text("include_local=false\n")
            trace = OnlineTrace(root, "0" * 64)
            server = None
            try:
                env = {
                    "PATH": "/usr/bin:/bin",
                    "HOME": str(root / "home"),
                    "CODEX_HOME": str(home),
                    "CODEX_SQLITE_HOME": str(home),
                    "ONLINE_RESEARCH_API_KEY": "LOCAL_FIXTURE_ONLY",
                    "CODEX_ROLLOUT_TRACE_ROOT": str(trace.root),
                }
                binary = Path(os.environ["PROCODEX_NATIVE_PACKAGE"]) / "bin/codex"
                server = runner.AppServer(
                    [str(binary), "app-server"],
                    env,
                    root / "rpc.jsonl",
                    root / "stderr.log",
                    root,
                )
                turns = runner.TurnTracker()

                def handle(message):
                    if "id" in message and "method" in message:
                        server.refuse(message)
                    else:
                        turns.observe(message)

                server.request(
                    "initialize",
                    {
                        "clientInfo": {"name": "online-trace-fixture", "version": "1"},
                        "capabilities": {"experimentalApi": True},
                    },
                    handle,
                )
                server.notify("initialized")
                created = server.request(
                    "thread/start",
                    {
                        "model": "gpt-5.6-luna",
                        "config": {"model_reasoning_effort": "max"},
                        "cwd": str(root),
                        "environments": [],
                        "ephemeral": True,
                        "selectedCapabilityRoots": [],
                    },
                    handle,
                )
                turns.thread_id = trace.thread_id = created["thread"]["id"]
                begun = server.request(
                    "turn/start",
                    {
                        "threadId": turns.thread_id,
                        "input": [
                            {
                                "type": "text",
                                "text": "Synthetic task; no filesystem or network work.",
                                "text_elements": [],
                            }
                        ],
                    },
                    handle,
                )
                turn_id = begun["turn"]["id"]
                self.assertTrue(first.wait(10))
                trace.latest_dispatch = time.monotonic() + 15
                server.notice_observer = trace
                notice = "Synthetic checkpoint: use the revised experimental strategy and continue this same task."
                ack = server.request(
                    "turn/steer",
                    {
                        "threadId": turns.thread_id,
                        "expectedTurnId": turn_id,
                        "input": [
                            {"type": "text", "text": notice, "text_elements": []}
                        ],
                    },
                    handle,
                    timeout=10,
                )
                release.set()
                deadline = time.monotonic() + 20
                while turns.completed == 0 and time.monotonic() < deadline:
                    try:
                        handle(server.messages.get(timeout=0.2))
                    except queue.Empty:
                        pass
                self.assertEqual(
                    turns.statuses,
                    ["completed"],
                    (root / "stderr.log").read_text()[-3000:],
                )
                closed = server.close()
                server = None
                result = trace.after_run(
                    {"attempt": {"outcome": "accepted", "turn_id": ack["turnId"]}},
                    closed,
                )
                self.assertEqual(result["evidence"]["status"], "observed", result)
                self.assertEqual(len(requests), 2)
                if output := os.environ.get("PROCODEX_ONLINE_TRACE_RECEIPT"):
                    Path(output).write_text(
                        json.dumps(
                            {
                                "evidence": result,
                                "synthetic_requests": 2,
                                "real_model_requests": 0,
                            },
                            indent=2,
                        )
                    )
            finally:
                release.set()
                if server is not None:
                    server.close()
                trace.close()
                provider.shutdown()
                provider.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
