"""One bounded invocation with pipes or an explicit controlling terminal.

Usage: invocation.py INPUT_DIR OUTPUT_DIR TIMEOUT PROGRAM [ARG ...]
Only the target receives the case environment. Exit status, actual timeout and
exec failure are independent facts; a program may legitimately exit 124 or 137.
Adapter failures exit nonzero rather than manufacturing a completed observation.
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


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(source, output, seconds, program, args):
    path = source / "terminal.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"terminal": None, "piped_stdin": True}
    environment = dict(line.split("=", 1) for line in (source / "env").read_bytes().decode("utf-8").split("\n") if line)
    terminal = config["terminal"]
    streams = {name: (output / name).open("wb") for name in ["out", "err"]}
    readers, writers, child_fds = {}, {}, set()
    if terminal:
        master, slave = os.openpty()
        tty.setraw(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ,
                    struct.pack("HHHH", terminal["rows"], terminal["cols"], 0, 0))
        readers[master] = streams["out"]
        writers[master] = memoryview(terminal["input"].encode("utf-8"))
        child_in = child_out = child_err = slave
        child_fds.add(slave)
    else:
        out_read, child_out = os.pipe()
        err_read, child_err = os.pipe()
        readers.update({out_read: streams["out"], err_read: streams["err"]})
        child_fds.update([child_out, child_err])
    if config["piped_stdin"]:
        child_in, stdin_write = os.pipe()
        writers[stdin_write] = memoryview((source / "stdin").read_bytes())
        child_fds.add(child_in)
    start_read, start_write = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        try:
            os.close(start_read)
            for fd in set(readers) | set(writers):
                os.close(fd)
            for source_fd, target_fd in [(child_in, 0), (child_out, 1), (child_err, 2)]:
                os.dup2(source_fd, target_fd)
            os.setsid()
            if terminal:
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for fd in child_fds:
                if fd > 2:
                    os.close(fd)
            os.execve(program, [program, *args], environment)
        except BaseException as error:
            os.write(start_write, b"1")
            os.write(2, (str(error) + "\n").encode())
            os._exit(127)
    os.close(start_write)
    for fd in child_fds:
        os.close(fd)
    for fd in set(readers) | set(writers):
        os.set_blocking(fd, False)

    def close_writer(fd):
        writers.pop(fd, None)
        if fd not in readers:
            os.close(fd)

    for fd in list(writers):
        if not writers[fd]:
            close_writer(fd)
    deadline = time.monotonic() + seconds
    status = None
    timed_out = False
    try:
        while True:
            if status is None:
                exited, value = os.waitpid(pid, os.WNOHANG)
                if exited:
                    status = value
                    kill_group(pid)
                    for fd in list(writers):
                        close_writer(fd)
            if not readers and status is not None:
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            readable, writable, _ = select.select(
                list(readers), list(writers), [], min(0.05, max(0, deadline - time.monotonic())))
            for fd in writable:
                try:
                    writers[fd] = writers[fd][os.write(fd, writers[fd]):]
                    if not writers[fd]:
                        close_writer(fd)
                except BlockingIOError:
                    pass
                except OSError as error:
                    if error.errno not in (errno.EIO, errno.EPIPE):
                        raise
                    close_writer(fd)
            for fd in readable:
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    data = b""
                if data:
                    readers[fd].write(data)
                else:
                    if terminal and fd == master and status is None:
                        # PTY EIO can precede process exit (or a later /dev/tty reopen).
                        # Closing its master here would inject SIGHUP into a live target.
                        time.sleep(0.01)
                        continue
                    readers.pop(fd)
                    writers.pop(fd, None)
                    os.close(fd)
    finally:
        kill_group(pid)
        if status is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status = os.waitpid(pid, 0)
        for fd in set(readers) | set(writers):
            os.close(fd)
        for stream in streams.values():
            stream.close()
    exec_failed = bool(os.read(start_read, 1))
    os.close(start_read)
    code = os.waitstatus_to_exitcode(status)
    code = 128 - code if code < 0 else code
    for name, value in [("rc", code), ("timed_out", int(timed_out)), ("exec_failed", int(exec_failed))]:
        (output / name).write_text(str(value) + "\n")


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5:])
