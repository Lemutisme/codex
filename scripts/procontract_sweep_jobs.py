"""Concurrent owned-group supervision. Never reap a PID before signalling its group."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class Job:
    def __init__(self, command, log, seconds):
        if sys.platform != "linux" or not hasattr(os, "WNOWAIT"):
            raise RuntimeError("owned sweep jobs require Linux waitid")
        self.closed = False
        self.started = time.monotonic()
        self.log = Path(log).open("x")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.pid = self.process.pid
        if (
            self.pid in (os.getpid(), os.getpgrp())
            or os.getpgid(self.pid) != self.pid
            or os.getsid(self.pid) != self.pid
        ):
            raise RuntimeError("unverified episode process-group ownership")
        self.deadline = time.monotonic() + seconds

    def status(self):
        if self.closed:
            return self.process.returncode
        ended = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if ended is None:
            return None
        return ended.si_status if ended.si_code == os.CLD_EXITED else -ended.si_status

    def signal(self, value):
        if self.closed:
            return
        try:
            os.killpg(self.pid, value)
        except ProcessLookupError:
            pass

    def close(self):
        if self.closed:
            return
        self.signal(signal.SIGKILL)
        self.process.wait(timeout=5)
        self.log.close()
        self.closed = True


def cancel_all(jobs):
    for job in jobs:
        job.signal(signal.SIGTERM)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and any(job.status() is None for job in jobs):
        time.sleep(0.2)
    for job in jobs:
        job.close()


def cleanup_containers(study, episode):
    command = [
        "/usr/bin/docker",
        "ps",
        "-aq",
        "--filter",
        f"label=procodex.study={study}",
        "--filter",
        f"label=procodex.episode={episode}",
    ]
    ids = subprocess.check_output(command, text=True, timeout=30).split()
    if ids:
        objects = json.loads(
            subprocess.check_output(
                ["/usr/bin/docker", "inspect", *ids], text=True, timeout=30
            )
        )
        if any(
            o["Config"]["Labels"].get("procodex.study") != study
            or o["Config"]["Labels"].get("procodex.episode") != episode
            for o in objects
        ):
            raise RuntimeError("container ownership changed; cleanup refused")
        subprocess.run(
            ["/usr/bin/docker", "rm", "-f", *ids],
            stdout=subprocess.DEVNULL,
            check=True,
            timeout=45,
        )
    remaining = subprocess.check_output(command, text=True, timeout=30).split()
    if remaining:
        raise RuntimeError("owned containers remain after cleanup")
    return {"removed_owned_container_ids": ids, "remaining_owned_containers": remaining}
