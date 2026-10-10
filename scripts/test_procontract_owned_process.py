"""Owned Linux subprocess groups only; no native inference or shared-process signals."""

import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

import procontract_owned_process as owned


@unittest.skipUnless(sys.platform == "linux", "Linux waitid supervision")
class OwnedTests(unittest.TestCase):
    def test_success_reaps_leader_and_terminates_its_lingering_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "child.py"
            source.write_text(
                "import os,signal,time\npid=os.fork()\nif pid==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN)\n time.sleep(30)\nelse:\n print(pid,flush=True)\n"
            )
            log = root / "log"
            with log.open("w") as output:
                self.assertEqual(
                    owned.run([sys.executable, str(source)], stdout=output, timeout=3),
                    0,
                )
            pid = int(log.read_text())
            path = Path(f"/proc/{pid}/stat")
            until = time.monotonic() + 2
            while (
                path.exists()
                and path.read_text().rsplit(")", 1)[1].split()[0] != "Z"
                and time.monotonic() < until
            ):
                time.sleep(0.02)
            self.assertTrue(
                not path.exists()
                or path.read_text().rsplit(")", 1)[1].split()[0] == "Z"
            )

    def test_timeout_stops_the_owned_job(self):
        started = time.monotonic()
        with open(os.devnull, "w") as output:
            with self.assertRaises(TimeoutError):
                owned.run(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    stdout=output,
                    timeout=0.1,
                )
        self.assertLess(time.monotonic() - started, 3)

    def test_interrupt_during_cleanup_is_not_swallowed_as_success(self):
        actual = os.killpg

        def signal_group(pid, sig):
            if sig == signal.SIGTERM:
                signal.raise_signal(signal.SIGINT)
            actual(pid, sig)

        with (
            open(os.devnull, "w") as output,
            mock.patch.object(owned.os, "killpg", side_effect=signal_group),
        ):
            with self.assertRaises(KeyboardInterrupt):
                owned.run([sys.executable, "-c", "pass"], stdout=output, timeout=3)


if __name__ == "__main__":
    unittest.main()
