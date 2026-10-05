import json
import os
import sqlite3
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

import procontract_benchmark_runner as runner


class HarnessReadyTest(unittest.TestCase):
    def test_codex_needs_an_executable_tool_host_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex = Path(tmp, "codex")
            codex.write_bytes(b"x")
            host = Path(tmp, "codex-code-mode-host")

            missing = runner.harness_ready(codex)
            host.write_bytes(b"x")
            host.chmod(0o644)
            not_executable = runner.harness_ready(codex)
            host.chmod(0o755)
            ready = runner.harness_ready(codex)

        self.assertIn("codex-code-mode-host", missing)
        self.assertIn("codex-code-mode-host", not_executable)
        self.assertIsNone(ready)


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

    def test_the_contract_counts_as_issued_once_the_lane_leaves_drafting(self):
        self.assertFalse(runner.issued(None))
        for phase in ["idle", "drafting"]:
            self.assertFalse(runner.issued({"phase": phase, "resting": False}))
        for phase in ["working", "checking", "supported", "not_verified"]:
            self.assertTrue(runner.issued({"phase": phase, "resting": False}))
        self.assertTrue(runner.issued({"phase": "abstained", "resting": True}))

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


class ServerEnvironmentTest(unittest.TestCase):
    def test_the_server_sees_neither_the_hosts_home_nor_its_codex_home(self):
        run_dir = Path("/runs/x")
        env = runner.server_env(
            run_dir, {"HOME": "/home/me", "OPENAI_API_KEY": "k", "PATH": "/bin"}
        )
        self.assertEqual(env["CODEX_HOME"], "/runs/x/codex-home")
        # Personal skills under ~/.agents would otherwise reach the executor's context.
        self.assertEqual(env["HOME"], "/runs/x/home")
        self.assertEqual((env["OPENAI_API_KEY"], env["PATH"]), ("k", "/bin"))


class TurnTrackerTest(unittest.TestCase):
    def turn_event(self, method, thread_id, turn_id):
        return {
            "method": method,
            "params": {"threadId": thread_id, "turn": {"id": turn_id}},
        }

    def test_a_failed_turns_error_is_kept(self):
        tracker = runner.TurnTracker("executor")
        tracker.observe(self.turn_event("turn/started", "executor", "t1"))
        failed = self.turn_event("turn/completed", "executor", "t1")
        failed["params"]["turn"].update(
            status="failed", error={"message": "stream disconnected before completion"}
        )
        tracker.observe(failed)
        self.assertEqual(
            (tracker.statuses, tracker.errors),
            (["failed"], ["stream disconnected before completion"]),
        )

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
    def test_a_version_brings_its_instructions_and_its_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp, "codex-home")
            instructions = 'Observe the reference "early".\nThen test.'
            runner.write_codex_home(
                home,
                Path(tmp, "workspace"),
                Path(tmp, "codex"),
                "image:tag",
                policy=Path(tmp, "policy"),
                developer_instructions=instructions,
            )
            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(config["developer_instructions"], instructions)
            self.assertIn("openai-custom", config["model_providers"])
            settings = json.loads((home / "pro_contract" / "settings.json").read_text())
            self.assertEqual(settings["policy"], str(Path(tmp, "policy")))

    def test_without_instructions_the_executor_keeps_its_defaults(self):
        config = tomllib.loads(runner.config_toml("  \n"))
        self.assertNotIn("developer_instructions", config)

    def test_a_task_without_a_reference_has_nothing_to_build_or_compare(self):
        evaluation = runner.settings(Path("/w"), "image:tag", reference=False)[
            "evaluation"
        ]
        self.assertIsNone(evaluation["reference_command"])
        self.assertIsNone(evaluation["check"]["build_command"])
        self.assertIsNone(evaluation["check"]["candidate_command"])

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


class InstanceTest(unittest.TestCase):
    def test_images_follow_programbench_naming(self):
        self.assertEqual(
            runner.cleanroom_image("wfxr__csview.8ac4de0"),
            "programbench/wfxr_1776_csview.8ac4de0:task_cleanroom",
        )
        self.assertEqual(runner.task_image("a__b.c"), "programbench/a_1776_b.c:task")


class SilentLaneTest(unittest.TestCase):
    def test_on_arm_without_status_ten_minutes_after_handoff_is_silent(self):
        self.assertFalse(runner.lane_silent("on", None, None, 1000.0))
        self.assertFalse(runner.lane_silent("on", None, 100.0, 699.0))
        self.assertTrue(runner.lane_silent("on", None, 100.0, 700.0))
        self.assertFalse(runner.lane_silent("on", {"resting": False}, 100.0, 9999.0))
        self.assertFalse(runner.lane_silent("off", None, 100.0, 9999.0))


class TurnStatusTest(unittest.TestCase):
    def test_completed_turn_statuses_are_recorded(self):
        tracker = runner.TurnTracker("t")
        tracker.observe(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "t",
                    "turn": {"id": "1", "status": "interrupted"},
                },
            }
        )
        self.assertEqual(tracker.statuses, ["interrupted"])


class CostTest(unittest.TestCase):
    def test_rollout_costs_split_executor_and_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp, "sessions", "2026", "10", "01")
            sessions.mkdir(parents=True)
            usage = {
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
                "total_tokens": 12,
            }
            for name, source in [
                ("rollout-a.jsonl", "vscode"),
                ("rollout-b.jsonl", {"internal": "extension_worker"}),
            ]:
                Path(sessions, name).write_text(
                    json.dumps({"type": "session_meta", "payload": {"source": source}})
                    + "\n"
                    + json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {"total_token_usage": usage},
                            },
                        }
                    )
                    + "\n"
                )
            costs = runner.rollout_costs(Path(tmp))
        self.assertEqual(costs["executor"]["total_tokens"], 12)
        self.assertEqual(
            (costs["workers"]["total_tokens"], costs["worker_rollouts"]), (12, 1)
        )

    def test_the_runner_has_no_future_import(self):
        self.assertNotIn("from __future__", Path(runner.__file__).read_text())


class TruncatedRolloutTest(unittest.TestCase):
    def test_a_truncated_last_line_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp, "sessions")
            sessions.mkdir()
            usage = {"total_tokens": 7}
            good = json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": usage},
                    },
                }
            )
            Path(sessions, "rollout-a.jsonl").write_text(good + '\n{"type": "event_m')
            costs = runner.rollout_costs(Path(tmp))
        self.assertEqual(costs["executor"]["total_tokens"], 7)
