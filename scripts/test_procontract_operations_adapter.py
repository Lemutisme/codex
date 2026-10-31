"""Scoped native cleanup controls for the real-model operations adapter."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from qualify_procontract_operations import build_identity, confirm_environment_shutdown, observe_build


class CleanupTest(unittest.TestCase):
    def run_cleanup(self, remaining):
        owned='a'*64;foreign='b'*64
        containers=[{'Id':owned,'Mounts':[{'Source':'/fixture/run/workspace'}]},
                    {'Id':foreign,'Mounts':[{'Source':'/another/invocation'}]}]
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=[owned+'\n'+foreign,json.dumps(containers),remaining]), \
             patch('qualify_procontract_operations.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','No such container')) as remove:
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
            self.assertEqual(remove.call_args.args[0],['docker','rm','-f',owned])
        return result

    def test_automatic_removal_race_is_confirmed_by_the_later_lifetime_observation(self):
        result=self.run_cleanup('b'*64+'\n')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['removal']['exit_code'],1)

    def test_a_failed_remove_does_not_claim_a_still_live_container_ended(self):
        self.assertFalse(self.run_cleanup('a'*64+'\n')['confirmed'])

    def test_unavailable_docker_observation_is_unknown(self):
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=OSError('daemon unavailable')):
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
        self.assertFalse(result['confirmed'])
        self.assertIn('daemon unavailable',result['error'])

    def test_version_includes_tool_host_and_changed_bytes_are_fenced_before_model_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            package=Path(temporary);(package/'bin').mkdir()
            (package/'bin/codex').write_text('native')
            host=package/'bin/codex-code-mode-host';host.write_text('tool host v1')
            original=build_identity(package)
            definition={'build':{'snapshot':original}}
            self.assertIn('bin/codex-code-mode-host',original['package_files'])
            self.assertIn('resolver',original['host_sources'])
            self.assertEqual(observe_build(package,definition),original)
            host.write_text('tool host v2')
            with self.assertRaisesRegex(ValueError,'differ'):
                observe_build(package,definition)
            self.assertNotEqual(observe_build(package,{'build':{}}),original)

    def test_build_identity_does_not_include_the_per_run_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            first=Path(temporary)/'first';second=Path(temporary)/'second'
            for root in (first,second):
                (root/'bin').mkdir(parents=True);(root/'bin/codex').write_text('same binary')
            self.assertEqual(build_identity(first),build_identity(second))


if __name__=='__main__':unittest.main()
