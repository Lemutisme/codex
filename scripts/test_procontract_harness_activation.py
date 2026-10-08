"""Real prepare/run plumbing with fake transport, never a model or Docker call."""

import argparse
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import procontract_benchmark_runner as runner
from procontract_delivery_budget import DeliveryBudget
import test_procontract_delivery_runner as delivery_tests


class HarnessActivationTest(unittest.TestCase):
    def test_program_changes_the_real_runner_decision_and_is_recorded(self):
        driver = delivery_tests.DeliveryRunnerTest()
        for decision in (True, False):
            with self.subTest(decision=decision):
                summary, methods = driver.drive(
                    reserve=0,
                    program={"schema": 1, "when": {"always": decision}},
                )
                self.assertEqual("turn/steer" in methods, decision)
                self.assertEqual(
                    {
                        key: summary["harness_program"][key]
                        for key in ("evaluations", "last_input", "last_decision")
                    },
                    {
                        "evaluations": 1,
                        "last_input": {
                            "deadline_secs": 18000,
                            "remaining_secs": 3600,
                            "turns_completed": 0,
                            "repairs_used": 0,
                        },
                        "last_decision": decision,
                    },
                )
                self.assertEqual(summary["deadline_secs"], 18000)

    def test_program_cannot_move_the_hosts_authority_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "harness.json").write_text('{"schema":1,"when":{"always":true}}')
            budget = DeliveryBudget(
                deadline_secs=100,
                reserve_secs=20,
                program=runner.harness_program.load(root),
            )
            server = mock.Mock()
            server.request.return_value = {"turnId": "turn"}
            turns = SimpleNamespace(
                active=True, thread_id="thread", turn_id="turn", completed=0
            )
            budget.maybe_steer(server, turns, None, mock.Mock(), elapsed_secs=50)
            server.request.assert_not_called()
            budget.maybe_steer(
                server, turns, {"phase": "checking"}, mock.Mock(), elapsed_secs=90
            )
            server.request.assert_not_called()
            budget.maybe_steer(server, turns, None, mock.Mock(), elapsed_secs=90)
            server.request.assert_called_once()

    def test_prepare_pins_task_and_research_programs_and_rejects_drift(self):
        for role in ("executor.md", "analyst.md", "challenger.md", "research.md"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                policy = root / "seed"
                policy.mkdir()
                (policy / role).write_text(f"Instructions for {role}")
                program_path = policy / "harness.json"
                program_path.write_text(
                    '{"schema":1,"when":{"remaining_fraction_lte":[1,5]}}'
                )
                program = runner.harness_program.load(policy)
                codex = root / "codex"
                codex.write_text("binary")
                prompt = root / "prompt"
                prompt.write_text("task")
                args = argparse.Namespace(
                    run_dir=root / "run",
                    codex_bin=codex,
                    workspace_from=root,
                    instance="task",
                    image="image",
                    policy=policy,
                    instructions=role,
                    no_reference=role != "executor.md",
                    prompt=prompt,
                    arm="on",
                    model="gpt-5.6-luna",
                    effort="max",
                    deadline_secs=18000,
                    delivery_reserve_secs=0,
                    stop_after_issue=False,
                )
                with (
                    mock.patch.object(runner, "harness_ready", return_value=None),
                    mock.patch.object(runner.subprocess, "run"),
                    mock.patch("sys.stdout"),
                ):
                    runner.prepare(args)
                manifest = json.loads((args.run_dir / "manifest.json").read_text())
                self.assertEqual(
                    (manifest["instructions"], manifest["harness_program"]),
                    (
                        role,
                        {
                            "sha256": program.digest,
                            "interpreter": runner.harness_program.INTERPRETER,
                        },
                    ),
                )
                config = tomllib.loads(
                    (args.run_dir / "codex-home/config.toml").read_text()
                )
                self.assertEqual(
                    config["developer_instructions"], f"Instructions for {role}"
                )
                (args.run_dir / "policy/harness.json").write_text(
                    '{"schema":1,"when":{"always":true}}'
                )
                with mock.patch.object(runner, "AppServer") as server:
                    with self.assertRaisesRegex(ValueError, "prepared identity"):
                        runner.run(args)
                    server.assert_not_called()

    def test_program_and_cli_override_cannot_silently_compete(self):
        with self.assertRaisesRegex(ValueError, "cannot be overridden"):
            delivery_tests.DeliveryRunnerTest().drive(
                program={"schema": 1, "when": {"always": True}}
            )

    def test_runtime_error_writes_an_invalid_execution_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text('{"image":"image"}')
            (root / "prompt.txt").write_text("task")
            args = argparse.Namespace(
                run_dir=root,
                codex_bin=root / "codex",
                arm="on",
                deadline_secs=18000,
                stop_after_issue=False,
            )
            server = mock.Mock()
            server.request.side_effect = RuntimeError("transport failed")
            with (
                mock.patch.object(runner, "AppServer", return_value=server),
                mock.patch.object(runner, "os", environ={"OPENAI_API_KEY": "test"}),
                mock.patch.object(runner, "current_key", return_value="test"),
                mock.patch.object(runner, "readable"),
                mock.patch("sys.stdout"),
            ):
                with self.assertRaises(RuntimeError):
                    runner.run(args)
            receipt = json.loads((root / "run.json").read_text())
            self.assertEqual(
                {
                    name: receipt[name]
                    for name in ("runner_error", "server_exited_early", "cost_unknown")
                },
                {
                    "runner_error": "RuntimeError",
                    "server_exited_early": True,
                    "cost_unknown": True,
                },
            )
            server.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
