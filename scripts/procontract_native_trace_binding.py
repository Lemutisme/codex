"""Sealed H-only native trace opt-in; private tmpfs bounds only trace-bundle storage.

Mounts are retained for explicit operator archival/cleanup. No raw trace is copied
into learner views. Reader outcomes attest transport evidence, not model behavior.
"""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import procontract_harness_program as harness
import procontract_native_notice_receipt as native
import procontract_ph_protocol as protocol

PROFILE = {
    "schema": 1,
    "profile": "private-tmpfs-native-notice-v1",
    "transport": "http",
    "max_bytes": 1 << 30,
    "max_inodes": 65536,
    "retention": "mounted_private_until_explicit_operator_archive_and_cleanup",
}
DESCRIPTOR = "native-trace-descriptor.json"
ROOT = "private-native-trace"
ENV = "CODEX_ROLLOUT_TRACE_ROOT"
IDENTITY = (
    "study",
    "study_version",
    "codex_sha256",
    "model",
    "effort",
    "instructions",
    "instance",
)


def _encoded(value):
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        + b"\n"
    )


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _expected(run, manifest):
    _require(run.is_absolute() and run.resolve() == run, "redirected native trace run")
    return {
        "schema": 1,
        "profile": PROFILE,
        "run_dir": str(run),
        "trace_root": str(run / ROOT),
        "identity": {key: manifest[key] for key in IDENTITY},
        "reader_sha256": hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
        "limits": asdict(native.Limits()),
        "uid": os.geteuid(),
        "gid": os.getegid(),
    }


def _selected(manifest, terms):
    camp = Path(manifest["study"]["manifest_path"]).parent
    selected = protocol.campaign_profile(camp, terms)
    _require(
        terms.get("native_notice_trace") == PROFILE
        and selected is not None
        and selected.protocol == protocol.H_PROTOCOL,
        "unsupported native trace profile",
    )


def prepare(run, manifest, terms):
    """Bind only a sealed future H profile; this does not provision or authorize inference."""
    selected = terms.get("native_notice_trace")
    if selected is None:
        return
    _selected(manifest, terms)
    _require(terms.get("study") == manifest.get("study"), "native trace study differs")
    root = run / ROOT
    root.mkdir(mode=0o700)
    raw = _encoded(_expected(run, manifest))
    with (run / DESCRIPTOR).open("xb") as output:
        os.chmod(output.fileno(), 0o600)
        output.write(raw)
    manifest["native_notice_trace"] = {
        "path": DESCRIPTOR,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def descriptor(run, manifest):
    value = manifest.get("native_notice_trace")
    if value is None:
        return None
    expected = _expected(run, manifest)
    raw = harness.read_regular(run / DESCRIPTOR, 32768)
    _require(
        raw == _encoded(expected)
        and value
        == {
            "path": DESCRIPTOR,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "native trace descriptor changed",
    )
    return expected


def _mounts():
    # Linux-only opt-in. Read a bounded proc snapshot, never a caller-provided mount command.
    with open("/proc/self/mountinfo", "rb") as stream:
        raw = stream.read((1 << 20) + 1)
    _require(len(raw) <= 1 << 20, "native trace mount table exceeds bound")
    result = []
    for line in raw.decode().splitlines():
        fields = line.split()
        split = fields.index("-")
        path = fields[4]
        for encoded, decoded in (
            ("\\040", " "),
            ("\\011", "\t"),
            ("\\012", "\n"),
            ("\\134", "\\"),
        ):
            path = path.replace(encoded, decoded)
        result.append(
            (
                fields[0],
                fields[2],
                fields[3],
                path,
                fields[5].split(","),
                fields[split + 1],
            )
        )
    return result


def storage(run, *, empty=False):
    root = run / ROOT
    info = root.lstat()
    _require(
        stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid()
        and root.resolve() == root,
        "native trace root must be a private owned real directory",
    )
    mounts = _mounts()
    chosen = [entry for entry in mounts if entry[3] == str(root)]
    _require(len(chosen) == 1, "native trace needs its dedicated mount")
    mount, device, source, _, options, filesystem = chosen[0]
    _require(
        source == "/"
        and filesystem == "tmpfs"
        and {"nosuid", "nodev", "noexec"} <= set(options)
        and sum(entry[1] == device for entry in mounts) == 1,
        "native trace mount is not a dedicated confined tmpfs",
    )
    usage = os.statvfs(root)
    total = usage.f_blocks * usage.f_frsize
    _require(
        total == PROFILE["max_bytes"] and usage.f_files == PROFILE["max_inodes"],
        "native trace storage limits differ",
    )
    if empty:
        _require(next(root.iterdir(), None) is None, "native trace root is not fresh")
    return {
        "mount_id": mount,
        "device": device,
        "max_bytes": total,
        "max_inodes": usage.f_files,
        "allocated_bytes": (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
        "used_inodes": usage.f_files - usage.f_ffree,
        "exhausted": usage.f_bavail == 0 or usage.f_favail == 0,
    }


def provision(run, manifest, terms):
    """Exact trusted mount before a paid reservation; no fallback, reuse or implicit cleanup."""
    selected = terms.get("native_notice_trace")
    if selected is None:
        _require("native_notice_trace" not in manifest, "unsealed native trace opt-in")
        return None
    _selected(manifest, terms)
    bound = descriptor(run, manifest)
    _require(bound is not None, "missing native trace descriptor")
    root = run / ROOT
    info = root.lstat()
    _require(
        stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid()
        and root.resolve() == root
        and next(root.iterdir(), None) is None
        and not any(entry[3] == str(root) for entry in _mounts()),
        "native trace provisioning requires a fresh private unmounted path",
    )
    options = (
        f"size={PROFILE['max_bytes']},nr_inodes={PROFILE['max_inodes']},"
        f"mode=0700,uid={os.geteuid()},gid={os.getegid()},nosuid,nodev,noexec"
    )
    started = time.monotonic()
    error = None
    try:
        completed = subprocess.run(
            [
                "sudo",
                "-n",
                "mount",
                "-t",
                "tmpfs",
                "-o",
                options,
                "procontract-native-trace",
                str(root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        returncode = completed.returncode
    except (OSError, subprocess.TimeoutExpired) as failure:
        returncode, error = None, type(failure).__name__
    receipt = {
        "descriptor_sha256": manifest["native_notice_trace"]["sha256"],
        "mount_returncode": returncode,
        "error": error,
        "elapsed_secs": round(time.monotonic() - started, 3),
        "trace_root": str(root),
    }
    with (run / "native-trace-provision.json").open("xb") as output:
        output.write(_encoded(receipt))
    _require(returncode == 0, "native trace mount failed; no paid launch")
    return {
        "descriptor_sha256": receipt["descriptor_sha256"],
        "storage": storage(run, empty=True),
    }


class Observer:
    """At most one baseline, followed by a compact private after-close receipt."""

    def __init__(self, run, manifest, *, latest_dispatch):
        self.run, self.manifest = run, manifest
        self.latest_dispatch, self.dispatch_skipped = latest_dispatch, False
        self.bound = descriptor(run, manifest)
        _require(self.bound is not None, "missing native trace descriptor")
        self.initial_storage = storage(run, empty=True)
        self.thread_id = None
        self.reader = self.baseline = self.notice = None
        self.observer_secs = 0.0
        self.attempted = False
        self.baseline_sha256 = None

    def before_send(self, message):
        started = time.monotonic()
        try:
            _require(not self.attempted, "repeated notice observation")
            self.attempted = True
            params = message["params"]
            _require(
                params["threadId"] == self.thread_id, "notice belongs to another root"
            )
            self.notice = params["input"][0]["text"]
            self.reader = native.Reader(
                self.run / ROOT,
                thread_id=self.thread_id,
                turn_id=params["expectedTurnId"],
            )
            self.baseline = self.reader.before_steer(self.notice)
        except Exception:
            self.baseline = {"status": "unknown", "reason": "baseline_observer_failed"}
        finally:
            value = {
                "schema": 1,
                "descriptor_sha256": self.manifest["native_notice_trace"]["sha256"],
                "thread_id": self.thread_id,
                "turn_id": self.reader.turn_id if self.reader else None,
                "baseline": asdict(self.baseline)
                if isinstance(self.baseline, native.Baseline)
                else self.baseline,
            }
            try:
                raw = _encoded(value)
                with (self.run / "native-notice-baseline.json").open("xb") as output:
                    os.chmod(output.fileno(), 0o600)
                    output.write(raw)
                self.baseline_sha256 = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError):
                self.baseline = {
                    "status": "unknown",
                    "reason": "baseline_persistence_failed",
                }
            self.observer_secs += time.monotonic() - started

    def after_run(self, delivery, closed):
        started = time.monotonic()
        result = {
            "status": "unknown",
            "reason": "baseline_observer_failed"
            if self.attempted
            else "no_steer_observed",
        }
        try:
            final_storage = storage(self.run)
            _require(
                not final_storage["exhausted"]
                and all(
                    final_storage[key] == self.initial_storage[key]
                    for key in ("mount_id", "device", "max_bytes", "max_inodes")
                ),
                "trace storage changed or exhausted",
            )
            _require(
                isinstance(closed, dict) and closed.get("status") == "exited",
                "native exit unknown",
            )
            _require(not self.dispatch_skipped, "dispatch window exhausted")
            if self.reader is not None:
                attempt = delivery.get("attempt") or {}
                result = self.reader.after_run(
                    self.baseline,
                    notice=self.notice,
                    accepted_turn_id=(
                        attempt.get("turn_id")
                        if attempt.get("outcome") == "accepted"
                        else None
                    ),
                )
        except Exception:
            result = {
                "status": "unknown",
                "reason": "dispatch_window_exhausted"
                if self.dispatch_skipped
                else "final_observer_failed",
            }
            final_storage = None
        self.observer_secs += time.monotonic() - started
        return {
            "schema": 1,
            "descriptor_sha256": self.manifest["native_notice_trace"]["sha256"],
            "baseline_sha256": self.baseline_sha256,
            "dispatch_skipped": self.dispatch_skipped,
            "evidence": result,
            "storage": final_storage,
            "observer_secs": round(self.observer_secs, 6),
            "retained_private_root": str(self.run / ROOT),
        }


def verify_notice(run, manifest, *, notice, accepted_turn_id, receipt):
    """Recheck persisted private evidence; never trust the summary's positive label alone."""
    try:
        bound = descriptor(run, manifest)
        _require(
            bound is not None
            and type(receipt["schema"]) is int
            and receipt["schema"] == 1
            and receipt["dispatch_skipped"] is False
            and receipt["descriptor_sha256"]
            == manifest["native_notice_trace"]["sha256"],
            "notice descriptor differs",
        )
        current = storage(run)
        _require(
            not current["exhausted"]
            and all(
                current[key] == receipt["storage"][key]
                for key in ("mount_id", "device", "max_bytes", "max_inodes")
            ),
            "notice storage changed",
        )
        path = run / "native-notice-baseline.json"
        if (
            notice is None
            and accepted_turn_id is None
            and receipt["baseline_sha256"] is None
            and receipt["dispatch_skipped"] is False
            and receipt["evidence"]
            == {"status": "unknown", "reason": "no_steer_observed"}
            and not path.exists()
            and not path.is_symlink()
        ):
            return receipt["evidence"]
        raw = harness.read_regular(path, 32768)
        _require(
            raw is not None
            and hashlib.sha256(raw).hexdigest() == receipt["baseline_sha256"],
            "notice baseline changed",
        )
        value = json.loads(raw)
        _require(
            raw == _encoded(value)
            and value["schema"] == 1
            and value["descriptor_sha256"] == receipt["descriptor_sha256"],
            "notice baseline differs",
        )
        baseline = value["baseline"]
        if isinstance(baseline, dict) and "status" not in baseline:
            baseline = native.Baseline(**baseline)
        reader = native.Reader(
            run / ROOT, thread_id=value["thread_id"], turn_id=value["turn_id"]
        )
        observed = reader.after_run(
            baseline, notice=notice, accepted_turn_id=accepted_turn_id
        )
        _require(observed == receipt["evidence"], "notice evidence changed")
        return observed
    except Exception:
        return {"status": "unknown", "reason": "binding_verification_failed"}
