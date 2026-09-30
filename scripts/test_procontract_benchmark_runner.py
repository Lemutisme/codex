import json
import os
import sqlite3
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

import procontract_benchmark_runner as runner


class PackagingTest(unittest.TestCase):
    def test_package_excludes_reference_and_build_output_and_zeroes_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp, "workspace")
            (workspace / "src").mkdir(parents=True)
            (workspace / "target" / "release").mkdir(parents=True)
            (workspace / "compile.sh").write_text("#!/bin/sh\n")
            (workspace / "src" / "main.rs").write_text("fn main() {}\n")
            (workspace / "src" / "executable").write_text("kept: not the reference\n")
            (workspace / "target" / "release" / "c").write_text("binary\n")
            (workspace / "executable").write_text("reference\n")
            dest = Path(tmp, "submission.tar.gz")

            runner.package(workspace, dest)

            with tarfile.open(dest) as archive:
                members = archive.getmembers()
            names = {member.name for member in members}
            self.assertIn("./compile.sh", names)
            self.assertIn("./src/main.rs", names)
            self.assertIn("./src/executable", names)
            self.assertNotIn("./executable", names)
            self.assertFalse(any(name.startswith("./target") for name in names), names)
            self.assertEqual({(m.uid, m.gid) for m in members}, {(0, 0)})


class RestingTest(unittest.TestCase):
    def test_off_arm_rests_when_the_first_turn_completes(self):
        self.assertFalse(
            runner.is_done("off", None, turn_active=True, turns_completed=0)
        )
        self.assertTrue(
            runner.is_done("off", None, turn_active=False, turns_completed=1)
        )

    def test_on_arm_waits_for_a_resting_status_after_a_completed_turn(self):
        checking = {"phase": "checking", "resting": False}
        supported = {"phase": "supported", "resting": True}
        abstained = {"phase": "abstained", "resting": True}
        self.assertFalse(
            runner.is_done("on", checking, turn_active=False, turns_completed=1)
        )
        self.assertFalse(
            runner.is_done("on", supported, turn_active=True, turns_completed=1)
        )
        self.assertFalse(
            runner.is_done("on", abstained, turn_active=False, turns_completed=0)
        )
        self.assertTrue(
            runner.is_done("on", supported, turn_active=False, turns_completed=1)
        )
        self.assertTrue(
            runner.is_done("on", abstained, turn_active=False, turns_completed=1)
        )

    def test_on_arm_without_any_status_is_not_done(self):
        self.assertFalse(
            runner.is_done("on", None, turn_active=False, turns_completed=3)
        )

    def test_status_is_read_from_the_ledger_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp, "ledger_1.sqlite")
            with sqlite3.connect(ledger) as db:
                db.execute("CREATE TABLE records (kind TEXT, key TEXT, json TEXT)")
                db.execute(
                    "INSERT INTO records VALUES ('status', 'thread-1', ?)",
                    (json.dumps({"phase": "supported", "resting": True}),),
                )
            self.assertEqual(
                runner.read_status(ledger, "thread-1"),
                {"phase": "supported", "resting": True},
            )
            self.assertIsNone(runner.read_status(ledger, "thread-2"))
            self.assertIsNone(
                runner.read_status(Path(tmp, "missing.sqlite"), "thread-1")
            )


class AppServerTest(unittest.TestCase):
    def test_the_server_starts_in_the_run_directory_not_the_callers(self):
        # A caller's cwd may hold project-local `.codex` skills that must not reach the executor.
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp).resolve()
            server = runner.AppServer(
                ["sh", "-c", "pwd"],
                dict(os.environ),
                run_dir / "log",
                run_dir / "err",
                cwd=run_dir,
            )
            self.assertEqual(server.messages.get(timeout=10), {"method": "runner/eof"})
            server.close()
            self.assertEqual((run_dir / "log").read_text().strip(), str(run_dir))


class TurnTrackerTest(unittest.TestCase):
    def turn_event(self, method, thread_id, turn_id):
        return {
            "method": method,
            "params": {"threadId": thread_id, "turn": {"id": turn_id}},
        }

    def test_only_the_executor_threads_turns_are_counted(self):
        tracker = runner.TurnTracker("executor")

        tracker.observe(self.turn_event("turn/started", "worker", "w1"))
        self.assertFalse(tracker.active)
        tracker.observe(self.turn_event("turn/started", "executor", "t1"))
        tracker.observe(self.turn_event("turn/completed", "worker", "w1"))
        self.assertTrue(tracker.active)
        tracker.observe(self.turn_event("turn/completed", "executor", "t1"))

        self.assertEqual(
            (tracker.active, tracker.completed, tracker.turn_id), (False, 1, "t1")
        )


class CodexHomeTest(unittest.TestCase):
    def test_codex_home_has_the_model_the_container_environment_and_the_evaluation_grant(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, "codex-home")
            workspace = Path(tmp, "workspace")
            codex_bin = Path(tmp, "bin", "codex")

            runner.write_codex_home(home, workspace, codex_bin, "image:tag")

            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(config["model"], "gpt-5.6-luna")
            self.assertEqual(config["model_reasoning_effort"], "max")
            self.assertEqual(config["approval_policy"], "never")
            self.assertNotIn("mcp_servers", config)
            self.assertNotIn("notify", config)
            provider = config["model_providers"][config["model_provider"]]
            self.assertEqual(provider["env_key"], "OPENAI_API_KEY")

            environments = tomllib.loads((home / "environments.toml").read_text())
            self.assertEqual(environments["default"], "cleanroom")
            self.assertFalse(environments["include_local"])
            [environment] = environments["environments"]
            args = environment["args"]
            self.assertEqual(environment["program"], "docker")
            for flag, value in [("--network", "none"), ("--user", "1000:1000")]:
                self.assertEqual(args[args.index(flag) + 1], value)
            self.assertIn(f"{workspace}:/workspace", args)
            self.assertIn(f"{codex_bin}:/opt/codex:ro", args)
            self.assertNotIn("--privileged", args)
            self.assertFalse(any(str(home) in arg for arg in args), args)
            self.assertFalse(any("OPENAI_API_KEY" in arg for arg in args), args)

            settings = json.loads((home / "pro_contract" / "settings.json").read_text())
            profile = settings["evaluation"]
            self.assertEqual(profile["environment_id"], "cleanroom")
            self.assertEqual(profile["workspace_host_root"], str(workspace))
            self.assertIn("executable", profile["excluded_paths"])
            self.assertEqual(profile["check"]["image"], "image:tag")
            self.assertEqual(profile["check"]["user"], "1000:1000")
            # The check builds exactly as the official evaluator does.
            self.assertEqual(
                profile["check"]["build_command"],
                "chmod +x ./compile.sh && ./compile.sh",
            )
            self.assertEqual(profile["reference_command"], "/workspace/executable")
            self.assertEqual(settings["worker"]["model"], "gpt-5.6-luna")
            self.assertEqual(settings["worker"]["reasoning_effort"], "max")

    def test_arms_differ_only_in_the_feature_flag(self):
        on = runner.app_server_command(Path("/bin/codex"), "on")
        off = runner.app_server_command(Path("/bin/codex"), "off")
        self.assertEqual(
            on,
            [
                "/bin/codex",
                "--disable",
                "hooks",
                "--enable",
                "pro_contract",
                "app-server",
            ],
        )
        self.assertEqual(
            off,
            [
                "/bin/codex",
                "--disable",
                "hooks",
                "--disable",
                "pro_contract",
                "app-server",
            ],
        )


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    unittest.main()
