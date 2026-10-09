"""Opt-in observer hooks preserve the task/RPC deadline and context payload."""

from pathlib import Path
import queue
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_native_trace_binding as binding


class TraceRunnerTests(unittest.TestCase):
    def test_ambient_trace_root_cannot_bypass_opt_in(self):
        base = {binding.ENV: "/unbounded/shared", "OPENAI_API_KEY": "synthetic"}
        env = runner.server_env(Path("/synthetic-run"), base)
        self.assertNotIn(binding.ENV, env)
        self.assertEqual(
            base, {binding.ENV: "/unbounded/shared", "OPENAI_API_KEY": "synthetic"}
        )
        self.assertEqual(env["OPENAI_API_KEY"], "synthetic")

    def test_observer_time_consumes_dispatch_window(self):
        server = runner.AppServer.__new__(runner.AppServer)
        server._next_id = 0
        server._send = mock.Mock()
        observer = mock.Mock(latest_dispatch=200, dispatch_skipped=False)
        server.notice_observer = observer
        with mock.patch.object(runner.time, "monotonic", side_effect=[100, 111]):
            with self.assertRaises(TimeoutError):
                server.request("turn/steer", {}, mock.Mock(), timeout=10)
        server._send.assert_not_called()
        self.assertTrue(observer.dispatch_skipped)

    def test_observed_request_keeps_original_rpc_timeout_and_payload(self):
        server = runner.AppServer.__new__(runner.AppServer)
        server._next_id = 0
        server._send = mock.Mock()
        server.notice_observer = mock.Mock(latest_dispatch=200, dispatch_skipped=False)
        server.messages = queue.Queue()
        server.messages.put({"id": 1, "result": {"turnId": "turn"}})
        with mock.patch.object(runner.time, "monotonic", side_effect=[100, 101, 101]):
            self.assertEqual(
                server.request(
                    "turn/steer", {"expectedTurnId": "turn"}, mock.Mock(), timeout=10
                ),
                {"turnId": "turn"},
            )
        server._send.assert_called_once_with(
            {"id": 1, "method": "turn/steer", "params": {"expectedTurnId": "turn"}}
        )


if __name__ == "__main__":
    unittest.main()
