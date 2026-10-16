"""Run one explicit PTY invocation. No shell parsing, terminal emulation or normalization.

Usage: terminal.py INPUT_DIR OUTPUT_DIR TIMEOUT PROGRAM [ARG ...]
The merged terminal byte stream is `out`; `err` is empty by definition. A process
exit is written to `rc`. Adapter failure exits nonzero without a synthetic receipt.
"""
import errno
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import struct
import sys
import termios
import time
import tty


def run(source, output, seconds, program, args):
    config = json.loads((source / "terminal.json").read_text())
    terminal = config["terminal"]
    master, slave = os.openpty()
    tty.setraw(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ,
                struct.pack("HHHH", terminal["rows"], terminal["cols"], 0, 0))
    pid = os.fork()
    if pid == 0:
        try:
            os.close(master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            if config["piped_stdin"]:
                with (source / "stdin").open("rb") as stream:
                    os.dup2(stream.fileno(), 0)
            os.execv(program, [program, *args])
        except BaseException as error:
            os.write(2, (str(error) + "\n").encode())
            os._exit(127)
    os.close(slave)
    os.set_blocking(master, False)
    pending = terminal["input"].encode("utf-8")
    deadline = time.monotonic() + seconds
    status = None
    eof = False
    timed_out = False
    try:
        (output / "err").write_bytes(b"")
        with (output / "out").open("wb") as stream:
            while True:
                if status is None:
                    exited, value = os.waitpid(pid, os.WNOHANG)
                    if exited:
                        status = value
                        # A completed leader cannot leave terminal-holding descendants behind.
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                if eof and status is not None:
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                readable, writable, _ = select.select(
                    [master] if not eof else [],
                    [master] if pending and status is None and not eof else [], [],
                    min(0.05, max(0, deadline - time.monotonic())),
                )
                if writable:
                    try:
                        pending = pending[os.write(master, pending):]
                    except BlockingIOError:
                        pass
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        pending = b""
                if readable:
                    try:
                        data = os.read(master, 65536)
                    except BlockingIOError:
                        continue
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        data = b""
                    if not data:
                        eof = True
                        continue
                    stream.write(data)
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Also kill the leader if setup failed before it established its process group.
        if status is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status = os.waitpid(pid, 0)
        os.close(master)
    code = os.waitstatus_to_exitcode(status)
    code = 128 - code if code < 0 else code
    (output / "rc").write_text(str(124 if timed_out else code) + "\n")


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5:])
