"""Full-sweep admission and native grant accounting without any real model calls."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import procontract_benchmark_runner as runner
import procontract_succession_binding as binding
import procontract_sweep_docker as transport
import procontract_sweep_jobs as jobs
import procontract_sweep as sweep
import procontract_sweep_report as reporting
import procontract_sweep_archive as archiving
import test_procodex_native as fixture


class BindingTests(unittest.TestCase):
    def test_full_plan_and_case_binding_cannot_relabel_or_extend_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tasks = [f"task-{i}" for i in range(200)]
            plan = {
                "protocol": "successor-full-v1",
                "root": str(root),
                "entrypoint": str(Path(sweep.__file__).resolve()),
                "tasks": tasks,
                "cases": {
                    task: {
                        "registry": "fixture",
                        "registry_sha256": "a" * 64,
                        "pins_sha256": "b" * 64,
                    }
                    for task in tasks
                },
                "arms": ["successor"],
                "limits": {
                    "task_launches": 200,
                    "learning_launches": 0,
                    "allocated_seconds": 3600000,
                },
                "model": "gpt-5.6-luna",
                "effort": "max",
                "succession": {"max_sessions": 3, "total_secs": 14400},
                "episode_secs": 18000,
                "inference_secs": 14400,
                "grading_secs": 3600,
                "research_secs": 0,
                "parallel": 4,
                "files": {},
            }
            path = root / "plan.json"
            path.write_text(json.dumps(plan))
            self.assertEqual(
                sweep.verify(path, sweep.plans.sha(path), 199)["registry"], "fixture"
            )
            plan["cases"][tasks[199]]["limits"] = {}
            path.write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                sweep.verify(path, sweep.plans.sha(path), 199)

    def test_missing_scores_remain_bounds_not_a_zero_filled_mean(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "runs/0-successor"
            run.mkdir(parents=True)
            (run / "result.json").write_text(
                json.dumps(
                    {
                        "status": "scored",
                        "outcome": {
                            "valid": True,
                            "resolved": 3,
                            "total": 4,
                            "pass_rate": 0.75,
                        },
                    }
                )
            )
            result = reporting.write({"root": str(root), "tasks": ["one", "two"]})
            self.assertEqual(
                (
                    result["scored"],
                    result["scored_only_macro_fraction"],
                    result["planned_macro_bounds"],
                ),
                (1, 0.75, [0.375, 0.875]),
            )

    def test_closed_native_home_is_archived_losslessly_without_touching_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "codex-home"
            home.mkdir()
            (home / "evidence").write_bytes(b"preserve me")
            (root / "workspace").mkdir()
            (root / "run.json").write_text(
                json.dumps({"native_process_exit": {"status": "exited"}})
            )
            receipt = archiving.archive_home(root)
            self.assertFalse(home.exists())
            self.assertTrue((root / "workspace").is_dir())
            import tarfile

            with tarfile.open(root / receipt["archive"]) as archive:
                self.assertEqual(
                    archive.extractfile("codex-home/evidence").read(), b"preserve me"
                )

    def test_opt_in_is_explicit_finite_and_never_off(self):
        self.assertIsNone(binding.grant(0, 14400, "off"))
        self.assertEqual(
            binding.grant(3, 14400, "on"), {"max_sessions": 3, "total_secs": 14400}
        )
        for values in [
            (True, 14400, "on"),
            (17, 14400, "on"),
            (3, 14401, "on"),
            (3, 14400, "off"),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                binding.grant(*values)

    def test_native_settings_are_written_and_cannot_drift_after_prepare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            grant = binding.grant(3, 14400, "on")
            runner.write_codex_home(
                root / "codex-home",
                root / "workspace",
                root / "codex",
                "image",
                succession=grant,
            )
            path = root / "codex-home/pro_contract/settings.json"
            manifest = {
                "arm": "on",
                "succession": grant,
                "settings_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            binding.validate(root, manifest)
            value = json.loads(path.read_text())
            value["succession"]["max_sessions"] = 4
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                binding.validate(root, manifest)

    def test_budget_identity_and_double_issue_are_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            directory = home / "pro_contract"
            directory.mkdir()
            grant = binding.grant(3, 14400, "on")
            value = {
                "grant": grant,
                "started_ms": 1000,
                "deadline_ms": 14401000,
                "launches": 1,
                "executors": ["child"],
                "pending": None,
            }
            with sqlite3.connect(directory / "ledger_1.sqlite") as db:
                db.execute("CREATE TABLE records(kind TEXT,key TEXT,json TEXT)")
                db.execute(
                    "CREATE TABLE events(seq INTEGER,contract_id TEXT,command_json TEXT)"
                )
                db.execute(
                    "INSERT INTO records VALUES('succession','root',?)",
                    (json.dumps(value),),
                )
                for i, command in enumerate(
                    ["issue", "propose", "defeat", "propose", "support"]
                ):
                    db.execute(
                        "INSERT INTO events VALUES(?, 'root.1', ?)",
                        (i, json.dumps({"command": {"type": command}})),
                    )
            db.close()
            audit = binding.snapshot(home, "root", grant)
            self.assertEqual(
                (audit["issue_count"], audit["launches"], audit["pending"]),
                (1, 1, None),
            )
            self.assertEqual(
                audit["accepted_commands"],
                ["issue", "propose", "defeat", "propose", "support"],
            )
            with self.assertRaises(ValueError):
                binding.snapshot(home, "root", {**grant, "max_sessions": 4})

    def test_transport_owns_only_declared_episode_and_preserves_tighter_limits(self):
        env = {
            "PROCONTRACT_SWEEP_ID": "a" * 64,
            "PROCONTRACT_SWEEP_EPISODE": "7-successor",
        }
        result = transport.arguments(
            ["run", "--memory", "64m", "--network", "none", "image"], env
        )
        self.assertIn("procodex.episode=7-successor", result)
        self.assertEqual(result.count("--memory"), 1)
        self.assertEqual(result[result.index("--memory") + 1], "64m")
        self.assertEqual(
            transport.arguments(["inspect", "image"], {}), ["inspect", "image"]
        )
        with self.assertRaises(ValueError):
            transport.arguments(["run", "image"], {})

    @unittest.skipUnless(sys.platform == "linux", "Linux owned process groups")
    def test_parallel_cancellation_joins_all_owned_groups(self):
        with tempfile.TemporaryDirectory() as temporary:
            children = [
                jobs.Job(
                    [sys.executable, "-c", "import time;time.sleep(30)"],
                    Path(temporary) / f"{i}.log",
                    60,
                )
                for i in range(2)
            ]
            self.assertTrue(all(job.status() is None for job in children))
            jobs.cancel_all(children)
            self.assertTrue(
                all(
                    job.process.returncode is not None and job.log.closed
                    for job in children
                )
            )


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
    "explicit native package/image; localhost fixture only",
)
class NativeBindingTests(unittest.TestCase):
    def test_real_successor_usage_is_included_and_not_double_counted(self):
        case = fixture.NativeEvidenceTest(
            "test_real_executor_and_reviewer_use_frozen_handles"
        )
        case.succession_fixture = True
        case.benchmark_binding_fixture = True
        case.debug()


if __name__ == "__main__":
    unittest.main()
