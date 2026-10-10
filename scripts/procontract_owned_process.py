"""Linux owned-group lifetime: never reap a leader before signalling its group.

Covers inherited job groups, not escaped sessions or daemon-owned containers.
Research workers in the online pilot deliberately inherit this group.
"""

import os
import signal
import subprocess
import sys
import time


def run(command, *, stdout, timeout):
    if sys.platform != "linux" or not hasattr(os, "WNOWAIT"):
        raise RuntimeError("owned-group supervision requires Linux waitid")
    pending = []
    previous = {
        sig: signal.signal(sig, lambda number, _frame: pending.append(number))
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    process = None
    ended = None
    owned = False
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        owned = (
            process.pid not in (os.getpid(), os.getpgrp())
            and os.getpgid(process.pid) == os.getsid(process.pid) == process.pid
        )
        if not owned:
            raise RuntimeError("child process-group ownership unverified")
        deadline = time.monotonic() + timeout
        while True:
            if pending:
                raise KeyboardInterrupt(f"signal {pending[0]}; no restart")
            ended = os.waitid(
                os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
            )
            if ended is not None:
                return (
                    ended.si_status
                    if ended.si_code == os.CLD_EXITED
                    else -ended.si_status
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("episode deadline; no restart")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    finally:
        try:
            if process is not None and owned:
                # waitid(WNOWAIT) keeps this leader's PID reserved, including on
                # ordinary success. A leftover child cannot outlive the job.
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        pass
                    if sig == signal.SIGTERM:
                        # On interruption allow native worker cleanup to finish.
                        # Do not reap while waiting; new signals remain deferred.
                        until = time.monotonic() + (0.1 if ended else 45)
                        while time.monotonic() < until:
                            if (
                                os.waitid(
                                    os.P_PID,
                                    process.pid,
                                    os.WEXITED | os.WNOHANG | os.WNOWAIT,
                                )
                                is not None
                            ):
                                break
                            time.sleep(0.1)
                process.wait(timeout=5)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if pending:
                raise KeyboardInterrupt(f"signal {pending[0]}; no restart")
