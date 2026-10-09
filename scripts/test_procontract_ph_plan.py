"""CLI/seal wiring for a future P/H episode; real files/store, no model or Docker."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import procontract_checkpoint as checkpoints
import procontract_ph_supervisor as supervisor
import procontract_rsi as rsi
import procontract_study as study
import test_procontract_checkpoint as checkpoint_fixtures
import test_procontract_dependency_host as dependency_fixtures
import test_procontract_ph_supervisor as supervisor_fixtures
import test_procontract_study as study_fixtures


class InitFlagsTest(unittest.TestCase):
    def test_partial_plan_flags_and_missing_finite_budget_fail_before_external_work(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [
                "rsi",
                "init",
                "--camp",
                str(root / "campaign"),
                "--codex-bin",
                "missing-codex",
                "--task-prompt",
                str(root / "missing-prompt"),
                "--research-image",
                "fixture",
                "--hf-revision",
                "rev",
            ]
            for extra in (
                ["--ph-supervisor-plan", str(root / "plan.json")],
                ["--ph-supervisor-sha256", "a" * 64],
                [
                    "--ph-supervisor-plan",
                    str(root / "plan.json"),
                    "--ph-supervisor-sha256",
                    "a" * 64,
                ],
            ):
                with (
                    mock.patch.object(sys, "argv", [*argv, *extra]),
                    mock.patch.object(
                        rsi.subprocess,
                        "run",
                        side_effect=AssertionError("external work"),
                    ),
                    mock.patch.object(study, "freeze") as freeze,
                    self.assertRaises(SystemExit),
                ):
                    rsi.main()
                freeze.assert_not_called()
                self.assertFalse((root / "campaign/campaign.json").exists())


class SealedPlanTest(study_fixtures.StudyFixture):
    def setUp(self):
        store_binary = os.environ["PRO_CONTRACT_STORE_BIN"]
        super().setUp()
        self.enterContext(
            mock.patch.dict(os.environ, {"PRO_CONTRACT_STORE_BIN": store_binary})
        )
        artifact = self.root / "checkpoint"
        native = supervisor.digest(self.root / "bin/codex")
        pin = checkpoint_fixtures.make_checkpoint(artifact, native_sha256=native)
        checkpoint = checkpoints.load(artifact, pin)
        registry_path = self.root / "registry.json"
        registry = json.loads(registry_path.read_text())
        stream = [self.task, *[f"serve__task{i}.123abcd" for i in range(3)]]
        confirm = [self.confirm, *[f"confirm__task{i}.123abcd" for i in range(3)]]
        registry.update(
            exposure_scope="prospective_lineage",
            exposed_tasks=list(checkpoint.excluded_tasks),
            operator_exposed_tasks=list(checkpoint.operator_exposed_tasks),
            tasks={
                task: {"total": 3, "image": "sha256:" + "a" * 64}
                for task in [*stream, *confirm]
            },
        )
        for task in registry["tasks"]:
            self.write(f"blobs/{task}/tests.tar.gz", "fixture tests")
        dependency_fixtures.write_policy(self.root, registry)
        self.write("registry.json", json.dumps(registry))
        settings = supervisor_fixtures.plan_terms(self.camp)
        for name in ("checkpoint", "canonical", "stream", "pools"):
            settings.pop(name)
        self.terms.update(
            settings,
            codex_sha256=native,
            task_prompt_sha256=supervisor.digest(self.root / "prompt.txt"),
            checkpoint={"path": str(artifact), **checkpoint.descriptor()},
        )
        self.terms["canonical"]["registry_sha256"] = supervisor.digest(registry_path)
        self.terms["stream"].update(order=stream, batch=1, method_confirmation="defer")
        self.terms["pools"] = {"dev": [], "confirm": confirm}

    def test_real_inventory_seals_plan_and_rejects_changed_or_removed_descriptor(self):
        plan = supervisor.plan_path(self.terms)
        supervisor.validate_plan(self.camp, self.terms)
        manifest = self.seal()
        self.assertEqual(
            manifest["files"][str(plan)]["sha256"],
            self.terms["ph_supervisor"]["plan_sha256"],
        )
        changed = copy.deepcopy(self.terms)
        changed.pop("ph_supervisor")
        with self.assertRaisesRegex(ValueError, "identity"):
            study.verify(self.camp, changed)
        plan.write_bytes(plan.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            study.verify(self.camp, self.terms)


if __name__ == "__main__":
    unittest.main()
