"""Integration checks against a real, unmodified native exec-server."""

import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(os.environ.get("BENCHMARK_EXEC_SERVER"), "set BENCHMARK_EXEC_SERVER")
class ProcessLimitTests(unittest.TestCase):
    def test_expiration_keeps_executor_and_protocol_usable(self):
        seconds = float(os.environ.get("BENCHMARK_PROCESS_SECONDS", "1.5"))
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "limits.jsonl"
            process = subprocess.Popen([
                sys.executable, str(Path(__file__).with_name("benchmark_exec_limit.py")),
                "--seconds", str(seconds), "--receipt", str(receipt), "--",
                os.environ["BENCHMARK_EXEC_SERVER"], "--listen", "stdio",
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            messages = queue.Queue()

            def consume():
                for raw in process.stdout:
                    messages.put(json.loads(raw))

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            seen = []

            def send(value):
                process.stdin.write((json.dumps(value) + "\n").encode())
                process.stdin.flush()

            def until(predicate):
                deadline = time.monotonic() + seconds + 15
                while time.monotonic() < deadline:
                    message = messages.get(timeout=max(.01, deadline - time.monotonic()))
                    seen.append(message)
                    if predicate(message):
                        return message
                self.fail("executor did not answer")

            def start(identity, pid, argv):
                send({"id": identity, "method": "process/start", "params": {
                    "processId": pid, "argv": argv, "cwd": Path(directory).as_uri(),
                    "env": {}, "tty": False, "arg0": None,
                }})

            try:
                send({"id": 1, "method": "initialize", "params": {"clientName": "limit-test"}})
                until(lambda message: message.get("id") == 1)
                send({"method": "initialized"})
                start(2, "bad", ["/nonexistent-benchmark-command"])
                self.assertIn("error", until(lambda message: message.get("id") == 2))
                before = time.monotonic()
                # A child holding the stdout pipe must also stop at the deadline.
                start(3, "long", ["sh", "-c", "sleep 600 & echo $! > child.pid; wait"])
                until(lambda message: message.get("id") == 3)
                time.sleep(seconds / 2)
                send({"id": 4, "method": "process/read", "params": {
                    "processId": "long", "afterSeq": 0, "maxBytes": 4096,
                }})
                until(lambda message: message.get("method") == "process/closed"
                      and message["params"]["processId"] == "long")
                elapsed = time.monotonic() - before
                self.assertGreaterEqual(elapsed, seconds * .95)
                self.assertLess(elapsed, seconds + 5)
                child = int((Path(directory) / "child.pid").read_text())
                stat = Path(f"/proc/{child}/stat")
                self.assertTrue(not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z")
                start(5, "quick", ["sh", "-c", "printf survived"])
                until(lambda message: message.get("method") == "process/closed"
                      and message["params"]["processId"] == "quick")
                output = b"".join(base64.b64decode(message["params"]["chunk"])
                                  for message in seen if message.get("method") == "process/output"
                                  and message["params"]["processId"] == "quick")
                self.assertEqual(output, b"survived")
                self.assertFalse(any(str(message.get("id", "")).startswith("benchmark-limit-")
                                     for message in seen))
            finally:
                process.stdin.close()
                code = process.wait(timeout=15)
                diagnostic = process.stderr.read().decode()
                reader.join(timeout=2)
                process.stdout.close()
                process.stderr.close()
            self.assertEqual(code, 0, diagnostic)
            events = [json.loads(line) for line in receipt.read_text().splitlines()]
            limited = [event["process_id"] for event in events if event["event"] == "process_limit"]
            self.assertEqual(limited, ["long"])
            self.assertEqual([e["response"]["result"]["running"] for e in events
                              if e["event"] == "termination_result"], [True])


if __name__ == "__main__":
    unittest.main()
