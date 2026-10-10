"""Opt-in installed native researcher against a localhost synthetic provider only."""

import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

import procontract_online as online
import procontract_online_worker as worker
from test_procontract_online import candidate
from test_procodex_native import text_values


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE"),
    "set package for zero-real-inference native test",
)
class NativeResearchTests(unittest.TestCase):
    def test_installed_native_consumes_method_and_has_no_execution_tools(self):
        requests = []
        program, final = candidate(online.seed(), "native")

        class Provider(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.headers.get("Authorization") != "Bearer LOCAL_FIXTURE_ONLY":
                    self.send_error(403)
                    return
                length = int(self.headers["Content-Length"])
                if not 0 < length < 1 << 20:
                    self.send_error(413)
                    return
                requests.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                for event in [
                    {
                        "type": "response.created",
                        "response": {"id": "research-fixture"},
                    },
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "message",
                            "id": "fixture-message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": final.decode()}
                            ],
                        },
                    },
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "research-fixture",
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

        with tempfile.TemporaryDirectory(prefix="online-native-test-") as temporary:
            root = Path(temporary)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result, receipt = worker.run(
                    Path(os.environ["PROCODEX_NATIVE_PACKAGE"]) / "bin/codex",
                    root,
                    {"program": online.seed(), "observations": {}, "past_rewards": []},
                    {
                        "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                        "env_key": "FIXTURE_KEY",
                    },
                    "LOCAL_FIXTURE_ONLY",
                    deadline_secs=45,
                    cancellation=threading.Event(),
                )
                self.assertEqual(
                    receipt["status"],
                    "completed",
                    (receipt, (root / "stderr.log").read_text()[-4000:]),
                )
                self.assertEqual(online.proposal(result)[0], program)
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(
                    (request["model"], request["reasoning"]["effort"]),
                    ("gpt-5.6-luna", "max"),
                )
                self.assertIn(
                    online.seed()["research"], "\n".join(text_values(request["input"]))
                )
                names = {v for v in text_values(request.get("tools", []))}
                self.assertFalse(
                    names
                    & {
                        "exec_command",
                        "shell",
                        "shell_command",
                        "read_file",
                        "apply_patch",
                        "read_evidence",
                    },
                    names,
                )
                if output := os.environ.get("PROCODEX_ONLINE_TEST_RECEIPT"):
                    Path(output).write_text(
                        json.dumps(
                            {
                                "native": receipt,
                                "synthetic_requests": len(requests),
                                "real_model_requests": 0,
                                "program": online.digest(program),
                            },
                            indent=2,
                        )
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
