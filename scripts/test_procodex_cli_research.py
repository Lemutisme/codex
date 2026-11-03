import unittest
from unittest.mock import patch
from pathlib import Path

import procodex


class ResearchEntryTest(unittest.TestCase):
    def test_explicit_research_cli_and_historical_entry_use_separate_drivers(self):
        with patch.object(procodex.subprocess,'call',return_value=0) as launch:
            self.assertEqual(procodex.main(['rsi','status','--config','/declared/profile.json']),0)
            command=launch.call_args.args[0]
            self.assertEqual(Path(command[1]).name,'procontract_research_control.py')
            self.assertEqual(command[2:],['status','--config','/declared/profile.json'])
            self.assertEqual(procodex.main(['rsi-legacy','--help']),0)
            self.assertEqual(Path(launch.call_args.args[0][1]).name,'procontract_rsi.py')

    def test_bare_research_cli_shows_help_without_admitting_work(self):
        with patch.object(procodex.subprocess,'call',return_value=0) as launch:
            procodex.main(['rsi'])
            self.assertEqual(launch.call_args.args[0][-1],'--help')


if __name__=='__main__':unittest.main()
