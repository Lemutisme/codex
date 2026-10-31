"""Scoped native cleanup controls for the real-model operations adapter."""
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from qualify_procontract_operations import confirm_environment_shutdown


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


if __name__=='__main__':unittest.main()
