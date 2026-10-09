"""Linux-only real nested subprocess containment; no Docker, models or old PIDs."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import procontract_ph_supervisor as supervisor


@unittest.skipUnless(sys.platform == "linux", "Linux process-group containment")
class ShutdownTest(unittest.TestCase):
    def test_nonzero_and_interruption_kill_term_ignoring_grandchild(self):
        real_popen, real_waitid = subprocess.Popen, os.waitid
        real_killpg, real_sleep = os.killpg, time.sleep
        child = "import os,signal,sys,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
        for mode in ("nonzero", "wait_interrupt", "launch_interrupt"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                controller = supervisor.Supervisor(
                    argparse.Namespace(camp=root, study_sha256="a" * 64)
                )
                controller.root.mkdir()
                marker, processes, signals = root / "child.pid", [], []
                parent = (
                    f"import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,'-c',{child!r},sys.argv[1]]);\nwhile not Path(sys.argv[1]).exists(): time.sleep(.01)\n"
                    + ("sys.exit(7)" if mode == "nonzero" else "time.sleep(60)")
                )

                def launch(_command, **kwargs):
                    self.assertTrue(kwargs["start_new_session"])
                    process = real_popen(
                        [sys.executable, "-c", parent, str(marker)], **kwargs
                    )
                    processes.append(process)
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        real_sleep(0.01)
                    self.assertTrue(marker.exists())
                    if mode == "launch_interrupt":
                        controller.interrupted(signal.SIGTERM, None)
                    return process

                def waitid(*args):
                    if mode == "wait_interrupt":
                        controller.interrupted(signal.SIGTERM, None)
                    return real_waitid(*args)

                def killpg(pgid, sig):
                    self.assertEqual(pgid, processes[0].pid)
                    self.assertIsNone(processes[0].returncode)
                    self.assertEqual(os.getpgid(pgid), pgid)
                    signals.append(sig)
                    real_killpg(pgid, sig)

                def grace(_seconds):
                    if mode != "nonzero":
                        controller.interrupted(signal.SIGINT, None)
                    real_sleep(0.02)

                try:
                    with (
                        mock.patch.object(
                            supervisor.subprocess, "Popen", side_effect=launch
                        ),
                        mock.patch.object(supervisor.os, "waitid", side_effect=waitid),
                        mock.patch.object(supervisor.os, "killpg", side_effect=killpg),
                        mock.patch.object(supervisor.time, "sleep", side_effect=grace),
                    ):
                        with self.assertRaises((RuntimeError, InterruptedError)):
                            controller.command(1)
                    receipt = supervisor.document(
                        controller.root / "phase-1/group-cleanup.json"
                    )
                    self.assertEqual(
                        (signals, receipt["status"]),
                        (
                            [signal.SIGTERM, signal.SIGKILL],
                            "signals_requested_leader_reaped",
                        ),
                    )
                    child_stat = Path(f"/proc/{int(marker.read_text())}/stat")
                    for _ in range(100):
                        if not child_stat.exists() or child_stat.read_text().rsplit(
                            ")", 1
                        )[1].split()[0] in {"Z", "X"}:
                            break
                        real_sleep(0.01)
                    else:
                        self.fail("owned-group grandchild still running")
                finally:
                    for process in processes:
                        if process.returncode is None:
                            real_killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)

    def test_unsupported_host_and_unowned_handle_never_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = supervisor.Supervisor(argparse.Namespace(camp=Path(directory)))
            with (
                mock.patch.object(supervisor.sys, "platform", "win32"),
                mock.patch.object(supervisor.subprocess, "Popen") as launch,
            ):
                with self.assertRaisesRegex(RuntimeError, "requires Linux"):
                    controller.command(1)
                launch.assert_not_called()
            controller.active = mock.Mock(pid=os.getpid())
            with mock.patch.object(supervisor.os, "killpg") as kill:
                self.assertEqual(
                    controller.shutdown()["status"], "unverified_group_not_signalled"
                )
                kill.assert_not_called()
