"""Exercise the real runner loop with a deterministic app-server and clock."""

import argparse
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_benchmark_runner as runner


class DeliveryRunnerTest(unittest.TestCase):
    def test_issue_only_mode_rejects_convergence_before_starting_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text("{}")
            args = argparse.Namespace(
                run_dir=root,
                deadline_secs=18000,
                delivery_reserve_secs=3600,
                stop_after_issue=True,
            )
            with mock.patch.object(runner, "AppServer") as server:
                with self.assertRaises(ValueError):
                    runner.run(args)
                server.assert_not_called()

    def drive(
        self,
        *,
        reserve=3600,
        end="completed",
        reject=False,
        program=None,
        environment_disconnects=(),
    ):
        clock = [0.0]
        server = mock.Mock()
        working = {"phase": "working", "resting": False}
        supported = {"phase": "supported", "resting": True}
        status = [working]

        def event(method, state):
            return {
                "method": method,
                "params": {
                    "threadId": "executor",
                    "turn": {"id": "turn-1", "status": state},
                },
            }

        def respond(method, params, handle, timeout=None):
            if method == "thread/start":
                return {"thread": {"id": "executor"}}
            if method == "turn/start":
                handle(event("turn/started", "inProgress"))
                for disconnected in environment_disconnects:
                    handle(disconnected)
            if method == "turn/steer":
                if reject:
                    raise RuntimeError("active turn changed")
                return {"turnId": "turn-1"}
            if method == "turn/interrupt":
                handle(event("turn/completed", "interrupted"))
            return {}

        def message(timeout):
            if clock[0] == 0:
                clock[0] = 18001 if end == "deadline" else 14400
                return {}
            if end == "accepted_then_deadline":
                clock[0] = 18001
                return {}
            clock[0] += 5
            status[0] = supported
            return event("turn/completed", "completed")

        server.request.side_effect = respond
        server.messages.get.side_effect = message
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"image": "pinned", "model": "gpt-5.6-luna", "effort": "max"}
            if program is not None:
                (root / "policy").mkdir()
                (root / "policy" / "harness.json").write_text(json.dumps(program))
                loaded = runner.harness_program.load(root / "policy")
                manifest["harness_program"] = {
                    "sha256": loaded.digest,
                    "interpreter": runner.harness_program.INTERPRETER,
                }
            (root / "manifest.json").write_text(json.dumps(manifest))
            (root / "prompt.txt").write_text("ordinary task")
            args = argparse.Namespace(
                run_dir=root,
                codex_bin=root / "codex",
                arm="on",
                deadline_secs=18000,
                delivery_reserve_secs=reserve,
                stop_after_issue=False,
            )
            with (
                mock.patch.object(runner, "AppServer", return_value=server),
                mock.patch.object(runner, "os", environ={"OPENAI_API_KEY": "test"}),
                mock.patch.object(runner, "current_key", return_value="test"),
                mock.patch.object(
                    runner.time, "monotonic", side_effect=lambda: clock[0]
                ),
                mock.patch.object(
                    runner, "read_status", side_effect=lambda *_: status[0]
                ),
                mock.patch.object(runner, "rollout_costs", return_value={}),
                mock.patch.object(runner, "readable"),
                mock.patch("sys.stdout"),
            ):
                runner.run(args)
            summary = json.loads((root / "run.json").read_text())
        methods = [call.args[0] for call in server.request.call_args_list]
        return summary, methods

    def test_reserve_steers_without_starting_a_new_turn_or_extending_deadline(self):
        summary, methods = self.drive()
        self.assertEqual(
            (
                methods,
                summary["turn_statuses"],
                summary["deadline_secs"],
                summary["elapsed_secs"],
            ),
            (
                ["initialize", "thread/start", "turn/start", "turn/steer"],
                ["completed"],
                18000,
                14405,
            ),
        )
        self.assertFalse(summary.get("deadline_hit", False))
        self.assertEqual(summary["delivery_budget"]["attempt"]["outcome"], "accepted")

    def test_legacy_default_adds_no_model_context(self):
        summary, methods = self.drive(reserve=0)
        self.assertEqual(methods, ["initialize", "thread/start", "turn/start"])
        self.assertEqual(summary["turn_statuses"], ["completed"])

    def test_completed_turn_does_not_hide_execution_environment_loss(self):
        disconnected = {
            "method": "thread/environment/disconnected",
            "params": {"threadId": "executor", "environmentId": "cleanroom"},
            "emittedAtMs": 1234,
        }
        summary, methods = self.drive(
            reserve=0, environment_disconnects=(disconnected, disconnected)
        )
        self.assertEqual(
            (
                summary["server_exited_early"],
                summary["turn_statuses"],
                summary["execution_environment"],
                methods,
            ),
            (
                False,
                ["completed"],
                {
                    "disconnect_observed": True,
                    "disconnect_count": 2,
                    "disconnections": [
                        {"environment_id": "cleanroom", "emitted_at_ms": 1234},
                        {"environment_id": "cleanroom", "emitted_at_ms": 1234},
                    ],
                    "events_omitted": 0,
                },
                ["initialize", "thread/start", "turn/start"],
            ),
        )

    def test_deadline_interrupt_remains_interrupted_not_a_successful_handoff(self):
        summary, methods = self.drive(end="deadline")
        self.assertEqual(
            (
                methods,
                summary["deadline_hit"],
                summary["turn_statuses"],
                summary["status"],
            ),
            (
                ["initialize", "thread/start", "turn/start", "turn/interrupt"],
                True,
                ["interrupted"],
                {"phase": "working", "resting": False},
            ),
        )

    def test_rejected_steer_does_not_restart_or_abort_the_task(self):
        summary, methods = self.drive(reject=True)
        self.assertEqual(
            methods, ["initialize", "thread/start", "turn/start", "turn/steer"]
        )
        self.assertEqual(summary["turn_statuses"], ["completed"])
        self.assertEqual(summary["delivery_budget"]["attempt"]["outcome"], "error")

    def test_accepted_notice_is_not_a_completed_handoff(self):
        summary, methods = self.drive(end="accepted_then_deadline")
        self.assertEqual(methods[-2:], ["turn/steer", "turn/interrupt"])
        self.assertEqual(
            (
                summary["delivery_budget"]["attempt"]["outcome"],
                summary["turn_statuses"],
                summary["status"],
            ),
            ("accepted", ["interrupted"], {"phase": "working", "resting": False}),
        )


class RequestDeadlineTest(unittest.TestCase):
    def test_real_request_does_not_round_a_subsecond_budget_up_to_a_second(self):
        clock = [0.0]
        server = mock.Mock()
        server._next_id = 0

        def empty_queue(timeout):
            clock[0] += timeout
            raise queue.Empty

        server.messages.get.side_effect = empty_queue
        with mock.patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                runner.AppServer.request(
                    server, "turn/steer", {}, mock.Mock(), timeout=0.25
                )
        self.assertEqual(clock[0], 0.25)
        server.messages.get.assert_called_once_with(timeout=0.25)
        server._send.assert_called_once_with(
            {"id": 1, "method": "turn/steer", "params": {}}
        )


if __name__ == "__main__":
    unittest.main()
