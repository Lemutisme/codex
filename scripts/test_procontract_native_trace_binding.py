"""Private evidence binding tests: no sudo, mount, model, Docker or network calls."""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import procontract_delivery_budget as delivery
import procontract_native_trace_binding as binding
import test_procontract_native_notice_receipt as reader_fixtures

FIXTURE = Path("/tmp/procontract-native-steer-trace-smoke-20261009/output/trace")


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.manifest = {
            "study": {
                "manifest_path": str(self.run.parent / "study.json"),
                "manifest_sha256": "a" * 64,
            },
            "study_version": "b" * 64,
            "codex_sha256": "c" * 64,
            "model": "gpt-5.6-luna",
            "effort": "max",
            "instructions": "executor.md",
            "instance": "synthetic",
        }
        self.terms = {
            "study": self.manifest["study"],
            "native_notice_trace": binding.PROFILE,
        }
        self.profile = mock.patch.object(
            binding.protocol,
            "campaign_profile",
            return_value=SimpleNamespace(protocol=binding.protocol.H_PROTOCOL),
        )
        self.profile.start()
        self.addCleanup(self.profile.stop)
        binding.prepare(self.run, self.manifest, self.terms)
        self.storage = {
            "mount_id": "4",
            "device": "0:100",
            "max_bytes": binding.PROFILE["max_bytes"],
            "max_inodes": binding.PROFILE["max_inodes"],
            "allocated_bytes": 0,
            "used_inodes": 1,
            "exhausted": False,
        }

    def test_descriptor_is_run_and_reader_bound(self):
        self.assertEqual(
            binding.descriptor(self.run, self.manifest)["trace_root"],
            str(self.run / binding.ROOT),
        )
        self.manifest["study_version"] = "d" * 64
        with self.assertRaisesRegex(RuntimeError, "descriptor changed"):
            binding.descriptor(self.run, self.manifest)

    def test_legacy_no_opt_in_creates_nothing(self):
        with tempfile.TemporaryDirectory() as other:
            binding.prepare(Path(other), {}, {})
            self.assertEqual(list(Path(other).iterdir()), [])
        self.assertIsNone(binding.provision(self.run, {}, {}))
        with self.assertRaisesRegex(RuntimeError, "unsealed"):
            binding.provision(self.run, self.manifest, {})

    def test_wrong_profile_never_mounts(self):
        with mock.patch.object(
            binding.protocol,
            "campaign_profile",
            return_value=SimpleNamespace(protocol="other"),
        ):
            with mock.patch.object(binding.subprocess, "run") as call:
                with self.assertRaisesRegex(RuntimeError, "unsupported"):
                    binding.provision(self.run, self.manifest, self.terms)
                call.assert_not_called()

    def test_provision_exact_command_and_error_receipt(self):
        with (
            mock.patch.object(binding, "_mounts", return_value=[]),
            mock.patch.object(
                binding.subprocess, "run", return_value=SimpleNamespace(returncode=1)
            ) as call,
        ):
            with self.assertRaisesRegex(RuntimeError, "no paid launch"):
                binding.provision(self.run, self.manifest, self.terms)
        args = call.call_args.args[0]
        self.assertEqual(args[:6], ["sudo", "-n", "mount", "-t", "tmpfs", "-o"])
        self.assertEqual(
            args[-2:], ["procontract-native-trace", str(self.run / binding.ROOT)]
        )
        self.assertEqual(
            json.loads((self.run / "native-trace-provision.json").read_text())[
                "mount_returncode"
            ],
            1,
        )

    def test_preexisting_mount_is_not_reused(self):
        existing = [("4", "0:100", "/", str(self.run / binding.ROOT), [], "tmpfs")]
        with (
            mock.patch.object(binding, "_mounts", return_value=existing),
            mock.patch.object(binding.subprocess, "run") as call,
        ):
            with self.assertRaisesRegex(RuntimeError, "fresh private"):
                binding.provision(self.run, self.manifest, self.terms)
            call.assert_not_called()

    def test_storage_rejects_shared_or_smaller_filesystem(self):
        root = str(self.run / binding.ROOT)
        entries = [("4", "0:100", "/", root, ["nosuid", "nodev", "noexec"], "tmpfs")]
        usage = SimpleNamespace(
            f_blocks=binding.PROFILE["max_bytes"] // 4096,
            f_frsize=4096,
            f_files=65536,
            f_bfree=1,
            f_ffree=1,
            f_bavail=1,
            f_favail=1,
        )
        with (
            mock.patch.object(binding, "_mounts", return_value=entries),
            mock.patch.object(binding.os, "statvfs", return_value=usage),
        ):
            self.assertEqual(binding.storage(self.run)["mount_id"], "4")
            entries.append(("5", "0:100", "/", "/different", [], "tmpfs"))
            with self.assertRaisesRegex(RuntimeError, "dedicated"):
                binding.storage(self.run)
            entries.pop()
            usage.f_blocks -= 1
            with self.assertRaisesRegex(RuntimeError, "limits differ"):
                binding.storage(self.run)

    def _observed(self, *, actual=False):
        root = self.run / binding.ROOT
        with mock.patch.object(binding, "storage", return_value=self.storage):
            observer = binding.Observer(self.run, self.manifest, latest_dispatch=1000)
        if actual:
            if not FIXTURE.is_dir():
                self.skipTest("local free native trace fixture unavailable")
            source = next(FIXTURE.iterdir())
            full = (source / "trace.jsonl").read_bytes()
            prefix = b"\n".join(full.splitlines()[:7]) + b"\n"
            notice = delivery.notice("checkpoint", 300)
        else:
            fixture = reader_fixtures.NativeNoticeReceiptTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            source = fixture.root
            prefix = (source / "trace.jsonl").read_bytes()
            full = "".join(
                json.dumps(event) + "\n" for event in fixture.events
            ).encode()
            notice = reader_fixtures.NOTICE
        bundle = root / source.name
        shutil.copytree(source, bundle)
        manifest = json.loads((bundle / "manifest.json").read_text())
        log = bundle / "trace.jsonl"
        events = [json.loads(line) for line in full.splitlines()]
        start = next(
            event for event in events if event["payload"]["type"] == "inference_started"
        )
        observer.thread_id = manifest["root_thread_id"]
        turn = start["codex_turn_id"]
        log.write_bytes(prefix)
        observer.before_send(
            {
                "id": 4,
                "method": "turn/steer",
                "params": {
                    "threadId": observer.thread_id,
                    "expectedTurnId": turn,
                    "input": [{"type": "text", "text": notice, "text_elements": []}],
                },
            }
        )
        log.write_bytes(full)
        with mock.patch.object(binding, "storage", return_value=self.storage):
            receipt = observer.after_run(
                {"attempt": {"outcome": "accepted", "turn_id": turn}},
                {"status": "exited"},
            )
        self.assertEqual(receipt["evidence"]["status"], "observed", receipt)
        return receipt, notice, turn

    def test_real_fixture_revalidates_and_changed_baseline_fails(self):
        receipt, notice, turn = self._observed()
        with mock.patch.object(binding, "storage", return_value=self.storage):
            self.assertEqual(
                binding.verify_notice(
                    self.run,
                    self.manifest,
                    notice=notice,
                    accepted_turn_id=turn,
                    receipt=receipt,
                ),
                receipt["evidence"],
            )
            baseline = self.run / "native-notice-baseline.json"
            baseline.write_bytes(baseline.read_bytes() + b" ")
            self.assertEqual(
                binding.verify_notice(
                    self.run,
                    self.manifest,
                    notice=notice,
                    accepted_turn_id=turn,
                    receipt=receipt,
                ),
                {"status": "unknown", "reason": "binding_verification_failed"},
            )

    def test_actual_native_free_fixture(self):
        self._observed(actual=True)

    def test_unknown_cannot_upgrade_on_later_replay(self):
        receipt, notice, turn = self._observed()
        receipt["evidence"] = {"status": "unknown", "reason": "earlier_failure"}
        with mock.patch.object(binding, "storage", return_value=self.storage):
            self.assertEqual(
                binding.verify_notice(
                    self.run,
                    self.manifest,
                    notice=notice,
                    accepted_turn_id=turn,
                    receipt=receipt,
                )["status"],
                "unknown",
            )

    def test_no_attempt_and_storage_exhaustion_remain_unknown(self):
        with mock.patch.object(binding, "storage", return_value=self.storage):
            observer = binding.Observer(self.run, self.manifest, latest_dispatch=1000)
            receipt = observer.after_run({"attempt": None}, {"status": "exited"})
            self.assertEqual(
                receipt["evidence"],
                {"status": "unknown", "reason": "no_steer_observed"},
            )
            self.assertEqual(
                binding.verify_notice(
                    self.run,
                    self.manifest,
                    notice=None,
                    accepted_turn_id=None,
                    receipt=receipt,
                ),
                receipt["evidence"],
            )
            self.storage["exhausted"] = True
            self.assertEqual(
                observer.after_run({"attempt": None}, {"status": "exited"})["evidence"][
                    "status"
                ],
                "unknown",
            )


if __name__ == "__main__":
    unittest.main()
