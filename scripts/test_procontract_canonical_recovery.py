"""Offline crash and resource-admission controls; evaluators are deterministic doubles."""

import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import procontract_canonical as canonical
import test_procontract_canonical as fixtures


class RecoveryTest(unittest.TestCase):
    setUp = fixtures.CanonicalTest.setUp

    def input_archive(self):
        archive = self.root / "submission.tar.gz"
        archive.write_bytes(b"frozen source")
        return archive, self.root / "eval"

    def complete(self, task, archive, raw):
        canonical.write_json(raw, {"synthetic": True})
        score = {
            "valid": True,
            "pass_rate": 1 / 3,
            "resolved": 1,
            "total": 3,
            "task": task,
            "reasons": [],
            "eval_json": str(raw.resolve()),
            "eval_sha256": canonical.sha256(raw),
            "pins_sha256": canonical.sha256(self.registry.pins_file),
        }
        canonical.write_json(raw.with_name("canonical-score.json"), score)
        canonical.write_json(
            raw.with_name("canonical-feedback.json"), {"synthetic": True}
        )
        return score

    def recheck(self, task, raw, output):
        value = json.loads(raw.with_name("canonical-score.json").read_text())
        canonical.write_json(output, value)
        shutil.copyfile(
            raw.with_name("canonical-feedback.json"),
            output.with_name("canonical-feedback.json"),
        )
        return value

    def interrupted(self):
        archive, work = self.input_archive()
        with (
            mock.patch.object(
                canonical.subprocess, "run", side_effect=InterruptedError("parent died")
            ),
            self.assertRaises(InterruptedError),
        ):
            canonical.evaluate_archive(self.task, archive, work)
        return archive, work, work / "attempt-1" / self.task

    def test_unknown_launch_never_relaunches_or_spends_second_attempt(self):
        archive, work, directory = self.interrupted()
        claim = (directory / canonical.recovery.CLAIM).read_bytes()
        for _ in range(2):
            with (
                mock.patch.object(
                    canonical.subprocess,
                    "run",
                    side_effect=AssertionError("repurchase"),
                ),
                self.assertRaisesRegex(RuntimeError, "unresolved"),
            ):
                canonical.evaluate_archive(self.task, archive, work)
        self.assertEqual((directory / canonical.recovery.CLAIM).read_bytes(), claim)
        self.assertFalse((work / "attempt-2").exists())

    def test_late_worker_terminal_resumes_without_rewriting_bound_evidence(self):
        archive, work, directory = self.interrupted()
        raw = directory / f"{self.task}.eval.json"
        with mock.patch.object(
            canonical, "evaluate_one", side_effect=self.complete
        ) as evaluator:
            canonical.evaluate_claimed(self.task, directory / "submission.tar.gz", raw)
        evaluator.assert_called_once()
        protected = {
            path: path.read_bytes() for path in directory.iterdir() if path.is_file()
        }
        with (
            mock.patch.object(
                canonical.subprocess, "run", side_effect=AssertionError("repurchase")
            ),
            mock.patch.object(
                canonical, "canonical_score_subprocess", side_effect=self.recheck
            ),
        ):
            result = canonical.evaluate_archive(self.task, archive, work)
        self.assertEqual(result["attempts"], 1)
        self.assertEqual({path: path.read_bytes() for path in protected}, protected)
        self.assertFalse((work / "attempt-2").exists())

    def test_known_failed_terminal_allows_only_the_same_subject_second_attempt(self):
        archive, work, first = self.interrupted()
        with (
            mock.patch.object(
                canonical, "evaluate_one", side_effect=RuntimeError("infra")
            ),
            self.assertRaisesRegex(RuntimeError, "infra"),
        ):
            canonical.evaluate_claimed(
                self.task, first / "submission.tar.gz", first / f"{self.task}.eval.json"
            )
        previous = (first / canonical.recovery.TERMINAL).read_bytes()

        def launch(command, **kwargs):
            source = Path(command[command.index("--archive") + 1])
            raw = Path(command[command.index("--eval-json") + 1])
            canonical.evaluate_claimed(self.task, source, raw)
            return SimpleNamespace(returncode=0)

        with (
            mock.patch.object(
                canonical.subprocess, "run", side_effect=launch
            ) as launched,
            mock.patch.object(canonical, "evaluate_one", side_effect=self.complete),
            mock.patch.object(
                canonical, "canonical_score_subprocess", side_effect=self.recheck
            ),
        ):
            result = canonical.evaluate_archive(self.task, archive, work)
            canonical.evaluate_archive(self.task, archive, work)
        self.assertEqual((result["attempts"], launched.call_count), (2, 1))
        self.assertEqual((first / canonical.recovery.TERMINAL).read_bytes(), previous)
        self.assertEqual(
            (work / "attempt-2" / self.task / "submission.tar.gz").read_bytes(),
            archive.read_bytes(),
        )

    def test_worker_entry_is_one_shot_even_without_terminal_receipt(self):
        _, _, directory = self.interrupted()
        args = (
            self.task,
            directory / "submission.tar.gz",
            directory / f"{self.task}.eval.json",
        )
        with (
            mock.patch.object(canonical, "evaluate_one", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            canonical.evaluate_claimed(*args)
        with (
            mock.patch.object(
                canonical,
                "evaluate_one",
                side_effect=AssertionError("duplicate worker"),
            ),
            self.assertRaisesRegex(RuntimeError, "already entered"),
        ):
            canonical.evaluate_claimed(*args)
        self.assertFalse((directory / canonical.recovery.TERMINAL).exists())

    def test_atomic_packaging_keeps_partial_output_out_of_final_path(self):
        run = self.root / "run"
        (run / "workspace").mkdir(parents=True)

        def failed(source, target):
            target.write_bytes(b"partial tar")
            raise OSError("interrupted tar")

        with (
            mock.patch.object(canonical.packaging, "package", side_effect=failed),
            self.assertRaises(OSError),
        ):
            canonical.package_submission(run)
        self.assertFalse((run / "submission.tar.gz").exists())
        with mock.patch.object(
            canonical.packaging,
            "package",
            side_effect=lambda source, target: target.write_bytes(b"complete"),
        ) as package:
            first = canonical.package_submission(run)
            self.assertEqual(canonical.package_submission(run), first)
        self.assertEqual((first.read_bytes(), package.call_count), (b"complete", 1))
        first.write_bytes(b"partial legacy tar")
        with self.assertRaisesRegex(RuntimeError, "partial or unbound"):
            canonical.package_submission(run)

    def test_child_pin_fence_rejects_whitespace_drift_before_external_preflight(self):
        command = canonical.worker_command("preflight")
        self.registry.pins_file.write_text(self.registry.pins_file.read_text() + " ")
        result = canonical.subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pins identity changed", result.stderr)

    def test_required_offline_blobs_cannot_be_omitted_or_escape_the_root(self):
        tasks = self.root / "tasks"
        (tasks / self.task).mkdir(parents=True)
        self.registry.programbench.mkdir()
        (self.registry.programbench / "uv.lock").write_text("lock")
        self.registry.wheelhouse.mkdir()
        (self.registry.wheelhouse / "wheel.whl").write_bytes(b"wheel")
        blob = self.registry.blob_root / self.task / "tests" / "b.tar.gz"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"tests")
        required = f"{self.task}/tests/b.tar.gz"
        instance = {
            "instance_id": self.task,
            "branches": {"b": {"tests": ["a", "b", "c"]}},
        }

        def inspect(command, **kwargs):
            return (
                self.data["programbench_head"]
                if command[0] == "git"
                else self.data["tasks"][self.task]["image"]
            )

        with (
            mock.patch.object(
                canonical,
                "pb_imports",
                return_value=(
                    tasks,
                    lambda: [instance],
                    lambda _: ["b"],
                    lambda _: set(),
                    None,
                ),
            ),
            mock.patch.object(
                canonical.subprocess, "check_output", side_effect=inspect
            ),
            mock.patch.object(canonical.subprocess, "run"),
        ):
            for entries in (
                {},
                {required: canonical.sha256(blob), "/outside": "0" * 64},
                {required: canonical.sha256(blob), f"{self.task}/../escape": "0" * 64},
            ):
                canonical.write_json(
                    self.registry.blob_manifest,
                    {
                        "commit": self.registry.hf_revision,
                        "blob_root": str(self.registry.blob_root),
                        "blob_sha256": entries,
                    },
                )
                with self.assertRaises(RuntimeError):
                    canonical.pin_state()
            canonical.write_json(
                self.registry.blob_manifest,
                {
                    "commit": self.registry.hf_revision,
                    "blob_root": str(self.registry.blob_root),
                    "blob_sha256": {required: canonical.sha256(blob)},
                },
            )
            self.assertEqual(
                canonical.pin_state()["blob_sha256"], {required: canonical.sha256(blob)}
            )
            target = self.root / "outside.tar.gz"
            blob.rename(target)
            blob.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                canonical.pin_state()


if __name__ == "__main__":
    unittest.main()
