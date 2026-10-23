"""Host-only collection qualification: fixed identities, explicit import failures."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from procontract_evaluator_readiness import COLLECTOR, collection_evaluator


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
    @unittest.skipUnless(importlib.util.find_spec('xdist'), 'requires pinned pytest/xdist wheels')
    def test_serial_readiness_keeps_worker_loadgroup_names_without_running_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'collection.json'
            (root/'pc_probe.py').write_text(COLLECTOR.replace('/tmp/procontract-collection.json',str(output)))
            (root/'conftest.py').write_text('''import pytest
def pytest_collection_modifyitems(items):
 for item in items:
  if item.name=='test_dynamic':item.add_marker(pytest.mark.xdist_group('late'))
''')
            (root/'test_sample.py').write_text('''import pytest
@pytest.mark.xdist_group('database')
@pytest.mark.xdist_group('database')
def test_grouped(): raise AssertionError('test body must not run')
@pytest.mark.xdist_group('z')
@pytest.mark.xdist_group(name='a')
def test_multiple(): raise AssertionError('test body must not run')
def test_plain(): raise AssertionError('test body must not run')
def test_dynamic(): raise AssertionError('test body must not run')
''')
            env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root)+os.pathsep+os.environ.get('PYTHONPATH','')}
            p=subprocess.run([sys.executable,'-m','pytest','-p','xdist.plugin','-p','pc_probe','-n','2','--dist=loadgroup','--collect-only','-q'],cwd=root,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            result=json.loads(output.read_text())
            self.assertEqual(set(result['names']),{'test_sample.test_grouped@database','test_sample.test_multiple@a_z','test_sample.test_plain','test_sample.test_dynamic'})
            self.assertTrue(result['collection_only']);self.assertEqual(result['errors'],0)

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
