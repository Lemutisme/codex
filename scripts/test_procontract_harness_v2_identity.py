"""Real store identities and runner plumbing; synthetic checkpoint, no model or Docker."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_checkpoint as checkpoints
import procontract_rsi as rsi
import procontract_store as store
from test_procontract_checkpoint import make_checkpoint, reseal, write_json
import test_procontract_rsi as fixtures


class HarnessV2IdentityTest(unittest.TestCase):
    def test_registered_program_survives_prepare_run_and_checkpoint_import(self):
        variants = (
            ({"schema": 1, "when": {"always": True}}, "convergence-v1", 3600),
            (
                {
                    "schema": 2,
                    "action": "checkpoint",
                    "when": {
                        "command_completions_observed_gte": 1,
                    },
                },
                "bounded-steering-v2",
                14400,
            ),
            (
                {
                    "schema": 2,
                    "action": "converge",
                    "when": {
                        "command_completions_observed_gte": 1,
                    },
                },
                "bounded-steering-v2",
                3600,
            ),
        )
        for document, interpreter, remaining in variants:
            with self.subTest(document=document), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                host = fixtures.host(fixtures.campaign(tmp), fixtures.FakeTasks())
                source = root / "proposal"
                shutil.copytree(rsi.V0_BUNDLE, source)
                (source / "harness.json").write_text(json.dumps(document))
                parent = host.incumbent()
                version = host.register(source, parent, parent, "Fixture proposal.")
                registered = host.versions()[version]
                bundle = host.version_dir(version) / "bundle"
                program = runner.harness_program.load(bundle)
                identity = {"sha256": program.digest, "interpreter": interpreter}
                self.assertEqual(registered["harness"], identity)
                self.assertEqual(store.digest("version", registered), version)
                args = argparse.Namespace(
                    run_dir=root / "run",
                    codex_bin=root / "codex",
                    workspace_from=root,
                    instance="task",
                    image="image",
                    policy=bundle,
                    instructions="executor.md",
                    no_reference=False,
                    prompt=root / "prompt.txt",
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
                manifest_path = args.run_dir / "manifest.json"
                prepared = json.loads(manifest_path.read_text())
                self.assertEqual(prepared["harness_program"], identity)
                receipt, methods = self.run_prepared(args)
                host.validate_harness(version, args.run_dir)
                self.assertEqual(
                    (
                        receipt["harness_program"]["sha256"],
                        receipt["harness_program"]["interpreter"],
                        receipt["delivery_budget"]["attempt"],
                        methods,
                    ),
                    (
                        program.digest,
                        interpreter,
                        {
                            "turn_id": "turn-1",
                            "remaining_secs": remaining,
                            "outcome": "accepted",
                            **(
                                {"action": document["action"]}
                                if document["schema"] == 2
                                else {}
                            ),
                        },
                        ["initialize", "thread/start", "turn/start", "turn/steer"],
                    ),
                )
                self.assertEqual(
                    receipt["harness_program"]["last_input"],
                    {
                        "deadline_secs": 18000,
                        "remaining_secs": remaining,
                        "turns_completed": 0,
                        "repairs_used": 0,
                        **(
                            {"executor_command_completions_observed": 1}
                            if document["schema"] == 2
                            else {}
                        ),
                    },
                )
                artifact = root / "checkpoint"
                pin = make_checkpoint(
                    artifact,
                    native_sha256=registered["binary"],
                    bundle=bundle,
                    manifest=registered,
                )
                imported = checkpoints.load(artifact, pin)
                self.assertEqual(imported.origin["source_version"], version)
                self.assertEqual(
                    (imported.bundle / "harness.json").read_bytes(), program.source
                )
                self.assertEqual(
                    host.register(imported.bundle, parent, parent, "Fixture proposal."),
                    version,
                )
                if document["schema"] == 2:
                    prepared["harness_program"]["interpreter"] = "convergence-v1"
                    manifest_path.write_text(json.dumps(prepared))
                    with mock.patch.object(runner, "AppServer") as server:
                        with self.assertRaisesRegex(ValueError, "prepared identity"):
                            runner.run(args)
                        server.assert_not_called()
                    registered["harness"]["interpreter"] = "convergence-v1"
                    write_json(artifact, "incumbent/manifest.json", registered)
                    with self.assertRaisesRegex(ValueError, "harness identity"):
                        checkpoints.load(artifact, reseal(artifact))

    def run_prepared(self, args):
        clock, state = (
            [0.0],
            [{"phase": "working", "resting": False, "repairs_used": 0}],
        )
        server = mock.Mock()

        def event(method, status):
            return {
                "method": method,
                "params": {
                    "threadId": "executor",
                    "turn": {"id": "turn-1", "status": status},
                },
            }

        def respond(method, params, handle, timeout=None):
            if method == "thread/start":
                return {"thread": {"id": "executor"}}
            if method == "turn/start":
                handle(event("turn/started", "inProgress"))
            if method == "turn/steer":
                return {"turnId": "turn-1"}
            return {}

        def message(timeout):
            if clock[0] == 0:
                clock[0] = 3600
                return {
                    "method": "item/completed",
                    "params": {
                        "threadId": "executor",
                        "turnId": "turn-1",
                        "item": {
                            "id": "command-1",
                            "type": "commandExecution",
                            "status": "completed",
                            "exitCode": 0,
                        },
                    },
                }
            if clock[0] == 3600:
                clock[0] = 14400
                return {}
            clock[0] = 14405
            state[0] = {"phase": "supported", "resting": True, "repairs_used": 0}
            return event("turn/completed", "completed")

        server.request.side_effect = respond
        server.messages.get.side_effect = message
        with (
            mock.patch.object(runner, "AppServer", return_value=server),
            mock.patch.object(runner, "os", environ={"OPENAI_API_KEY": "test"}),
            mock.patch.object(runner, "current_key", return_value="test"),
            mock.patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(runner, "read_status", side_effect=lambda *_: state[0]),
            mock.patch.object(runner, "rollout_costs", return_value={}),
            mock.patch.object(runner, "readable"),
            mock.patch("sys.stdout"),
        ):
            runner.run(args)
        return (
            json.loads((args.run_dir / "run.json").read_text()),
            [call.args[0] for call in server.request.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
