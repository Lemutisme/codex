"""A sealed evaluator carries the same identity without sharing mutable thread state."""

import json
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import procontract_canonical as canonical
import procontract_study_evaluation as bridge
import test_procontract_study as fixtures

PYTHON = sys.executable


class StudyEvaluationTest(fixtures.StudyFixture):
    def setUp(self):
        super().setUp()
        self.addCleanup(bridge.bind, None)

    def test_real_seal_is_checked_in_the_credential_free_evaluator_environment(self):
        self.seal()
        (self.camp / "campaign.json").write_text(json.dumps(self.terms))
        bridge.bind(self.terms["study"], evaluator=True)
        expected = [
            "--study-manifest",
            str(self.camp / "study.json"),
            "--study-sha256",
            self.terms["study"]["manifest_sha256"],
        ]
        self.assertEqual(bridge.flags(), expected)
        with mock.patch.object(
            bridge.study.sys, "executable", str(self.root / "pb/.venv/bin/python")
        ):
            bridge.verify()
            path = self.root / "pb/.venv/lib/python3/site-packages/package.py"
            path.write_text("changed after task inference")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                bridge.verify()

    def test_parallel_canonical_commands_do_not_drop_another_threads_study_pin(self):
        barrier = threading.Barrier(2)
        descriptors = [
            {"manifest_path": f"/study-{i}/study.json", "manifest_sha256": str(i) * 64}
            for i in (1, 2)
        ]

        def command(descriptor):
            bridge.bind(descriptor)
            barrier.wait(timeout=10)
            return bridge.flags()

        with ThreadPoolExecutor(2) as pool:
            result = list(pool.map(command, descriptors))
        self.assertEqual(
            result,
            [
                [
                    "--study-manifest",
                    d["manifest_path"],
                    "--study-sha256",
                    d["manifest_sha256"],
                ]
                for d in descriptors
            ],
        )
        self.assertEqual(bridge.flags(), [])

    def test_child_cli_cannot_reach_preflight_with_a_missing_study_campaign(self):
        # Registry parsing succeeds; the study fence must fail before any ProgramBench/Docker import.
        child = subprocess.run(
            [
                PYTHON,
                str(Path(canonical.__file__).resolve()),
                "preflight",
                "--registry",
                self.terms["canonical"]["registry_path"],
                "--registry-sha256",
                self.terms["canonical"]["registry_sha256"],
                "--pins-sha256",
                "0" * 64,
                "--study-manifest",
                str(self.camp / "study.json"),
                "--study-sha256",
                "0" * 64,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("sealed evaluator campaign is missing", child.stderr)


if __name__ == "__main__":
    unittest.main()
