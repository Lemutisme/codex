"""Real confirmation/store transactions reject source drift before first adoption."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_harness_program as harness
import procontract_rsi as rsi
import procontract_store as store
import test_procontract_rsi as fixtures
from test_procontract_recursive_engine import ActivatedTasks


class AdoptionIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        seed = root / "seed"
        shutil.copytree(rsi.V0_BUNDLE, seed)
        for name in rsi.BUNDLE_FILES:
            path = seed / name
            path.write_text(path.read_text() + "\nPEER_STAGE=0\n")
        (seed / harness.PROGRAM_FILE).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "when": {"remaining_fraction_lte": [1, 20]},
                }
            )
        )
        with mock.patch.object(rsi, "V0_BUNDLE", seed):
            self.camp = fixtures.campaign(temporary.name)
        self.tasks = ActivatedTasks()
        self.host = fixtures.host(self.camp, self.tasks)
        self.parent = self.host.incumbent()
        candidate = root / "candidate"
        shutil.copytree(self.host.version_dir(self.parent) / "bundle", candidate)
        executor = candidate / "executor.md"
        executor.write_text(executor.read_text() + "\nbetter\n")
        analyst = candidate / "analyst.md"
        analyst.write_text(analyst.read_text() + "\nA changed analysis method.\n")
        (candidate / harness.PROGRAM_FILE).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "when": {"remaining_fraction_lte": [1, 10]},
                }
            )
        )
        self.candidate = self.host.register(
            candidate, self.parent, self.parent, "fixture"
        )
        # FakeTasks grades the concrete executor change 0.6 versus 0.5; no gate is relaxed.
        self.assertEqual(
            self.host.confirm(self.candidate, self.parent),
            "confirmed; awaiting the principal's adoption",
        )
        self.adoption = f"adoption.{self.candidate[:16]}"
        self.bundle = self.host.version_dir(self.candidate) / "bundle"

    def test_supported_method_or_harness_drift_cannot_change_adoption_state(self):
        before = (
            self.host.incumbent(),
            self.host.contract(self.adoption),
            store.events(self.host.store),
        )
        for name, remove in (
            ("analyst.md", False),
            (harness.PROGRAM_FILE, False),
            (harness.PROGRAM_FILE, True),
        ):
            with self.subTest(name=name, remove=remove):
                path = self.bundle / name
                saved = path.read_bytes()
                if remove:
                    path.unlink()
                elif name == harness.PROGRAM_FILE:
                    path.write_text(json.dumps({"schema": 1, "when": {"always": True}}))
                else:
                    path.write_bytes(saved + b"\nUnconfirmed method change.\n")
                with self.assertRaisesRegex(
                    RuntimeError, "harness identity validation failed"
                ):
                    self.host.adopt(self.candidate)
                self.assertEqual(
                    (
                        self.host.incumbent(),
                        self.host.contract(self.adoption),
                        store.events(self.host.store),
                    ),
                    before,
                )
                path.write_bytes(saved)

    def test_settled_adoption_replay_remains_readable_after_source_cleanup(self):
        self.host.adopt(self.candidate)
        self.assertEqual(
            (self.host.incumbent(), self.host.contract(self.adoption)["standing"]),
            (self.candidate, "discharged"),
        )
        before = (self.host.contract(self.adoption), store.events(self.host.store))
        shutil.rmtree(self.bundle)
        reopened = fixtures.host(self.camp, self.tasks)
        self.assertEqual(
            reopened.adopt(self.candidate), f"{self.candidate[:12]} was already adopted"
        )
        self.assertEqual(reopened.incumbent(), self.candidate)
        self.assertEqual(
            (reopened.contract(self.adoption), store.events(reopened.store)), before
        )

    def test_registration_freezes_utf8_role_and_experiment_bytes(self):
        draft = self.camp / "mixed-line-endings"
        shutil.copytree(self.bundle, draft)
        role = "研究方法\r\nPreserve both line endings.\n".encode("utf-8")
        experiment = "外部证据\r\nFrozen experiment.\n"
        (draft / "research.md").write_bytes(role)
        version = self.host.register(draft, self.candidate, self.candidate, experiment)
        registered = self.host.version_dir(version)
        self.assertEqual(
            {
                "role": (registered / "bundle/research.md").read_bytes(),
                "experiment": (registered / "EXPERIMENT.md").read_bytes(),
            },
            {"role": role, "experiment": experiment.encode("utf-8")},
        )
        self.host.validate_harness(version)


if __name__ == "__main__":
    unittest.main()
