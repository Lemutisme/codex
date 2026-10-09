"""A deadline without a final turn notification still needs a real process exit."""

import io
import subprocess
import unittest
from unittest import mock

import procontract_benchmark_runner as runner


class ShutdownTest(unittest.TestCase):
    def test_shutdown_receipts_distinguish_exit_escalation_and_unknown(self):
        timeout = subprocess.TimeoutExpired("fixture", 1)
        cases = (
            ([0], 0, "stdin_closed", []),
            ([timeout, -15], -15, "terminate", [mock.call()]),
            ([timeout, timeout, -9], -9, "kill", [mock.call()]),
            ([timeout, timeout, timeout], None, "kill", [mock.call()]),
        )
        for waits, code, action, terminate_calls in cases:
            with self.subTest(action=action, code=code):
                server = runner.AppServer.__new__(runner.AppServer)
                server.process = mock.Mock()
                server.process.wait.side_effect = waits
                server.process.poll.return_value = code
                server._log, server._stderr = io.StringIO(), io.StringIO()
                self.assertEqual(
                    server.close(),
                    {
                        "status": "exited" if code is not None else "unknown",
                        "returncode": code,
                        "shutdown": action,
                    },
                )
                self.assertEqual(
                    server.process.terminate.call_args_list, terminate_calls
                )
                self.assertEqual(server.process.kill.call_count, int(action == "kill"))
                self.assertEqual(
                    server.process.wait.call_args_list,
                    [mock.call(timeout=t) for t in (30, 30, 5)[: len(waits)]],
                )
                self.assertTrue(server._log.closed and server._stderr.closed)


if __name__ == "__main__":
    unittest.main()
