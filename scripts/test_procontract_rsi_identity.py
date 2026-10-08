"""Version inheritance and analysis input identity, without models or containers."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_harness_program as program
import procontract_rsi as rsi
import procontract_store as store
import test_procontract_rsi as fixtures


class VersionIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = fixtures.host(
            fixtures.campaign(temporary.name), fixtures.FakeTasks()
        )
        self.parent = self.host.incumbent()
        self.delivery = self.root / "delivery"
        self.bundle = self.delivery / "policy"
        shutil.copytree(self.host.version_dir(self.parent) / "bundle", self.bundle)
        (self.delivery / "EXPERIMENT.md").write_text(
            "\n".join(
                f"## {section}\nBounded convergence."
                for section in rsi.EXPERIMENT_SECTIONS
            )
        )

    def write_program(self):
        (self.bundle / program.PROGRAM_FILE).write_text(
            json.dumps({"schema": 1, "when": {"remaining_fraction_lte": [1, 5]}})
        )

    def test_optional_program_preserves_old_identity_and_changes_execution_twin(self):
        original = self.host.versions()[self.parent]
        self.assertEqual(
            ("harness" in original, store.digest("version", original)),
            (False, self.parent),
        )
        before = rsi.delivery_subject(self.delivery, "experiment")
        self.write_program()
        candidate = self.host.register(
            self.bundle, self.parent, self.parent, "experiment"
        )
        expected = {
            **original,
            "lineage": {"parent": self.parent, "proposed_by": self.parent},
            "harness": {
                "interpreter": program.INTERPRETER,
                "sha256": program.load(self.bundle).digest,
            },
        }
        self.assertEqual(self.host.versions()[candidate], expected)
        self.assertEqual(self.host.twin(candidate), candidate)
        self.assertNotEqual(rsi.delivery_subject(self.delivery, "experiment"), before)
        self.assertEqual(
            (
                self.host.version_dir(candidate) / "bundle" / program.PROGRAM_FILE
            ).read_bytes(),
            (self.bundle / program.PROGRAM_FILE).read_bytes(),
        )

    def test_harness_change_needs_authorization_and_task_prediction(self):
        self.write_program()
        self.host.terms["mutable"] = rsi.BUNDLE_FILES
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent),
            (False, "changed files the campaign does not allow: harness.json", False),
        )
        self.host.terms["mutable"] = [*rsi.BUNDLE_FILES, program.PROGRAM_FILE]
        with mock.patch.object(
            self.host, "prediction_problem", return_value="missing prediction"
        ):
            self.assertEqual(
                self.host.qualify(self.delivery, self.parent),
                (False, "missing prediction", False),
            )
        with mock.patch.object(self.host, "prediction_problem", return_value=""):
            self.assertEqual(
                self.host.qualify(self.delivery, self.parent), (True, "qualified", True)
            )

    def test_invalid_programs_and_links_are_rejected_before_registration(self):
        path = self.bundle / program.PROGRAM_FILE
        for content in ('{"schema":1,"when":{"shell":"echo unsafe"}}', "not JSON"):
            with self.subTest(content=content):
                path.write_text(content)
                ok, reason, changed = self.host.qualify(self.delivery, self.parent)
                self.assertEqual((ok, changed), (False, False))
                self.assertIn("invalid harness program", reason)
                with self.assertRaises(ValueError):
                    self.host.register(
                        self.bundle, self.parent, self.parent, "experiment"
                    )
        self.write_program()
        target = self.root / "linked-program.json"
        path.replace(target)
        try:
            path.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent)[::2], (False, False)
        )




    def test_witness_requires_both_prepared_and_runtime_program_identities(self):
        self.write_program()
        candidate = self.host.register(self.bundle, self.parent, self.parent, "harness")
        run = self.root / "witness"
        fixtures.FakeTasks.write_evidence(run, 0)
        result = {"validity": "valid", "run_dir": str(run)}
        versions = self.host.versions()
        identity = versions[candidate]["harness"]
        (run / "manifest.json").write_text(json.dumps({"harness_program": identity}))
        (run / "run.json").write_text(
            json.dumps({"harness_program": {**identity, "evaluations": 0}})
        )
        worker_hash = store.digest(
            "policy_bundle",
            [
                (self.bundle / name).read_text()
                for name in ("drafter.md", "prober.md", "reviewer.md")
            ],
        )
        with (
            mock.patch.object(self.host, "measure", return_value=result),
            mock.patch.object(self.host, "versions", return_value=versions),
            mock.patch.object(
                store,
                "events",
                return_value=[
                    {
                        "event": {"identities": {"policies": {"bundle": worker_hash}}},
                    }
                ],
            ),
            mock.patch.object(rsi, "executor_delivered", return_value=True),
        ):
            adapter = rsi.ProgramBench(self.host.terms)
            self.assertEqual(adapter.witness(self.host, candidate), "")
            (run / "run.json").write_text(
                json.dumps({"harness_program": {**identity, "sha256": "wrong"}})
            )
            self.assertEqual(
                adapter.witness(self.host, candidate),
                f"harness identity validation failed for {candidate}: run.json does not match the version's harness identity",
            )

    def test_program_drift_blocks_execution_and_missing_activation_cannot_retry(self):
        self.write_program()
        candidate = self.host.register(self.bundle, self.parent, self.parent, "harness")
        frozen = self.host.version_dir(candidate) / "bundle" / program.PROGRAM_FILE
        saved = frozen.read_bytes()
        frozen.unlink()
        with self.assertRaisesRegex(RuntimeError, "version bundle"):
            self.host.measure(candidate, fixtures.DEV[0], "dev")
        self.assertEqual(self.host.adapter.runs, [])
        frozen.write_bytes(saved)
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "harness identity"):
                self.host.measure(candidate, fixtures.DEV[0], "dev")
        self.assertEqual(self.host.adapter.runs, [(candidate, fixtures.DEV[0])])

    def test_cached_valid_results_recheck_activation(self):
        self.write_program()
        candidate = self.host.register(self.bundle, self.parent, self.parent, "harness")
        identity = self.host.versions()[candidate]["harness"]
        original = self.host.adapter.run_and_label

        def measured(host, bundle, task, run):
            result = original(host, bundle, task, run)
            for name in ("manifest.json", "run.json"):
                (run / name).write_text(json.dumps({"harness_program": identity}))
            return result

        with mock.patch.object(
            self.host.adapter, "run_and_label", side_effect=measured
        ) as run:
            result = self.host.measure(candidate, fixtures.DEV[0], "dev")
            (Path(result["run_dir"]) / "run.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "run.json"):
                self.host.measure(candidate, fixtures.DEV[0], "dev")
            self.assertEqual(run.call_count, 1)

    def test_failed_runner_never_packages_leftovers(self):
        run = self.root / "failed-task"
        run.mkdir()
        adapter = rsi.ProgramBench(self.host.terms)
        for code, summary in (
            (1, {}),
            (0, None),
            (0, {"runner_error": "failed"}),
            (0, {"turn_statuses": ["failed"]}),
        ):
            with self.subTest(code=code, summary=summary):
                receipt = run / "run.json"
                if summary is None:
                    receipt.unlink(missing_ok=True)
                else:
                    receipt.write_text(json.dumps(summary))
                with (
                    mock.patch.object(adapter, "await_images"),
                    mock.patch.object(
                        rsi.subprocess,
                        "run",
                        side_effect=[
                            rsi.subprocess.CompletedProcess([], 0),
                            rsi.subprocess.CompletedProcess([], code),
                        ],
                    ),
                    mock.patch("procontract_evaluation.package") as package,
                ):
                    result = adapter.run_and_label(
                        self.host, self.bundle, fixtures.DEV[0], run
                    )
                    self.assertEqual(
                        (result["validity"], result["pass_rate"], package.call_count),
                        ("invalid", None, 0),
                    )

    def test_failed_learning_runner_cannot_qualify_its_documents(self):
        self.host.dev(self.parent)
        original = rsi.subprocess.run

        def failed(args, **kwargs):
            result = original(args, **kwargs)
            if fixtures.FAKE_RUNNER[1] in args and args[2] == "run":
                result.returncode = 1
            return result

        with mock.patch.object(rsi.subprocess, "run", side_effect=failed):
            k = self.host.analyze(self.parent)
        self.assertEqual(self.host.insight(k)["status"], "failed")
        root = self.host.camp / "insight" / str(k) / "analyst-1"
        self.assertTrue((root / "run" / "workspace" / "ANALYSIS.md").exists())
        self.assertTrue((root / "runner-failed.json").exists())

    def test_failed_research_releases_improvement_and_keeps_stream_policy(self):
        camp = self.root / "stream-case"
        camp.mkdir()
        host = fixtures.host(fixtures.stream_campaign(str(camp)), fixtures.FakeTasks())
        parent = host.incumbent()
        original = rsi.subprocess.run

        def failed(args, **kwargs):
            result = original(args, **kwargs)
            if (
                fixtures.FAKE_RUNNER[1] in args
                and args[2] == "run"
                and "/research/" in args[args.index("--run-dir") + 1].replace("\\", "/")
            ):
                result.returncode = 1
            return result

        with mock.patch.object(rsi.subprocess, "run", side_effect=failed):
            first = host.stream_step()
            host.stream_step()
        self.assertIn("research failed", first)
        self.assertEqual(
            (
                host.contract("improvement.1")["standing"],
                [b["version"] for b in host.batches()],
            ),
            ("released", [parent, parent]),
        )

    def test_role_files_and_bundle_root_cannot_redirect_host_reads(self):
        role = self.bundle / "research.md"
        role.write_bytes(b"x" * (rsi.MAX_BUNDLE_FILE + 1))
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent)[::2], (False, False)
        )
        role.unlink()
        try:
            role.symlink_to(self.root / "unreadable-target")
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent)[::2], (False, False)
        )
        rsi.delivery_subject(self.delivery, "rejected role")
        shutil.rmtree(self.bundle)
        self.bundle.symlink_to(
            self.host.version_dir(self.parent) / "bundle", target_is_directory=True
        )
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent)[::2], (False, False)
        )
        rsi.delivery_subject(self.delivery, "rejected bundle")

    def test_experiment_record_is_bounded_and_never_follows_links(self):
        path = self.delivery / "EXPERIMENT.md"
        for raw in (b"\xff", b"x" * (rsi.MAX_BUNDLE_FILE + 1)):
            path.write_bytes(raw)
            self.assertEqual(
                self.host.qualify(self.delivery, self.parent)[::2], (False, False)
            )
        path.unlink()
        try:
            path.symlink_to(self.root / "not-readable")
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(
            self.host.qualify(self.delivery, self.parent)[::2], (False, False)
        )



if __name__ == "__main__":
    unittest.main()
