"""Real pytest controls for offline completion adapter repairs; no inference."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from procontract_evaluator_runtime import install_plugin_path
from procontract_evaluator_runtime import PLUGIN as RUNTIME
from procontract_evaluator_scope import PLUGIN as SCOPE
from procontract_evaluator_readiness import COLLECTOR


@unittest.skipUnless(importlib.util.find_spec('pytest'), 'requires pytest')
class CompletionControls(unittest.TestCase):
    def test_large_report_transport_keeps_the_failed_outcome_and_identity(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'runtime_probe.py').write_text(RUNTIME)
            (root/'test_case.py').write_text('def test_failure():\n    print("x"*4096)\n    assert False, "y"*4096\n')
            env={**os.environ,'PYTHONPATH':str(root),'PYTEST_PLUGINS':'runtime_probe',
                 'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PC_GRADER_REPORT_TEXT_CHARS':'64'}
            env.pop('PYTEST_ADDOPTS',None)
            p=subprocess.run([sys.executable,'-m','pytest','-q','-p','xdist.plugin','-n','2','--junitxml=result.xml'],
                cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            cases=ET.parse(root/'result.xml').findall('.//testcase')
            self.assertEqual(len(cases),1)
            self.assertEqual(cases[0].get('name'),'test_failure')
            self.assertIsNotNone(cases[0].find('failure'))
            self.assertIn('abbreviated for transport',cases[0].find('failure').text)

    def test_observer_import_survives_script_replacing_pythonpath(self):
        import pytest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'observer_probe.py').write_text('def pytest_configure(config): config._probe_loaded = True\n')
            (root/'test_probe.py').write_text('def test_loaded(pytestconfig): assert pytestconfig._probe_loaded\n')
            env = {**os.environ, 'PATH':str(Path(sys.executable).parent)+':'+os.environ['PATH']}
            def run(command, **kwargs):
                subprocess.run(shlex.split(command), check=True, capture_output=True, env=env)
            name = 'procontract-observer-'+hashlib.sha256(str(root).encode()).hexdigest()[:16]+'.pth'
            pth = Path(pytest.__file__).resolve().parent.parent/name
            try:
                install_plugin_path(run, None, [], str(root))
                env.update(PYTHONPATH=str(root/'unrelated'), PYTEST_PLUGINS='observer_probe', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
                env.pop('PYTEST_ADDOPTS', None)
                p = subprocess.run([sys.executable,'-m','pytest','-q',str(root/'test_probe.py')], env=env, cwd='/', capture_output=True, text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            finally:
                pth.unlink(missing_ok=True)

    def test_catalogue_excludes_extra_cases_without_hiding_declared_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plugins=root/'plugins';plugins.mkdir()
            (plugins/'scope_probe.py').write_text(SCOPE)
            (plugins/'scope.json').write_text(json.dumps({'ignored':[],'catalogue_exact':True,
                'eligible':['test_cases.test_good','test_cases.test_bad']}))
            (root/'test_cases.py').write_text('def test_good(): assert True\ndef test_bad(): assert False\ndef test_outside(): raise RuntimeError("outside")\n')
            (root/'test_unlisted.py').write_text('raise RuntimeError("unlisted import")\n')
            env={**os.environ,'PYTHONPATH':str(plugins),'PYTEST_PLUGINS':'scope_probe','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
            env.pop('PYTEST_ADDOPTS',None)
            p=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,1,p.stdout+p.stderr)
            self.assertIn('1 failed, 1 passed, 1 deselected',p.stdout)
            receipt=json.loads((plugins/'receipt.json').read_text())
            self.assertEqual(receipt['outside_catalogue'],['test_cases.test_outside'])
            self.assertEqual(receipt['outside_catalogue_modules'],['test_unlisted'])

    def test_multiple_pytest_invocations_retain_the_combined_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result=root/'collection.json'
            (root/'collector_probe.py').write_text(COLLECTOR.replace('/tmp/procontract-collection.json',str(result)))
            (root/'test_cases.py').write_text('def test_first(): assert False\ndef test_second(): assert False\n')
            env={**os.environ,'PYTHONPATH':str(root),'PYTEST_PLUGINS':'collector_probe','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'}
            env.pop('PYTEST_ADDOPTS',None)
            for name in ['first','second']:
                p=subprocess.run([sys.executable,'-m','pytest','-q','-k',name],cwd=root,env=env,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            x=json.loads(result.read_text())
            self.assertEqual(x['names'],['test_cases.test_first','test_cases.test_second'])
            self.assertEqual(x['errors'],0)


if __name__=='__main__':unittest.main()
