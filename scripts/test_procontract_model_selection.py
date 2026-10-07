import argparse
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_evaluation as evaluation
import procontract_rsi as rsi
from test_procontract_rsi import campaign


class ModelSelectionTest(unittest.TestCase):
    def test_prepare_pins_model_for_executor_workers_and_run(self):
        for model, effort in [("gpt-5.6-luna", "max"), ("gpt-6-astra", "high")]:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                codex = root / "codex"
                codex.write_text("binary")
                prompt = root / "prompt.txt"
                prompt.write_text("task")
                args = argparse.Namespace(
                    run_dir=root / "run",
                    codex_bin=codex,
                    workspace_from=root,
                    instance="task",
                    image="image",
                    policy=None,
                    no_reference=False,
                    prompt=prompt,
                    arm="on",
                    model=model,
                    effort=effort,
                    deadline_secs=1,
                    stop_after_issue=False,
                )
                with (
                    mock.patch.object(runner, "harness_ready", return_value=None),
                    mock.patch.object(runner.subprocess, "run"),
                    mock.patch("sys.stdout"),
                ):
                    runner.prepare(args)
                home = args.run_dir / "codex-home"
                config = tomllib.loads((home / "config.toml").read_text())
                settings = json.loads(
                    (home / "pro_contract" / "settings.json").read_text()
                )
                manifest = json.loads((args.run_dir / "manifest.json").read_text())
                self.assertEqual(
                    {
                        "executor": (config["model"], config["model_reasoning_effort"]),
                        "worker": settings["worker"],
                        "manifest": (manifest["model"], manifest["effort"]),
                    },
                    {
                        "executor": (model, effort),
                        "worker": {
                            "model": model,
                            "reasoning_effort": effort,
                            "deadline_secs": 2400,
                        },
                        "manifest": (model, effort),
                    },
                )
                # Conflicting flags must not override the prepared manifest on a resumed run.
                args.model, args.effort = "not-the-pinned-model", "low"
                self.assert_run_model(args, model, effort)

    def test_old_manifest_runs_with_the_original_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(json.dumps({"image": "image"}))
            (root / "prompt.txt").write_text("task")
            args = argparse.Namespace(
                run_dir=root,
                codex_bin=root / "codex",
                arm="on",
                deadline_secs=1,
                stop_after_issue=False,
            )
            self.assert_run_model(args, "gpt-5.6-luna", "max")

    def assert_run_model(self, args, model, effort):
        server = mock.Mock()

        def respond(method, params, handle):
            if method == "thread/start":
                return {"thread": {"id": "thread"}}
            if method == "turn/start":
                handle({"method": "runner/eof"})
            return {}

        server.request.side_effect = respond
        with (
            mock.patch.object(runner, "AppServer", return_value=server),
            mock.patch.object(runner, "os", environ={"OPENAI_API_KEY": "test"}),
            mock.patch.object(runner, "current_key", return_value="test"),
            mock.patch.object(runner, "readable"),
            mock.patch("sys.stdout"),
        ):
            runner.run(args)
        [params] = [
            call.args[1]
            for call in server.request.call_args_list
            if call.args[0] == "thread/start"
        ]
        self.assertEqual(
            params,
            {
                "model": model,
                "config": {"model_reasoning_effort": effort},
                "sandbox": "danger-full-access",
                "approvalPolicy": "never",
                "cwd": "/workspace",
            },
        )
        summary = json.loads((args.run_dir / "run.json").read_text())
        self.assertEqual((summary["model"], summary["effort"]), (model, effort))

    def test_campaign_pins_and_propagates_model_to_every_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = campaign(tmp, model="gpt-6-astra", effort="high")
            host = rsi.Host(camp, runner=["fake-runner"])
            parent = host.incumbent()
            self.assertEqual(
                host.versions()[parent]["model"],
                {"id": "gpt-6-astra", "effort": "high"},
            )
            actual_run = rsi.subprocess.run
            invocations = []

            def invoke(command, **kwargs):
                if command[0] == "uv":
                    return mock.Mock(returncode=0)
                if command[0] != "fake-runner":
                    return actual_run(command, **kwargs)
                invocations.append(command)
                run_dir = Path(command[command.index("--run-dir") + 1])
                if command[1] == "prepare":
                    (run_dir / "workspace").mkdir(parents=True)
                else:
                    (run_dir / "run.json").write_text(
                        json.dumps({"turn_statuses": ["completed"]})
                    )
                return mock.Mock(returncode=0)

            with (
                mock.patch.object(rsi.subprocess, "run", side_effect=invoke),
                mock.patch.object(host.adapter, "await_images"),
                mock.patch.object(evaluation, "package"),
                mock.patch.object(
                    evaluation,
                    "evaluate_package",
                    return_value={"validity": "valid", "outcome": {"pass_rate": 1.0}},
                ),
                mock.patch.object(rsi, "compact"),
            ):
                for role in ["analyst", "challenger", "research"]:
                    root = camp / role
                    root.mkdir()
                    host.run_agent(root, role, parent, f"{role}.md", 1)
                result = host.adapter.run_and_label(
                    host, host.version_dir(parent) / "bundle", "task", camp / "task"
                )
            self.assertEqual(result["validity"], "valid")
            self.assertEqual(
                [
                    (
                        call[1],
                        call[call.index("--model") + 1],
                        call[call.index("--effort") + 1],
                    )
                    for call in invocations
                ],
                [
                    (phase, "gpt-6-astra", "high")
                    for _ in range(4)
                    for phase in ["prepare", "run"]
                ],
            )


if __name__ == "__main__":
    unittest.main()
