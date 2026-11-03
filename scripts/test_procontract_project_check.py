import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import procontract_project_check as check


class ProjectCheckTest(unittest.TestCase):
    def assignment(self,root,deadline=None):
        project=root/'project';project.mkdir()
        return {'request':{'id':'same-local-name','inputs':{'seconds':None}},'admitted_at':time.time(),
            'deadline':deadline,'authority':'scope','measurement':{'identity':'fixed-check'},
            'runtime_project':{'path':str(project)},'runtime_inputs':{'command':['python3','-c','pass'],'image':'fixture'}}

    def test_cleanup_failure_retains_the_observed_command_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);assignment=self.assignment(root);path=root/'assignment.json';path.write_text(json.dumps(assignment))
            with patch.object(check.subprocess,'run',side_effect=[subprocess.CompletedProcess([],2),subprocess.TimeoutExpired(['docker','rm'],15)]):
                check.run(path)
            outcome=json.loads((root/'result.json').read_text())
            self.assertEqual(outcome['command_exit'],2)
            self.assertEqual(outcome['execution'],'completed')
            self.assertEqual(outcome['validity'],'valid')
            self.assertFalse(outcome['effects_resolved'])
            self.assertFalse(outcome['admissible'])

    def test_expired_allocation_does_not_start_a_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'assignment.json';path.write_text(json.dumps(self.assignment(root,time.time()-1)))
            with patch.object(check,'shutdown',return_value={'confirmed':True}),patch.object(check.subprocess,'run') as launch:
                check.run(path)
            launch.assert_not_called()
            outcome=json.loads((root/'result.json').read_text())
            self.assertEqual(outcome['execution'],'allocation_exhausted')
            self.assertIsNone(outcome['command_exit'])

    def test_daemon_identity_binds_assignment_not_local_operation_alias(self):
        first={'request':{'id':'run'},'admitted_at':10,'authority':'scope-one','measurement':{'identity':'same'}}
        second={**first,'authority':'scope-two'}
        self.assertNotEqual(check.container_name(first),check.container_name(second))
        self.assertEqual(check.container_name(first),check.container_name({**first,'runtime_project':{'path':'view'}}))


if __name__=='__main__':unittest.main()
