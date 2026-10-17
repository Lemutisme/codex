"""Host-only collection qualification: fixed identities, explicit import failures."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from procontract_evaluator_readiness import collection_evaluator


class Base:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.result = SimpleNamespace(log=[], error_code=None, executable_hash=None)
        self.tests_branches = ["branch"]
        self.tests_by_branch = {"branch": ["suite.test_a", "suite.test_b"]}
        self.ignored_tests = {"branch/suite.test_b"}
        self.observed = dict(names=["suite.test_a", "suite.test_b"], errors=0, collection_only=True)
        self.commands = []
        self.image_name = "sha256"
        self.image_tag = "frozen"

    def _compile_executable(self, env, log_buf):
        self.result.executable_hash = "null-build-hash"
        self.commands.append("ordinary_compile")

    def _restore_executable(self, env, log_buf):
        self.commands.append("ordinary_restore_and_validate")

    def _run_step(self, command, **kwargs):
        self.commands.append(kwargs["step_name"])
        return {"output": "image-reference-hash  executable", "returncode": 0}

    def _run_test_branch(self, branch, image, log_buf):
        self._restore_executable(None, log_buf)
        return json.dumps(self.observed)

    def run(self):
        self._compile_executable(None, self.result.log)
        self._evaluate_branch("branch", "image")
        return self.result


class CollectionTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("procontract_evaluator_readiness.retain_image_reference", return_value="image-reference-hash")
        self.reference = patch.start()
        self.addCleanup(patch.stop)

    def test_reference_collection_keeps_build_and_reference_identities_separate(self):
        evaluator = collection_evaluator(Base)()
        result = evaluator.readiness()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["mode"], "reference_collection_only")
        self.assertEqual(result["compiled_executable_hash"], "null-build-hash")
        self.assertEqual(result["collection_reference_hash"], "image-reference-hash")
        self.reference.assert_called_once_with(None, "sha256:frozen", evaluator.result.log)
        self.assertEqual(evaluator.commands, ["ordinary_compile",
            "ordinary_restore_and_validate", "use_image_reference_only_for_collection"])
        self.assertNotIn("suite.test_a", json.dumps(result))
        self.assertFalse(hasattr(Base, "readiness"))

    def test_import_errors_duplicates_and_denominator_drift_are_not_readiness(self):
        for change in [dict(errors=1), dict(collection_only=False), dict(names=[]),
                       dict(names=["suite.test_a", "suite.test_a"]),
                       dict(names=["suite.test_a", "extra"]), dict(names=[1])]:
            with self.subTest(change=change):
                evaluator = collection_evaluator(Base)()
                evaluator.observed.update(change)
                with self.assertRaises(RuntimeError):
                    evaluator.readiness()

    def test_reference_swap_must_match_original_image_bytes(self):
        evaluator = collection_evaluator(Base)()
        evaluator.reference_hash = "changed"
        with self.assertRaisesRegex(RuntimeError, "reference changed"):
            evaluator._restore_executable(None, [])


if __name__ == "__main__":
    unittest.main()
