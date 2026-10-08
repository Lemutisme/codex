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














if __name__ == "__main__":
    unittest.main()
