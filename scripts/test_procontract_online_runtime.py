"""Actual online scheduler against deterministic native transport/worker seams."""

from concurrent.futures import Future
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_online as online
from procontract_online_lineage import Lineage
from procontract_online_runtime import OnlineRuntime
from test_procontract_online import candidate


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lineage = Lineage(self.root / "lineage")
        self.runtime = OnlineRuntime(
            self.lineage,
            "task",
            self.root / "online",
            Path("/codex"),
            {"base_url": "http://127.0.0.1", "env_key": "KEY"},
            "not-real",
            total_secs=1000,
            research_secs=100,
        )
        self.turns = SimpleNamespace(
            active=True, thread_id="t", turn_id="u", completed=0
        )
        self.status = {
            "phase": "working",
            "resting": False,
            "repairs_used": 0,
            "contract_id": "contract",
        }
        self.server = mock.Mock()
        self.server.request.return_value = {"turnId": "u"}
        self.handle = mock.Mock()
        self.closed = False
        self.addCleanup(self.close)

    def close(self):
        if not self.closed:
            self.closed = True
            return self.runtime.close()

    def observe(self, thread="t"):
        self.runtime.observe(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread,
                    "item": {
                        "type": "commandExecution",
                        "command": "check",
                        "exitCode": 1,
                        "status": "completed",
                        "aggregatedOutput": "observed failure",
                    },
                },
            },
            "t",
        )

    def poll(self, elapsed=100):
        self.runtime.poll(
            self.server, self.turns, self.status, self.handle, elapsed_secs=elapsed
        )

    def begin(self, raw=None, receipt=None):
        for _ in range(4):
            self.observe()
        future = Future()
        with mock.patch.object(
            self.runtime.pool, "submit", return_value=future
        ) as submit:
            self.poll(30)
        self.assertEqual(submit.call_count, 1)
        program, default = candidate(online.seed(), "focused")
        future.set_result(
            (
                raw if raw is not None else default,
                receipt or {"status": "completed", "elapsed_secs": 1},
            )
        )
        return program, submit.call_args

    def test_native_feedback_changes_program_and_fenced_checkpoint_without_new_turn(
        self,
    ):
        program, request = self.begin()
        self.assertEqual(
            request.args[3]["program"]["research"], online.seed()["research"]
        )
        self.poll()
        self.assertEqual(self.runtime.status, "experimental")
        self.assertEqual(self.lineage.current(), program)
        self.assertEqual(self.server.request.call_args.args[0], "turn/steer")
        params = self.server.request.call_args.args[1]
        self.assertEqual((params["threadId"], params["expectedTurnId"]), ("t", "u"))
        self.assertIn(program["execution"], params["input"][0]["text"])
        self.observe("another-thread")
        self.observe()
        self.poll()
        self.assertEqual(self.server.request.call_count, 1)
        terminal = self.close()
        self.assertEqual(
            (terminal["status"], terminal["command_completions_after_ack"]),
            ("experimental", 1),
        )

    def test_inactive_or_checking_executor_is_never_steered(self):
        self.begin()
        self.turns.active = False
        self.poll()
        self.turns.active = True
        self.status["phase"] = "checking"
        self.poll()
        self.server.request.assert_not_called()
        self.status["phase"] = "working"
        self.poll()
        self.server.request.assert_called_once()

    def test_unissued_contract_never_launches_research_or_steers(self):
        for _ in range(4):
            self.observe()
        self.status = {
            "phase": "abstained",
            "resting": True,
            "repairs_used": 0,
            "contract_id": None,
        }
        with mock.patch.object(self.runtime.pool, "submit") as submit:
            with self.assertRaisesRegex(RuntimeError, "issued ProContract"):
                self.poll()
            submit.assert_not_called()
        self.server.request.assert_not_called()

    def test_lost_ack_consumes_attempt_and_does_not_inherit(self):
        self.begin()
        self.server.request.side_effect = TimeoutError("lost")
        self.poll()
        self.poll()
        self.assertEqual(self.lineage.current(), online.seed())
        self.assertEqual(self.runtime.status, "not_applied")
        self.server.request.assert_called_once()

    def test_malformed_proposal_cannot_grade_itself_or_replace_policy(self):
        self.begin(raw=b'{"reward":1,"adopt":true}')
        self.poll()
        self.assertEqual(self.runtime.status, "rejected")
        self.assertEqual(self.lineage.current(), online.seed())
        self.server.request.assert_not_called()

    def test_deadline_expiry_never_dispatches_finished_research(self):
        self.begin()
        self.poll(901)
        self.server.request.assert_not_called()
        self.assertEqual(self.lineage.current(), online.seed())

    def test_insufficient_time_or_foreign_events_do_not_launch_research(self):
        for _ in range(4):
            self.observe("other")
        with mock.patch.object(self.runtime.pool, "submit") as submit:
            self.poll()
            for _ in range(4):
                self.observe()
            self.poll(899)
            submit.assert_not_called()

    def test_close_signals_cancellation_before_joining_worker(self):
        def worker(*_args, **kwargs):
            self.assertTrue(kwargs["cancellation"].wait(timeout=2))
            return None, {"status": "failed", "elapsed_secs": 0}

        for _ in range(4):
            self.observe()
        with mock.patch(
            "procontract_online_runtime.researcher.run", side_effect=worker
        ):
            self.poll(30)
            result = self.close()
        self.assertTrue(self.runtime.cancel.is_set())
        self.assertEqual(result["research"]["status"], "failed")
        self.assertEqual(self.lineage.current(), online.seed())


if __name__ == "__main__":
    unittest.main()
