"""Real canonical identity gates and Host/store caches; no model or evaluator processes."""

import contextlib
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_canonical as canonical
import procontract_rsi as rsi
import procontract_store as store
import test_procontract_rsi as fixtures


class CanonicalHostTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patch = mock.patch.multiple(canonical, _REGISTRY=None, _EXPECTED_PINS=None)
        patch.start()
        self.addCleanup(patch.stop)
        self.task = "development__one.1234567"
        self.audit = ["audit__left.7654321", "audit__right.abcdef0"]
        self.registry_path = self.root / "registry.json"
        self.pins_path = self.root / "pins.json"
        self.source_path = Path(canonical.__file__).resolve()
        self.data = {
            "schema": 1,
            "tasks": {
                task: {"total": 3, "image": "sha256:" + "3" * 64}
                for task in [self.task, *self.audit]
            },
            "programbench": str(self.root / "pb"),
            "programbench_head": "1" * 40,
            "hf_revision": "2" * 40,
            "python": str(Path(sys.executable).resolve()),
            "wheelhouse": str(self.root / "wheels"),
            "blob_root": str(self.root / "blobs"),
            "blob_manifest": str(self.root / "blob-manifest.json"),
            "pins_file": str(self.pins_path),
        }
        canonical.write_json(self.registry_path, self.data)
        self.registry_sha = canonical.sha256(self.registry_path)
        self.adapter_sha = canonical.sha256(self.source_path)
        canonical.write_json(
            self.pins_path,
            {
                "registry_sha256": self.registry_sha,
                "adapter_sha256": self.adapter_sha,
            },
        )
        self.descriptor = {
            "registry_path": str(self.registry_path),
            "registry_sha256": self.registry_sha,
            "pins_sha256": canonical.sha256(self.pins_path),
            "adapter_sha256": self.adapter_sha,
        }
        (self.root / "codex").write_text("fixture binary, never executed")
        (self.root / "prompt.txt").write_text("Fixture task.")
        canonical.write_json(self.root / "pools.json", {"dev": [self.task]})
        canonical.write_json(self.root / "sealed.json", {"select": self.audit})
        self.host = self.make_host(self.root / "campaign")
        self.parent = self.host.incumbent()

    def args(self, camp):
        return [
            "rsi",
            "init",
            "--camp",
            str(camp),
            "--codex-bin",
            str(self.root / "codex"),
            "--task-prompt",
            str(self.root / "prompt.txt"),
            "--research-image",
            "fixture-image",
            "--programbench",
            self.data["programbench"],
            "--hf-revision",
            self.data["hf_revision"],
            "--pools",
            str(self.root / "pools.json"),
            "--sealed",
            str(self.root / "sealed.json"),
            "--dev",
            self.task,
            "--confirm-pool",
            "2",
            "--confirm-tasks",
            "2",
            "--confirm-min-wins",
            "2",
            "--parallel",
            "1",
        ]

    def make_host(self, camp):
        run = rsi.subprocess.run

        def pinned_head(command, **kwargs):
            if command == ["git", "-C", self.data["programbench"], "rev-parse", "HEAD"]:
                return rsi.subprocess.CompletedProcess(
                    command, 0, stdout=self.data["programbench_head"] + "\n"
                )
            return run(command, **kwargs)

        flags = [
            "--canonical-registry",
            str(self.registry_path),
            "--canonical-registry-sha256",
            self.registry_sha,
            "--canonical-pins-sha256",
            self.descriptor["pins_sha256"],
        ]
        with (
            mock.patch.object(sys, "argv", [*self.args(camp), *flags]),
            mock.patch.object(rsi.subprocess, "run", side_effect=pinned_head),
            mock.patch("sys.stdout"),
        ):
            rsi.main()
        return rsi.Host(camp)

    def cached(self, version, task, purpose="dev", resolved=1):
        """Make internally consistent fixed-case fixture receipts, retaining real hash checks."""
        parent = self.host.camp / "runs" / f"{purpose}-{version[:12]}-{task}"
        run = parent / "attempt-1"
        evaluation = run / "eval" / "attempt-1" / task
        evaluation.mkdir(parents=True)
        archive = run / "submission.tar.gz"
        archive.write_bytes(f"fixture {version}/{task}".encode())
        shutil.copyfile(archive, evaluation / "submission.tar.gz")
        claim, created = canonical.recovery.start(
            evaluation, canonical.attempt_binding(task, archive, 1)
        )
        self.assertTrue(created)
        canonical.recovery.enter_worker(evaluation, claim)
        raw = evaluation / f"{task}.eval.json"
        canonical.write_json(
            raw,
            {
                "test_results": [
                    {
                        "branch": "b",
                        "name": f"t{i}",
                        "status": "passed" if i < resolved else "failure",
                    }
                    for i in range(3)
                ]
            },
        )
        feedback = {
            f"b/t{i}": {"passed": i < resolved, "message": ""} for i in range(3)
        }
        canonical.write_json(evaluation / "canonical-feedback.json", feedback)
        canonical.write_json(run / "canonical-feedback.json", feedback)
        score = {
            "valid": True,
            "reasons": [],
            "task": task,
            "total": 3,
            "resolved": resolved,
            "pass_rate": resolved / 3,
            "eval_json": str(raw.resolve()),
            "eval_sha256": canonical.sha256(raw),
            "pins_sha256": self.descriptor["pins_sha256"],
        }
        canonical.write_json(evaluation / "canonical-score.json", score)
        canonical.recovery.finish(
            evaluation,
            claim,
            canonical.terminal_fields(evaluation, task, exit_code=0, elapsed=0),
        )
        outcome = {
            **score,
            "attempts": 1,
            "submission_sha256": canonical.sha256(archive),
            "feedback_json": str(evaluation / "canonical-feedback.json"),
        }
        canonical.write_json(run / "eval" / "canonical-result.json", outcome)
        canonical.write_json(run / "run.json", {"turn_statuses": ["completed"]})
        canonical.write_json(run / "manifest.json", {"instructions": "executor.md"})
        result = {
            "version": version,
            "task": task,
            "purpose": purpose,
            "run_dir": str(run),
            "validity": "valid",
            "pass_rate": resolved / 3,
            "label": self.host.adapter._label(task, outcome),
        }
        canonical.write_json(parent / "result.json", result)
        return result

    def candidate(self):
        bundle = self.root / "candidate"
        shutil.copytree(self.host.version_dir(self.parent) / "bundle", bundle)
        executor = bundle / "executor.md"
        executor.write_text(executor.read_text() + "\nA distinct fixture strategy.\n")
        return self.host.register(
            bundle, self.parent, self.parent, "Synthetic confirmation fixture."
        )

    @contextlib.contextmanager
    def drift(self, kind):
        if kind == "terms":
            before = copy.deepcopy(self.host.terms)
            self.host.terms["task_deadline_secs"] += 1
            try:
                yield
            finally:
                self.host.terms.clear()
                self.host.terms.update(before)
        elif kind == "adapter_source":
            path = self.root / "changed-adapter.py"
            path.write_bytes(self.source_path.read_bytes() + b"\n# drift fixture\n")
            with mock.patch.object(canonical, "__file__", str(path)):
                yield
        else:
            path = self.registry_path if kind == "registry" else self.pins_path
            before = path.read_bytes()
            path.write_bytes(before + b"\n")
            try:
                yield
            finally:
                path.write_bytes(before)

    def test_cli_persists_descriptor_and_factory_never_falls_back(self):
        terms = json.loads((self.host.camp / "campaign.json").read_text())
        self.assertEqual(terms["canonical"], self.descriptor)
        self.assertEqual(
            self.host.contract("campaign")["bindings"]["terms_hash"],
            store.digest("terms", terms),
        )
        with mock.patch.object(
            rsi, "ProgramBench", side_effect=AssertionError("legacy fallback")
        ):
            reopened = rsi.Host(self.host.camp)
            self.assertIsInstance(reopened.adapter, canonical.CanonicalProgramBench)
            self.assertEqual(reopened.adapter.terms, terms)
        with self.assertRaisesRegex(ValueError, "cannot fall back"):
            rsi.Host(self.host.camp, adapter=fixtures.FakeTasks())
        mismatched = canonical.CanonicalProgramBench({**terms, "effort": "low"})
        with self.assertRaisesRegex(ValueError, "does not match"):
            rsi.Host(self.host.camp, adapter=mismatched)

    def test_cli_requires_all_three_canonical_inputs_before_initialization(self):
        flags = [
            ("--canonical-registry", str(self.registry_path)),
            ("--canonical-registry-sha256", self.registry_sha),
            ("--canonical-pins-sha256", self.descriptor["pins_sha256"]),
        ]
        for mask in range(1, 7):
            with self.subTest(mask=mask):
                camp = self.root / f"partial-{mask}"
                extra = [
                    value
                    for i, flag in enumerate(flags)
                    if mask & (1 << i)
                    for value in flag
                ]
                with (
                    mock.patch.object(sys, "argv", [*self.args(camp), *extra]),
                    mock.patch.object(
                        rsi.subprocess,
                        "run",
                        side_effect=AssertionError("external initialization"),
                    ),
                    self.assertRaisesRegex(SystemExit, "require registry path"),
                ):
                    rsi.main()
                self.assertFalse((camp / "campaign.json").exists())
                self.assertFalse((camp / "store" / "ledger_1.sqlite").exists())

    def test_cached_reuse_invokes_the_real_canonical_binding_validator(self):
        result = self.cached(self.parent, self.task)
        with mock.patch.object(
            self.host.adapter, "run_and_label", side_effect=AssertionError("paid rerun")
        ):
            self.assertEqual(self.host.measure(self.parent, self.task, "dev"), result)
            before = store.events(self.host.store)
            changed = copy.deepcopy(result)
            changed["pass_rate"] = changed["label"]["outcome"]["pass_rate"] = 0.9
            canonical.write_json(
                Path(result["run_dir"]).parent / "result.json", changed
            )
            with self.assertRaisesRegex(RuntimeError, "cached canonical scalar"):
                self.host.measure(self.parent, self.task, "dev")
            self.assertEqual(store.events(self.host.store), before)

    def test_source_pins_and_frozen_terms_are_checked_before_cached_reuse(self):
        result = self.cached(self.parent, self.task)
        self.host.measure(self.parent, self.task, "dev")
        before = store.events(self.host.store)
        for kind in ("registry", "pins", "adapter_source", "terms"):
            with (
                self.subTest(kind=kind),
                self.drift(kind),
                mock.patch.object(
                    self.host.adapter,
                    "run_and_label",
                    side_effect=AssertionError("paid rerun"),
                ),
            ):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.host.measure(self.parent, self.task, "dev")
                self.assertEqual(store.events(self.host.store), before)
        self.assertEqual(self.host.measure(self.parent, self.task, "dev"), result)

    def test_drift_prevents_confirmation_before_reservation_or_execution(self):
        candidate = self.candidate()
        before = store.events(self.host.store)
        for kind in ("registry", "pins", "adapter_source", "terms"):
            with (
                self.subTest(kind=kind),
                self.drift(kind),
                mock.patch.object(
                    self.host.adapter,
                    "run_and_label",
                    side_effect=AssertionError("confirmation ran"),
                ),
            ):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.host.confirm(candidate, self.parent)
                self.assertEqual(
                    (
                        self.host.used_confirmation_tasks(),
                        store.events(self.host.store),
                    ),
                    ([], before),
                )

    def test_supported_adoption_rechecks_source_pins_and_frozen_terms(self):
        candidate = self.candidate()
        for task in self.host.terms["pools"]["confirm"]:
            self.cached(self.parent, task, "confirm", resolved=1)
            self.cached(candidate, task, "confirm", resolved=2)
        with mock.patch.object(
            self.host.adapter,
            "run_and_label",
            side_effect=AssertionError("uncached confirmation"),
        ):
            self.assertEqual(
                self.host.confirm(candidate, self.parent),
                "confirmed; awaiting the principal's adoption",
            )
        adoption = f"adoption.{candidate[:16]}"
        before = (
            self.host.incumbent(),
            self.host.contract(adoption),
            store.events(self.host.store),
        )
        for kind in ("registry", "pins", "adapter_source", "terms"):
            with self.subTest(kind=kind), self.drift(kind):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.host.adopt(candidate)
                self.assertEqual(
                    (
                        self.host.incumbent(),
                        self.host.contract(adoption),
                        store.events(self.host.store),
                    ),
                    before,
                )
        self.host.adopt(candidate)
        self.assertEqual(self.host.incumbent(), candidate)

    def test_reopening_rejects_changed_persisted_campaign_terms(self):
        path = self.host.camp / "campaign.json"
        changed = json.loads(path.read_text())
        changed["task_deadline_secs"] += 1
        canonical.write_json(path, changed)
        with self.assertRaisesRegex(RuntimeError, "campaign terms changed"):
            rsi.Host(self.host.camp)

    def test_generic_campaigns_keep_default_and_injected_adapters(self):
        root = self.root / "generic"
        root.mkdir()
        with mock.patch.object(
            canonical,
            "validate_identity",
            side_effect=AssertionError("canonical gate on generic campaign"),
        ):
            camp = fixtures.campaign(str(root))
            self.assertIsInstance(rsi.Host(camp).adapter, rsi.ProgramBench)
            tasks = fixtures.FakeTasks()
            host = fixtures.host(camp, tasks)
            result = host.measure(host.incumbent(), fixtures.DEV[0], "dev")
            self.assertEqual(
                (host.adapter is tasks, result["validity"], result["pass_rate"]),
                (True, "valid", 0.5),
            )


if __name__ == "__main__":
    unittest.main()
