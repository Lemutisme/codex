"""Private bounded native request evidence for a new online pilot, not legacy study authority.

Reuses the strict native notice reader. ACK/activity alone never establish model
input consumption. Raw traces stay private and are never supplied to the learner.
"""

from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import time

import procontract_native_notice_receipt as reader
import procontract_native_trace_binding as trace
from procontract_online_plan import TRACE_PROFILE, PROTOCOL
from procontract_online_plan import publish
from procontract_online_plan import sha


class OnlineTrace(trace.Observer):
    def __init__(self, run, plan_sha256):
        self.run = Path(run).resolve()
        self.root = self.run / trace.ROOT
        self.root.mkdir(mode=0o700)
        options = f"size={trace.PROFILE['max_bytes']},nr_inodes={trace.PROFILE['max_inodes']},mode=0700,uid={os.geteuid()},gid={os.getegid()},nosuid,nodev,noexec"
        subprocess.run(
            [
                "sudo",
                "-n",
                "mount",
                "-t",
                "tmpfs",
                "-o",
                options,
                "procontract-online-trace",
                str(self.root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            check=True,
        )
        self.initial_storage = trace.storage(self.run, empty=True)
        # Provider response identifiers are opaque, unlike native UUIDs. This
        # future profile admits bounded 505-character proxy IDs; legacy readers
        # retain their original 128-character default and frozen verdicts.
        self.reader_limits = reader.Limits(max_response_id_chars=1024)
        self.bound = {
            "schema": 1,
            "protocol": PROTOCOL,
            "plan_sha256": plan_sha256,
            "run": str(self.run),
            "profile": TRACE_PROFILE,
            "reader_limits": asdict(self.reader_limits),
        }
        publish(self.run / "online-trace-descriptor.json", self.bound)
        self.manifest = {
            "native_notice_trace": {
                "sha256": sha(self.run / "online-trace-descriptor.json")
            }
        }
        self.latest_dispatch, self.dispatch_skipped = 0, False
        self.thread_id = self.reader = self.baseline = self.notice = None
        self.observer_secs = 0.0
        self.attempted = False
        self.baseline_sha256 = None
        self._closed = False

    def close(self):
        if self._closed:
            return
        # No native writer remains when called by the pilot. Preserve evidence
        # before releasing only this private, identity-checked mount.
        storage = trace.storage(self.run)
        if storage["mount_id"] != self.initial_storage["mount_id"]:
            raise RuntimeError("trace mount changed; refusing cleanup")
        archive = self.run / "private-native-trace.tar.gz"
        temporary = archive.with_suffix(".partial")
        started = time.monotonic()
        if archive.exists() or temporary.exists():
            raise RuntimeError(
                "trace archive already exists; preserve it for reconciliation"
            )
        # Archive failure retains the bounded private mount rather than destroying
        # the only raw evidence. The caller records failure and stops the pilot.
        subprocess.run(
            [
                "tar",
                "--one-file-system",
                "-czf",
                str(temporary),
                "-C",
                str(self.root),
                ".",
            ],
            check=True,
            timeout=60,
        )
        temporary.rename(archive)
        subprocess.run(
            ["sudo", "-n", "umount", str(self.root)],
            check=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._closed = True
        publish(
            self.run / "online-trace-cleanup.json",
            {
                "released_mount": storage["mount_id"],
                "archive": str(archive),
                "elapsed_secs": time.monotonic() - started,
                "raw_evidence_shared_with_learner": False,
            },
        )
