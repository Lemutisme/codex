"""Settled state migration through the real Host/CLI/store; no models or containers."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock

import procontract_canonical as canonical
import procontract_checkpoint as checkpoints
import procontract_comparison as comparison
import procontract_rsi as rsi
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_canonical_host as canonical_fixtures
from test_procontract_checkpoint import make_checkpoint, reseal
from test_procontract_study import StudyFixture


class CheckpointHostTest(unittest.TestCase):
    args = canonical_fixtures.CanonicalHostTest.args
    make_host = canonical_fixtures.CanonicalHostTest.make_host

    def setUp(self):
        canonical_fixtures.CanonicalHostTest.setUp(self)
        self.default = self.host
        bundle = self.root / "settled-bundle"
        shutil.copytree(rsi.V0_BUNDLE, bundle)
        (bundle / "analyst.md").write_text("Settled inherited analyst method.\n")
        self.artifact = self.root / "checkpoint"
        self.pin = make_checkpoint(
            self.artifact,
            native_sha256=canonical.sha256(self.root / "codex"),
            bundle=bundle,
        )
        self.checkpoint = checkpoints.load(self.artifact, self.pin)
        self.data.update(
            exposure_scope="prospective_lineage",
            exposed_tasks=list(self.checkpoint.excluded_tasks),
            operator_exposed_tasks=list(self.checkpoint.operator_exposed_tasks),
        )
        self.instances = self.root / "instances.txt"
        self.instances.write_text(self.task + "\n")
        self.limits = {
            "task_launches": 6,
            "learning_launches": 8,
            "allocated_seconds": 180000,
        }
        self.repin()

    def repin(self):
        canonical.write_json(self.registry_path, self.data)
        self.registry_sha = canonical.sha256(self.registry_path)
        canonical.write_json(
            self.pins_path,
            {"registry_sha256": self.registry_sha, "adapter_sha256": self.adapter_sha},
        )
        self.descriptor["pins_sha256"] = canonical.sha256(self.pins_path)
        canonical._REGISTRY = None
        canonical._EXPECTED_PINS = None

    def initialize(self, name="migrated", *, artifact=None, extra=(), sealed=False):
        camp = self.root / name
        flags = [
            "--instances",
            str(self.instances),
            "--batch",
            "1",
            "--stream-mode",
            "guarded",
            "--release-every",
            "1",
            "--confirmation-exposure-scope",
            "prospective_lineage",
            "--checkpoint",
            str(artifact or self.artifact),
            "--checkpoint-sha256",
            self.pin,
            "--canonical-registry",
            str(self.registry_path),
            "--canonical-registry-sha256",
            self.registry_sha,
            "--canonical-pins-sha256",
            self.descriptor["pins_sha256"],
            *extra,
        ]
        if sealed:
            flags.extend(
                [
                    "--research-image",
                    "sha256:" + "a" * 64,
                    "--study-task-launches",
                    "6",
                    "--study-learning-launches",
                    "8",
                    "--study-allocated-secs",
                    "180000",
                ]
            )
        real_run = rsi.subprocess.run

        def pinned_head(command, **kwargs):
            if command == ["git", "-C", self.data["programbench"], "rev-parse", "HEAD"]:
                return rsi.subprocess.CompletedProcess(
                    command, 0, stdout=self.data["programbench_head"] + "\n"
                )
            return real_run(command, **kwargs)

        with (
            mock.patch.object(sys, "argv", [*self.args(camp), *flags]),
            mock.patch.object(rsi.subprocess, "run", side_effect=pinned_head),
            mock.patch("sys.stdout"),
        ):
            rsi.main()
        return rsi.Host(camp)

    def test_real_bootstrap_rebases_only_settled_bundle_and_inherits_qualified_views(
        self,
    ):
        source_knowledge = self.checkpoint.knowledge / "mechanisms.md"
        source_knowledge.chmod(0o555)
        self.checkpoint.knowledge.chmod(0o555)
        self.pin = reseal(self.artifact)
        self.checkpoint = checkpoints.load(self.artifact, self.pin)
        host = self.initialize()
        root = host.incumbent()
        source = self.checkpoint.origin["source_version"]
        self.assertNotEqual(root, source)
        self.assertEqual(list(host.versions()), [root])
        self.assertEqual(
            host.versions()[root]["lineage"],
            {"parent": None, "proposed_by": "operator"},
        )
        self.assertEqual(
            [
                e["body"]
                for e in host.events("selection")
                if e["body"]["role"] == "checkpoint_bootstrap"
            ],
            [
                {
                    "role": "checkpoint_bootstrap",
                    "origin": self.checkpoint.origin,
                    "version": root,
                }
            ],
        )
        adoption = host.contract(f"adoption.{root[:16]}")
        self.assertEqual(
            (
                adoption["standing"],
                adoption["settlement"]["decision"],
                adoption["support"]["coordinate"]["reach"],
            ),
            ("discharged", {"type": "explicit"}, "within"),
        )
        self.assertEqual(
            rsi.bundle_texts(host.version_dir(root) / "bundle"),
            rsi.bundle_texts(self.checkpoint.bundle),
        )
        self.assertEqual(
            rsi.knowledge_identity(host.current_knowledge()),
            self.checkpoint.origin["knowledge_digest"],
        )
        self.assertEqual(source_knowledge.stat().st_mode & 0o777, 0o555)
        self.assertEqual(
            (host.current_knowledge() / "mechanisms.md").stat().st_mode & 0o777, 0o755
        )
        self.assertEqual(host.current_knowledge().stat().st_mode & 0o777, 0o755)
        self.assertEqual(
            (host.used_confirmation_tasks(), host.confirm_budget_left()), ([], 2)
        )
        inherited = host.events("exposure")[0]["body"]
        self.assertEqual(inherited["sources"], list(self.checkpoint.excluded_tasks))
        self.assertEqual(
            inherited["operator_exposed_tasks"],
            list(self.checkpoint.operator_exposed_tasks),
        )
        token = next(iter(host.adapter.task_tokens(self.checkpoint.excluded_tasks[0])))
        self.assertIn(
            "exposed task", host.boundary({"executor.md": token}, ["executor.md"])
        )
        view = host.stage_research(root, 1) / "workspace"
        archive = view / "archive"
        self.assertEqual(
            (view / "policy/analyst.md").read_bytes(),
            (self.checkpoint.bundle / "analyst.md").read_bytes(),
        )
        self.assertEqual(
            rsi.knowledge_identity(archive / "knowledge"),
            self.checkpoint.origin["knowledge_digest"],
        )
        self.assertEqual(
            (archive / "method-trials/inherited-method-trial.json").read_bytes(),
            self.checkpoint.feedback_files[0].read_bytes(),
        )
        origin = json.loads(
            (archive / "method-trials/checkpoint-origin.json").read_text()
        )
        self.assertEqual(
            (
                origin["source_method"],
                origin["bootstrap_root"],
                origin["new_promotion"],
            ),
            (source, root, False),
        )
        self.assertFalse(
            any(
                path.name
                in {"operator-metadata", "evidence", "provenance", "MANIFEST.json"}
                for path in view.rglob("*")
            )
        )

    def test_checkpoint_is_pinned_before_seal_and_new_study_budget_starts_at_zero(self):
        paths = {p.absolute() for p in study.SCRIPTS.glob("*.py")} | {
            p for p in self.artifact.rglob("*") if p.is_file()
        }
        real_freeze = study.freeze

        def freeze(camp, terms, limits):
            self.assertEqual(
                terms["checkpoint"],
                {"path": str(self.artifact), **self.checkpoint.descriptor()},
            )
            return real_freeze(camp, terms, limits)

        with (
            mock.patch.object(study, "mandatory_paths", return_value=paths),
            mock.patch.object(study, "freeze", side_effect=freeze),
        ):
            host = self.initialize(sealed=True)
            receipt = budget.status(
                host.camp / "study-budget.sqlite",
                host.terms["study"]["manifest_sha256"],
                self.limits,
            )
            self.assertEqual(receipt["reserved"], dict.fromkeys(self.limits, 0))
            self.assertEqual(study.verify(host.camp, host.terms)["limits"], self.limits)

    def test_partial_pin_and_raw_knowledge_are_rejected_before_campaign_creation(self):
        raw = self.root / "raw-knowledge"
        raw.mkdir()
        for flags in (
            ["--checkpoint", str(self.artifact)],
            ["--checkpoint-sha256", self.pin],
            ["--instances", str(self.instances), "--knowledge", str(raw)],
        ):
            with (
                mock.patch.object(sys, "argv", [*self.args(self.root / "bad"), *flags]),
                self.assertRaises(SystemExit),
            ):
                rsi.main()
            self.assertFalse((self.root / "bad/campaign.json").exists())
        with self.assertRaisesRegex(SystemExit, "cannot be combined"):
            self.initialize(extra=["--knowledge", str(raw)])

    def test_new_confirmation_cannot_reuse_old_repository_or_omit_exposure(self):
        old = self.checkpoint.excluded_tasks[0]
        related = old.rsplit(".", 1)[0] + ".abcdef0"
        for task in (old, related):
            self.data["tasks"][task] = {"total": 3, "image": "sha256:" + "3" * 64}
            canonical.write_json(
                self.root / "sealed.json", {"select": [task, self.audit[0]]}
            )
            self.repin()
            with self.assertRaisesRegex(ValueError, "overlap"):
                self.initialize()
        canonical.write_json(self.root / "sealed.json", {"select": self.audit})
        for field in ("exposed_tasks", "operator_exposed_tasks"):
            original = self.data[field]
            self.data[field] = original[1:]
            self.repin()
            with self.assertRaisesRegex(ValueError, "omits"):
                self.initialize()
            self.data[field] = original

    def test_profile_pin_source_and_copied_knowledge_drift_fail_closed(self):
        wrong_binary = self.root / "other-codex"
        wrong_binary.write_text("another native build")
        for flags in (
            ["--model", "gpt-6-astra"],
            ["--effort", "high"],
            ["--codex-bin", str(wrong_binary)],
            ["--checkpoint-sha256", "0" * 64],
        ):
            with self.assertRaises(ValueError):
                self.initialize(extra=flags)
        host = self.initialize()
        copied = next(p for p in host.current_knowledge().rglob("*") if p.is_file())
        copied.write_text("tampered knowledge")
        with self.assertRaisesRegex(ValueError, "knowledge seed changed"):
            host.stage_research(host.incumbent(), 1)
        source = self.checkpoint.feedback_files[0]
        source.write_text(source.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "payload content differs"):
            rsi.Host(host.camp)

    def test_strict_scope_also_excludes_disclosed_operator_only_repositories(self):
        operator = next(
            t
            for t in self.checkpoint.operator_exposed_tasks
            if t not in self.checkpoint.excluded_tasks
        )
        self.data["tasks"][operator] = {"total": 3, "image": "sha256:" + "3" * 64}
        canonical.write_json(
            self.root / "sealed.json", {"select": [operator, self.audit[0]]}
        )
        self.repin()
        host = self.initialize("prospective")
        self.assertIn(operator, host.terms["pools"]["confirm"])
        self.data["exposure_scope"] = "strict"
        self.repin()
        with self.assertRaisesRegex(ValueError, "known-exposed repository"):
            self.initialize("strict", extra=["--confirmation-exposure-scope", "strict"])

    def test_comparison_uses_seed_contents_and_origin_not_artifact_location(self):
        stream = self.initialize()
        copied = self.root / "relocated-checkpoint"
        shutil.copytree(self.artifact, copied)
        baseline = self.initialize("baseline", artifact=copied)
        comparison.validate_comparison(stream, baseline)
        baseline.terms["checkpoint"]["source_study_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checkpoint seed"):
            comparison.validate_comparison(stream, baseline)
        baseline.terms["checkpoint"] = stream.terms["checkpoint"]
        (baseline.current_knowledge() / "additional.md").write_text("different seed")
        with self.assertRaisesRegex(ValueError, "knowledge seeds"):
            comparison.validate_comparison(stream, baseline)
        (stream.current_knowledge() / "additional.md").write_text("different seed")
        with self.assertRaisesRegex(ValueError, "from checkpoint"):
            comparison.validate_comparison(stream, baseline)
        for host in (stream, baseline):
            shutil.rmtree(host.camp / "knowledge-seed")
        with self.assertRaisesRegex(ValueError, "from checkpoint"):
            comparison.validate_comparison(stream, baseline)

    def test_default_bootstrap_still_uses_shipped_bundle_without_checkpoint(self):
        root = self.default.incumbent()
        self.assertEqual(
            rsi.bundle_texts(self.default.version_dir(root) / "bundle"),
            rsi.bundle_texts(rsi.V0_BUNDLE),
        )
        self.assertNotIn("checkpoint", self.default.terms)
        self.assertIsNone(self.default.current_knowledge())
        self.assertEqual(
            [
                e
                for e in self.default.events("selection")
                if e["body"]["role"] == "checkpoint_bootstrap"
            ],
            [],
        )


class CheckpointStudyInventoryTest(StudyFixture):
    def setUp(self):
        binary = os.environ["PRO_CONTRACT_STORE_BIN"]
        super().setUp()
        self.enterContext(
            mock.patch.dict(os.environ, {"PRO_CONTRACT_STORE_BIN": binary})
        )

    def test_entire_checkpoint_is_mandatory_and_drift_is_rejected(self):
        artifact = self.root / "checkpoint"
        pin = make_checkpoint(
            artifact,
            native_sha256=hashlib.sha256(
                (self.root / "bin/codex").read_bytes()
            ).hexdigest(),
        )
        checkpoint = checkpoints.load(artifact, pin)
        self.terms.update(
            codex_sha256=checkpoint.origin["native_sha256"],
            checkpoint={"path": str(artifact), **checkpoint.descriptor()},
            confirmation_exposure_scope="prospective_lineage",
        )
        registry = json.loads((self.root / "registry.json").read_text())
        registry.update(
            exposure_scope="prospective_lineage",
            exposed_tasks=list(checkpoint.excluded_tasks),
            operator_exposed_tasks=list(checkpoint.operator_exposed_tasks),
        )
        self.write("registry.json", json.dumps(registry))
        self.terms["canonical"]["registry_sha256"] = hashlib.sha256(
            (self.root / "registry.json").read_bytes()
        ).hexdigest()
        manifest = self.seal()
        self.assertTrue(
            {str(p) for p in artifact.rglob("*") if p.is_file()}
            <= manifest["files"].keys()
        )
        self.write("checkpoint/evidence/store/contracts.json", "changed")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            study.verify(self.camp, self.terms)


if __name__ == "__main__":
    unittest.main()
