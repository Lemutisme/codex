"""Actual pytest collection/execution checks; no benchmark cases or model calls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from procontract_evaluator_scope import PLUGIN
from procontract_evaluator_scope import PLUGIN_NAME
from procontract_evaluator_scope import scoped_evaluator


@unittest.skipUnless(importlib.util.find_spec("pytest"), "requires pytest")
class PytestModuleScopeTest(unittest.TestCase):
    def test_only_official_archive_files_are_collected_even_from_workspace_root(self):
        for workers in (0, 2):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);plugins=root/'plugins';plugins.mkdir()
                (plugins/(PLUGIN_NAME+'.py')).write_text(PLUGIN)
                payload={'ignored':[], 'root':str(root), 'files':['eval/conftest.py','eval/test_official.py']}
                (plugins/'scope.json').write_text(json.dumps(payload))
                (root/'eval').mkdir();(root/'tests').mkdir()
                (root/'eval/conftest.py').write_text('import pytest\n@pytest.fixture\ndef official_fixture(): return 42\n')
                (root/'eval/test_official.py').write_text('def test_pass(official_fixture): assert official_fixture==42\ndef test_failure(): assert False\n')
                (root/'tests/test_candidate.py').write_text("from pathlib import Path\nPath('candidate-imported').touch()\ndef test_injected(): assert True\n")
                env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTEST_PLUGINS':PLUGIN_NAME,'PYTHONPATH':str(plugins)}
                env.pop('PYTEST_ADDOPTS',None)
                args=[sys.executable,'-m','pytest','-q','--junitxml',str(root/'results.xml')]
                if workers:args+=['-p','xdist.plugin','-n',str(workers)]
                result=subprocess.run(args,cwd=root,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertFalse((root/'candidate-imported').exists())
                cases=ET.parse(root/'results.xml').findall('.//testcase')
                self.assertEqual({c.get('name') for c in cases},{'test_pass','test_failure'})
                self.assertEqual(sum(c.find('failure') is not None for c in cases),1)

    def run_pytest(self, *, ignored, collect=False, prefix=None, workers=0, eligible=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        plugins = root / "plugins"
        plugins.mkdir()
        (plugins / (PLUGIN_NAME + ".py")).write_text(PLUGIN)
        payload = json.dumps({"ignored": ignored, "eligible":eligible or []}, sort_keys=True).encode()
        (plugins / "scope.json").write_bytes(payload)
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_unavailable.py").write_text(
            "from pathlib import Path\nPath('imported-marker').touch()\n"
            "import deliberately_absent_grader_dependency\n"
            "def test_hidden(): assert False\n"
        )
        (tests / "test_unavailable_extra.py").write_text("def test_real_failure(): assert False\n")
        (tests / "test_eligible.py").write_text("def test_pass(): assert True\n")
        env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": PLUGIN_NAME,
               "PYTHONPATH": str(plugins) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("PYTEST_ADDOPTS", None)
        args = [sys.executable, "-m", "pytest", "tests", "-q", "--rootdir", str(root),
                "--junitxml", str(root / "result.xml")]
        if collect:
            args.append("--collect-only")
        if prefix:
            args += ["--junit-prefix", prefix]
        if workers:
            args += ["-p", "xdist.plugin", "-n", str(workers)]
        result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, timeout=30)
        receipt = json.loads((plugins / "receipt.json").read_text())
        self.assertEqual(receipt["selectors_sha256"], hashlib.sha256(payload).hexdigest())
        return root, result, receipt

    def test_ignored_module_never_imports_in_collection_or_execution(self):
        for collect in (False, True):
            with self.subTest(collect=collect):
                root, result, receipt = self.run_pytest(ignored=["tests.test_unavailable"], collect=collect)
                self.assertEqual(result.returncode, 0 if collect else 1, result.stdout + result.stderr)
                self.assertFalse((root / "imported-marker").exists())
                self.assertEqual(receipt["excluded_modules"], ["tests.test_unavailable"])
                if not collect:
                    cases = ET.parse(root / "result.xml").findall(".//testcase")
                    self.assertEqual({c.get("name") for c in cases}, {"test_pass", "test_real_failure"})
                    self.assertEqual(sum(c.find("failure") is not None for c in cases), 1)

    def test_ignored_module_diagnostic_does_not_hide_explicitly_eligible_descendants(self):
        root,result,receipt=self.run_pytest(
            ignored=["tests.test_unavailable", "tests.test_eligible"],
            eligible=["tests.test_eligible.test_pass"])
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertEqual(receipt['excluded_modules'],['tests.test_unavailable'])
        cases=ET.parse(root/'result.xml').findall('.//testcase')
        self.assertEqual({c.get('name') for c in cases},{'test_pass','test_real_failure'})

    def test_leaf_exclusion_does_not_erase_its_module_or_an_unignored_import_error(self):
        root, result, receipt = self.run_pytest(ignored=["tests.test_unavailable.test_hidden"])
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((root / "imported-marker").exists())
        self.assertIn("deliberately_absent_grader_dependency", result.stdout)
        self.assertEqual(receipt["excluded_modules"], [])

    def test_junit_prefix_is_part_of_the_exact_module_identity(self):
        root, result, receipt = self.run_pytest(
            ignored=["qualified.tests.test_unavailable", "qualified.tests.test_eligible.test_pass"],
            prefix="qualified",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((root / "imported-marker").exists())
        self.assertEqual(receipt["excluded_modules"], ["qualified.tests.test_unavailable"])
        cases = ET.parse(root / "result.xml").findall(".//testcase")
        self.assertEqual({c.get("name") for c in cases}, {"test_pass", "test_real_failure"})

    @unittest.skipUnless(importlib.util.find_spec("xdist"), "requires pytest-xdist")
    def test_parallel_workers_preserve_the_same_scope_and_report_the_excluded_module(self):
        root, result, receipt = self.run_pytest(ignored=["tests.test_unavailable"], workers=2)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((root / "imported-marker").exists())
        self.assertEqual(receipt["excluded_modules"], ["tests.test_unavailable"])
        cases = ET.parse(root / "result.xml").findall(".//testcase")
        self.assertEqual({c.get("name") for c in cases}, {"test_pass", "test_real_failure"})


class EmptyEligibleScopeTest(unittest.TestCase):
    def test_fully_excluded_branch_does_not_require_its_unrelated_setup(self):
        class Base:
            tests_by_branch={'branch':['tests.unavailable']}
            ignored_tests={'branch/tests.unavailable'}
            def _run_test_branch(self,*args,**kwargs):
                raise AssertionError('excluded branch setup must not run')
        evaluator=scoped_evaluator(Base)()
        log=[]
        xml=evaluator._run_test_branch('branch','image',log)
        self.assertEqual(ET.fromstring(xml).findall('.//testcase'),[])
        self.assertEqual(log[0]['eligible_count'],0)

if __name__ == "__main__":
    unittest.main()
