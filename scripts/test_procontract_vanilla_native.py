"""Actual OFF runner, native Codex and Docker; localhost scripted provider, no paid model."""

import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procodex
import procontract_benchmark_runner as runner
import procontract_online as online
from procontract_online_trace import OnlineTrace
from test_procontract_online_cycle_native import FixtureProvider


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
    "requires existing native package and Docker image; no real inference",
)
class VanillaNativeTests(unittest.TestCase):
    def test_off_executes_and_stops_without_contract_workers_or_learning(self):
        package = Path(os.environ["PROCODEX_NATIVE_PACKAGE"])
        fixture = FixtureProvider(online.seed())
        self.addCleanup(fixture.close)
        fixture.more_commands.set()
        fixture.finish.set()
        with tempfile.TemporaryDirectory(prefix="procodex-off-native-") as temporary:
            root = Path(temporary)
            source, policy, run = root / "source", root / "policy", root / "run"
            source.mkdir()
            policy.mkdir()
            (source / "answer.txt").write_text("not ready\n")
            (policy / "executor.md").write_text(online.instructions(online.seed()))
            prompt = root / "prompt.txt"
            prompt.write_text("Make answer.txt contain ready.")
            config = procodex.toml(
                {
                    "model": "gpt-5.6-luna",
                    "model_reasoning_effort": "max",
                    "developer_instructions": online.instructions(online.seed()),
                    "model_provider": "fixture",
                    "approval_policy": "never",
                    "sandbox_mode": "danger-full-access",
                    "web_search": "disabled",
                    "model_providers": {
                        "fixture": {
                            **fixture.provider,
                            "name": "Local fixture",
                            "wire_api": "responses",
                            "supports_websockets": False,
                            "request_max_retries": 0,
                            "stream_max_retries": 0,
                        }
                    },
                }
            )
            args = SimpleNamespace(
                arm="off",
                run_dir=run,
                instance="local-fixture",
                image=os.environ["PROCODEX_TEST_IMAGE"],
                codex_bin=package / "bin/codex",
                model="gpt-5.6-luna",
                effort="max",
                prompt=prompt,
                study_manifest=None,
                study_sha256=None,
                workspace_from=source,
                no_reference=True,
                instructions="executor.md",
                policy=policy,
                stop_after_issue=False,
                delivery_reserve_secs=0,
                deadline_secs=120,
            )
            with mock.patch.object(runner, "config_toml", return_value=config):
                runner.prepare(args)
            trace = OnlineTrace(run, "a" * 64)
            env = {
                "PATH": os.environ["PATH"],
                "FIXTURE_KEY": "LOCAL_FIXTURE_ONLY",
                "OPENAI_API_KEY": "LOCAL_FIXTURE_ONLY",
            }
            try:
                with (
                    mock.patch.object(runner, "os", SimpleNamespace(environ=env)),
                    mock.patch.object(
                        runner, "current_key", return_value="LOCAL_FIXTURE_ONLY"
                    ),
                    mock.patch("builtins.print"),
                ):
                    runner.run(args, online_trace=trace)
            finally:
                trace.close()
            summary = json.loads((run / "run.json").read_text())
            self.assertEqual(fixture.errors, [])
            self.assertEqual(set(fixture.counts), {"executor"})
            self.assertEqual(
                {
                    "arm": summary["arm"],
                    "status": summary["status"],
                    "turns": summary["turn_statuses"],
                    "workers": summary["cost"]["worker_rollouts"],
                    "exit": summary["native_process_exit"]["returncode"],
                    "learning": summary.get("online_learning"),
                    "artifact": (run / "workspace/answer.txt").read_text(),
                    "ledger_exists": (
                        run / "codex-home/pro_contract/ledger_1.sqlite"
                    ).exists(),
                },
                {
                    "arm": "off",
                    "status": None,
                    "turns": ["completed"],
                    "workers": 0,
                    "exit": 0,
                    "learning": None,
                    "artifact": "ready\n",
                    "ledger_exists": False,
                },
            )
            if destination := os.environ.get("PROCODEX_CONTROL_REPORT"):
                report = Path(destination)
                report.mkdir(parents=True)
                for name in (
                    "run.json",
                    "manifest.json",
                    "online-trace-cleanup.json",
                    "private-native-trace.tar.gz",
                    "app-server.jsonl",
                ):
                    shutil.copyfile(run / name, report / name)


if __name__ == "__main__":
    unittest.main()
