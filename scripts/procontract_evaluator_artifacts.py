"""Grader transport capabilities, separate from candidate behavior and test rules."""

import hashlib
import math
from pathlib import PurePosixPath
import subprocess
import tarfile
import tempfile
import threading
import time


def container_file_digest(env, path, *, timeout):
    """Hash one file through Docker's read-only archive API without chmod/extract.

    Candidate executability does not imply in-container readability. The trusted
    grader already owns file transport; no extra capability is given to candidate
    execution. The archive is streamed and never extracted on the host.
    """
    target = PurePosixPath(path)
    if not target.is_absolute():
        target = PurePosixPath(env.cwd) / target
    command = [env.executable, "cp", "-L", f"{env.container_id}:{target}", "-"]
    expired = threading.Event()
    with tempfile.TemporaryFile() as diagnostic:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=diagnostic)

        def stop():
            expired.set()
            child.kill()

        timer = threading.Timer(timeout, stop)
        timer.daemon = True
        timer.start()
        try:
            digest = hashlib.sha256()
            record = None
            with tarfile.open(fileobj=child.stdout, mode="r|") as archive:
                for member in archive:
                    if record is not None or not member.isfile():
                        raise RuntimeError("executable export must contain exactly one regular file")
                    size = 0
                    with archive.extractfile(member) as source:
                        while block := source.read(1024 * 1024):
                            digest.update(block)
                            size += len(block)
                    if size != member.size:
                        raise RuntimeError("incomplete executable export")
                    record = {"bytes": size, "mode": member.mode}
            # Drain tar padding before waiting; both reads share the same timer.
            while child.stdout.read(65536):
                pass
            code = child.wait()
            if expired.is_set():
                raise TimeoutError("executable archive read exceeded its original allowance")
            if code or record is None:
                diagnostic.seek(0)
                raise RuntimeError("executable export failed: " + diagnostic.read(4096).decode(errors="replace"))
            return {**record, "sha256": digest.hexdigest(), "target": str(target),
                    "transport": "read_only_docker_archive", "source_mode_changed": False}
        except BaseException as error:
            if expired.is_set() and not isinstance(error, TimeoutError):
                raise TimeoutError("executable archive read exceeded its original allowance") from error
            if isinstance(error, Exception) and not isinstance(error, TimeoutError):
                diagnostic.seek(0)
                detail = diagnostic.read(4096).decode(errors="replace")
                raise RuntimeError(f"executable export failed: {error}; {detail}") from error
            raise
        finally:
            timer.cancel()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            child.stdout.close()


def owned_keepalive_args(args, *, deadline, cleanup_seconds=60, now=None):
    """Bind only the evaluator's detached keeper to its owner's actual grant.

    Explicit command/suite timeouts still stop work. A missing deadline remains
    absent; the owner must clean up its container. The cleanup allowance keeps
    receipts readable after work cancellation, not an extra execution grant.
    """
    if not (args and args[0] in ("run", "create") and "--init" in args
            and ("-d" in args or "--detach" in args or args[0] == "create")
            and args[-2:] == ["sleep", "2h"]):
        return list(args)
    if deadline is None:
        duration = "infinity"
    else:
        now = time.time() if now is None else now
        if not math.isfinite(deadline) or deadline <= now:
            raise ValueError("grading owner allocation is expired or invalid")
        duration = str(math.ceil(deadline - now + cleanup_seconds)) + "s"
    return [*args[:-1], duration]
