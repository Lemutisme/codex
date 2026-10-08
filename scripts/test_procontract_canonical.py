"""Offline adapter boundary tests; no ProgramBench tasks, Docker or models execute."""

import dataclasses
import io
import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import procontract_canonical as canonical


@dataclasses.dataclass
class Validation:
    valid: bool = True
    utility: Fraction = Fraction(1, 3)
    resolved: int = 1
    total: int = 3
    reasons: tuple = ()


class CanonicalTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patch = mock.patch.object(canonical, "_REGISTRY", None)
        patch.start()
        self.addCleanup(patch.stop)
        self.task = "fresh__demo.1234567"
        self.registry_file = self.root / "registry.json"
        self.data = {
            "schema": 1,
            "tasks": {self.task: {"total": 3, "image": "sha256:" + "3" * 64}},
            "programbench": str(self.root / "pb"),
            "programbench_head": "1" * 40,
            "hf_revision": "2" * 40,
            "python": str(Path(sys.executable).resolve()),
            "wheelhouse": str(self.root / "wheels"),
            "blob_root": str(self.root / "blobs"),
            "blob_manifest": str(self.root / "blob-manifest.json"),
            "pins_file": str(self.root / "pins.json"),
        }
        canonical.write_json(self.registry_file, self.data)
        self.registry = canonical.configure(
            self.registry_file, canonical.sha256(self.registry_file)
        )
        self.pins = {
            "registry_sha256": self.registry.digest,
            "adapter_sha256": canonical.sha256(canonical.__file__),
        }
        canonical.write_json(self.registry.pins_file, self.pins)
        self.terms = {
            key: self.data[key]
            for key in ("programbench", "programbench_head", "hf_revision")
        }
        self.terms.update(
            codex_sha256="4" * 64,
            stream={"order": [self.task]},
            pools={"dev": [], "confirm": []},
            canonical={
                "registry_path": str(self.registry_file),
                "registry_sha256": self.registry.digest,
                "pins_sha256": canonical.sha256(self.registry.pins_file),
                "adapter_sha256": self.pins["adapter_sha256"],
            },
        )

    def test_static_factory_identity_and_single_registry_binding(self):
        with mock.patch.object(
            canonical.subprocess, "run", side_effect=AssertionError("external call")
        ):
            adapter = canonical.CanonicalProgramBench(self.terms)
            self.assertEqual(
                adapter.environment()["cleanrooms"],
                {self.task: self.data["tasks"][self.task]["image"]},
            )
            self.assertEqual(
                adapter.evaluator()["registry_sha256"], self.registry.digest
            )
            other = self.root / "other.json"
            other.write_bytes(self.registry_file.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "cannot switch"):
                canonical.configure(other, self.registry.digest)
            self.registry_file.write_text(self.registry_file.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "identity changed"):
                adapter.evaluator()

    def test_pins_and_adapter_drift_are_rejected_without_external_calls(self):
        for key in ("pins_sha256", "adapter_sha256"):
            terms = {
                **self.terms,
                "canonical": {**self.terms["canonical"], key: "0" * 64},
            }
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(RuntimeError, "identity changed"),
            ):
                canonical.validate_identity(terms)
        canonical.write_json(self.registry.pins_file, {})
        with self.assertRaisesRegex(RuntimeError, "do not bind"):
            canonical.checked_pins()

    def test_cli_accepts_fresh_task_and_rejects_unregistered_legacy_task(self):
        argv = [
            "canonical",
            "preflight",
            "--registry",
            str(self.registry_file),
            "--registry-sha256",
            self.registry.digest,
            "--task",
            self.task,
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch.object(
                canonical, "preflight", return_value={"valid": True}
            ) as preflight,
        ):
            canonical.main()
            preflight.assert_called_once_with()
        argv[-1] = "antonmedv__fx.86d0d34"
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit),
        ):
            canonical.main()

    def test_child_rejects_registry_drift_before_preflight(self):
        command = canonical.worker_command("preflight")
        self.registry_file.write_text(self.registry_file.read_text() + " ")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("registry identity changed", result.stderr)

    def test_preflight_evaluate_and_score_commands_carry_the_frozen_registry(self):
        for operation in ("preflight", "evaluate-one", "score"):
            command = canonical.worker_command(operation, "--task", self.task)
            self.assertEqual(
                command[2:],
                [
                    operation,
                    "--registry",
                    str(self.registry_file),
                    "--registry-sha256",
                    self.registry.digest,
                    "--task",
                    self.task,
                ],
            )
        output = self.root / "score.json"
        canonical.write_json(output, {"valid": True})
        with mock.patch.object(canonical.subprocess, "run") as run:
            canonical.canonical_score_subprocess(
                self.task, self.root / "eval.json", output
            )
        self.assertEqual(
            run.call_args.args[0],
            canonical.worker_command(
                "score",
                "--task",
                self.task,
                "--eval-json",
                self.root / "eval.json",
                "--output",
                output,
            ),
        )

    def test_scoring_preserves_skips_last_outcome_and_validator_failures(self):
        raw = self.root / "eval.json"
        canonical.write_json(
            raw,
            {
                "test_results": [
                    {"branch": "b", "name": name, "status": status}
                    for name, status in [
                        ("a", "passed"),
                        ("b", "passed"),
                        ("b", "failure"),
                        ("c", "skipped"),
                    ]
                ]
            },
        )
        output = self.root / "score.json"
        validator = mock.Mock(return_value=Validation())
        with (
            mock.patch.object(canonical, "preflight"),
            mock.patch.object(canonical, "fixture", return_value={}),
            mock.patch.object(
                canonical,
                "pb_imports",
                return_value=(None, None, lambda _: ["b"], lambda _: set(), validator),
            ),
        ):
            score = canonical.canonical_score(self.task, raw, output)
            self.assertEqual(
                (score["valid"], score["total"], score["pass_rate"]), (True, 3, 1 / 3)
            )
            feedback = json.loads((self.root / "canonical-feedback.json").read_text())
            self.assertEqual(
                {name: row["passed"] for name, row in feedback.items()},
                {"b/a": True, "b/b": False, "b/c": False},
            )
            for invalid in (
                Validation(valid=False, reasons=("branch_error:b",)),
                Validation(total=2),
            ):
                validator.return_value = invalid
                score = canonical.canonical_score(self.task, raw, output)
                self.assertEqual((score["valid"], score["pass_rate"]), (False, None))
                self.assertEqual(
                    json.loads((self.root / "canonical-feedback.json").read_text()), {}
                )

    def evaluate(self, work, valid_attempts):
        archive = self.root / (work.name + ".tar.gz")
        archive.write_bytes(b"frozen submission")
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            raw = Path(command[command.index("--eval-json") + 1])
            canonical.write_json(raw, {"synthetic": True})
            valid = valid_attempts[len(calls) - 1]
            canonical.write_json(
                raw.with_name("canonical-score.json"),
                {
                    "valid": valid,
                    "pass_rate": 1 / 3,
                    "resolved": 1,
                    "total": 3,
                    "task": self.task,
                    "reasons": [] if valid else ["branch_error:b"],
                    "eval_json": str(raw.resolve()),
                    "eval_sha256": canonical.sha256(raw),
                    "pins_sha256": canonical.sha256(self.registry.pins_file),
                },
            )
            canonical.write_json(
                raw.with_name("canonical-feedback.json"),
                {
                    "b/a": {"passed": True},
                    "b/b": {"passed": False},
                    "b/c": {"passed": False},
                },
            )
            return SimpleNamespace(returncode=0)

        def score(task, raw, output):
            return json.loads(output.read_text())

        with (
            mock.patch.object(canonical.subprocess, "run", side_effect=run),
            mock.patch.object(
                canonical, "canonical_score_subprocess", side_effect=score
            ),
        ):
            if any(valid_attempts):
                outcome = canonical.evaluate_archive(self.task, archive, work)
                self.assertEqual(outcome["attempts"], valid_attempts.index(True) + 1)
            else:
                with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
                    canonical.evaluate_archive(self.task, archive, work)
        self.assertEqual(
            len(calls), valid_attempts.index(True) + 1 if any(valid_attempts) else 2
        )
        for command in calls:
            self.assertEqual(
                command[command.index("--registry-sha256") + 1], self.registry.digest
            )
            self.assertEqual(
                canonical.sha256(Path(command[command.index("--archive") + 1])),
                canonical.sha256(archive),
            )
        return archive

    def test_evaluation_keeps_one_or_two_same_subject_attempts(self):
        for index, outcomes in enumerate(([True], [False, True], [False, False])):
            with self.subTest(outcomes=outcomes):
                self.evaluate(self.root / str(index), outcomes)

    def test_bound_result_revalidates_without_another_evaluation(self):
        work = self.root / "resume"
        archive = self.evaluate(work, [True])
        score_file = work / "attempt-1" / self.task / "canonical-score.json"
        with (
            mock.patch.object(
                canonical.subprocess, "run", side_effect=AssertionError("rerun")
            ),
            mock.patch.object(
                canonical,
                "canonical_score_subprocess",
                return_value=json.loads(score_file.read_text()),
            ) as score,
        ):
            outcome = canonical.evaluate_archive(self.task, archive, work)
        self.assertEqual(
            (outcome["attempts"], outcome["submission_sha256"]),
            (1, canonical.sha256(archive)),
        )
        score.assert_called_once_with(
            self.task, score_file.with_name(f"{self.task}.eval.json"), score_file
        )

    def test_legacy_or_changed_receipts_cannot_relabel_cached_scores(self):
        for mutation in ("legacy", "archive", "raw"):
            with self.subTest(mutation=mutation):
                work = self.root / mutation
                archive = self.evaluate(work, [True])
                directory = work / "attempt-1" / self.task
                receipt = directory / "evaluation-receipt.json"
                if mutation == "legacy":
                    body = json.loads(receipt.read_text())
                    del body["raw_eval_sha256"]
                    canonical.write_json(receipt, body)
                elif mutation == "archive":
                    archive.write_bytes(b"different submission")
                    (directory / "submission.tar.gz").write_bytes(archive.read_bytes())
                else:
                    canonical.write_json(
                        directory / f"{self.task}.eval.json", {"substituted": True}
                    )
                with (
                    mock.patch.object(
                        canonical.subprocess, "run", side_effect=AssertionError("rerun")
                    ),
                    self.assertRaisesRegex(RuntimeError, "unbound or changed"),
                ):
                    canonical.evaluate_archive(self.task, archive, work)

    def cached_result(self, name):
        run_dir = self.root / name
        archive = self.evaluate(run_dir / "eval", [True])
        archive.rename(run_dir / "submission.tar.gz")
        outcome = json.loads((run_dir / "eval" / "canonical-result.json").read_text())
        (run_dir / "canonical-feedback.json").write_bytes(
            Path(outcome["feedback_json"]).read_bytes()
        )
        adapter = canonical.CanonicalProgramBench(self.terms)
        label = {
            "task": self.task,
            "evaluator_epoch": canonical.packaging.epoch(adapter.evaluator()),
            "validity": "valid",
            "reason": "",
            "attempts": 1,
            "outcome": {"pass_rate": 1 / 3, "passed": 1, "counted": 3},
            "canonical": outcome,
        }
        return adapter, {
            "validity": "valid",
            "task": self.task,
            "pass_rate": 1 / 3,
            "run_dir": str(run_dir),
            "label": label,
        }

    def test_cached_scalar_epoch_and_bound_evidence_are_checked_without_processes(self):
        for mutation in (
            None,
            "scalar",
            "epoch",
            "task",
            "canonical",
            "score",
            "raw",
            "feedback",
        ):
            with self.subTest(mutation=mutation):
                adapter, result = self.cached_result(str(mutation))
                run_dir = Path(result["run_dir"])
                if mutation == "scalar":
                    result["pass_rate"] = result["label"]["outcome"]["pass_rate"] = 0.9
                elif mutation == "epoch":
                    result["label"]["evaluator_epoch"] = "0" * 64
                elif mutation == "task":
                    result["task"] = "other__task.7654321"
                elif mutation == "canonical":
                    outcome = result["label"]["canonical"]
                    canonical.write_json(
                        run_dir / "eval" / "canonical-result.json",
                        {**outcome, "pass_rate": 0.9},
                    )
                elif mutation == "score":
                    canonical.write_json(
                        Path(result["label"]["canonical"]["eval_json"]).with_name(
                            "canonical-score.json"
                        ),
                        {},
                    )
                elif mutation == "raw":
                    Path(result["label"]["canonical"]["eval_json"]).write_text("{}")
                elif mutation == "feedback":
                    (run_dir / "canonical-feedback.json").write_text("{}")
                with mock.patch.object(
                    canonical.subprocess,
                    "run",
                    side_effect=AssertionError("external process"),
                ):
                    if mutation is None:
                        adapter.validate_cached(result)
                    else:
                        with self.assertRaises(RuntimeError):
                            adapter.validate_cached(result)

    def test_existing_adapter_rechecks_pins_for_every_cached_access(self):
        adapter, result = self.cached_result("pins")
        adapter.validate_cached(result)
        canonical.write_json(self.registry.pins_file, {**self.pins, "changed": True})
        with (
            mock.patch.object(
                canonical.subprocess,
                "run",
                side_effect=AssertionError("external process"),
            ),
            self.assertRaisesRegex(RuntimeError, "identity changed"),
        ):
            adapter.validate_cached(result)


if __name__ == "__main__":
    unittest.main()
