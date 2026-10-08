import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import procontract_study as study


class StudyFixture(unittest.TestCase):
    """Real seal/registry checks over small resource files; no model or process calls."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.camp = self.root / "campaign"
        self.scripts = self.root / "source/scripts"
        self.scripts.mkdir(parents=True)
        for name in (
            "procontract_study.py",
            "procontract_canonical_registry.py",
            "procontract_harness_program.py",
            "procontract_canonical.py",
        ):
            (self.scripts / name).write_bytes((study.SCRIPTS / name).read_bytes())
        self.write("source/scripts/procontract_benchmark_runner.py", "# fake transport")
        for role in (
            "executor",
            "research",
            "analyst",
            "challenger",
            "drafter",
            "prober",
            "reviewer",
        ):
            self.write(f"source/codex-rs/ext/pro-contract/policies/{role}.md", role)
        for name in ("codex", "codex-code-mode-host", "pro-contract-store", "python"):
            self.write(f"bin/{name}", "fake executable " + name)
        for name in (
            "uv.lock",
            "src/module.py",
            "scripts/scorer.py",
            ".venv/pyvenv.cfg",
            ".venv/lib/python3/site-packages/package.py",
            ".venv/lib/python3/site-packages/module.pyc",
            ".venv/lib/python3/site-packages/startup.pth",
            ".venv/bin/python",
        ):
            self.write("pb/" + name, name)
        self.task = "example__serve.1234567"
        self.confirm = "different__confirm.abcdef0"
        for task in (self.task, self.confirm):
            self.write(f"blobs/{task}/tests.tar.gz", task)
        self.write("wheels/package.whl", "wheel")
        self.write("prompt.txt", "task")
        self.write("blob-manifest.json", "{}")
        self.write("pins.json", "{}")
        document = {
            "schema": 1,
            "tasks": {
                task: {"total": 3, "image": "sha256:" + "a" * 64}
                for task in (self.task, self.confirm)
            },
            "programbench": str(self.root / "pb"),
            "programbench_head": "a" * 40,
            "hf_revision": "b" * 40,
            "python": str(self.root / "pb/.venv/bin/python"),
            "wheelhouse": str(self.root / "wheels"),
            "blob_root": str(self.root / "blobs"),
            "blob_manifest": str(self.root / "blob-manifest.json"),
            "pins_file": str(self.root / "pins.json"),
        }
        self.write("registry.json", json.dumps(document))
        self.terms = {
            "model": "gpt-5.6-luna",
            "effort": "max",
            "task_deadline_secs": 18000,
            "research_deadline_secs": 3600,
            "analysis_deadline_secs": 3600,
            "budgets": {"task_attempts": 1},
            "research_image": "sha256:" + "a" * 64,
            "codex_bin": str(self.root / "bin/codex"),
            "task_prompt": str(self.root / "prompt.txt"),
            "stream": {"mode": "guarded", "release_every": 1, "order": [self.task]},
            "pools": {"dev": [], "confirm": [self.confirm]},
            **{
                key: document[key]
                for key in ("programbench", "programbench_head", "hf_revision")
            },
            "canonical": {
                "registry_path": str(self.root / "registry.json"),
                "registry_sha256": hashlib.sha256(
                    (self.root / "registry.json").read_bytes()
                ).hexdigest(),
            },
        }
        self.limits = {
            "task_launches": 11,
            "learning_launches": 14,
            "allocated_seconds": 248400,
        }
        self.enterContext(mock.patch.object(study, "SCRIPTS", self.scripts))
        self.enterContext(
            mock.patch.object(study.sys, "executable", str(self.root / "bin/python"))
        )
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {"PRO_CONTRACT_STORE_BIN": str(self.root / "bin/pro-contract-store")},
            )
        )

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def seal(self):
        self.terms["study"] = study.freeze(self.camp, self.terms, self.limits)
        return study.verify(self.camp, self.terms)


class StudyTest(StudyFixture):
    def test_freeze_binds_actual_inventory_and_preserves_immutable_manifest(self):
        manifest = self.seal()
        self.assertEqual(manifest["limits"], self.limits)
        self.assertIn(
            str(self.root / "pb/.venv/lib/python3/site-packages/module.pyc"),
            manifest["files"],
        )
        with self.assertRaisesRegex(ValueError, "new campaign"):
            study.freeze(self.camp, self.terms, self.limits)
        self.assertEqual(study.verify(self.camp, self.terms), manifest)

    def test_source_binary_dependency_prompt_and_added_shadow_file_drift(self):
        self.seal()
        for name in (
            "source/scripts/procontract_study.py",
            "bin/codex-code-mode-host",
            "bin/pro-contract-store",
            "pb/.venv/lib/python3/site-packages/module.pyc",
            "prompt.txt",
        ):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "inventory changed"):
                    study.verify(self.camp, self.terms)
                path.write_bytes(original)
        self.write("source/scripts/json.py", "shadow module")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            study.verify(self.camp, self.terms)

    def test_descriptor_terms_runner_and_environment_changes_fail_closed(self):
        self.seal()
        changed = copy.deepcopy(self.terms)
        changed["analysis_deadline_secs"] = 7200
        with self.assertRaisesRegex(ValueError, "campaign identity"):
            study.verify(self.camp, changed)
        with self.assertRaisesRegex(ValueError, "command"):
            study.verify(self.camp, self.terms, ["another-runner"])
        with mock.patch.dict(os.environ, {"PYTHONPATH": "changed"}):
            with self.assertRaisesRegex(ValueError, "environment"):
                study.verify(self.camp, self.terms)
        changed = copy.deepcopy(self.terms)
        changed["study"]["manifest_path"] = str(self.root / "elsewhere.json")
        with self.assertRaisesRegex(ValueError, "descriptor"):
            study.verify(self.camp, changed)

    def test_evaluator_uses_lexical_venv_and_sealed_host_store_not_child_environment(
        self,
    ):
        manifest = self.seal()
        with mock.patch.object(
            study.sys, "executable", str(self.root / "pb/.venv/bin/python")
        ):
            with mock.patch.dict(
                os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True
            ):
                self.assertEqual(
                    study.verify(self.camp, self.terms, evaluator=True), manifest
                )
                with self.assertRaisesRegex(ValueError, "host interpreter"):
                    study.verify(self.camp, self.terms)

    def test_invalid_profile_limits_and_existing_campaign_cannot_be_sealed(self):
        for field, value in (
            ("model", "gpt-6-astra"),
            ("research_image", "latest"),
            ("task_deadline_secs", 21600),
            ("analysis_deadline_secs", True),
        ):
            with self.subTest(field=field):
                terms = {**self.terms, field: value}
                with self.assertRaises(ValueError):
                    study.freeze(self.camp, terms, self.limits)
        for value in (0, True, 1 << 63):
            with self.assertRaisesRegex(ValueError, "limits"):
                study.freeze(
                    self.camp, self.terms, {**self.limits, "task_launches": value}
                )
        with self.assertRaisesRegex(ValueError, "limits"):
            study.freeze(self.camp, self.terms, {**self.limits, "unknown": 1})
        self.write("campaign/campaign.json", "{}")
        with self.assertRaisesRegex(ValueError, "new campaign"):
            study.freeze(self.camp, self.terms, self.limits)

    def test_manifest_inventory_cannot_be_used_as_its_own_required_file_list(self):
        self.seal()
        path = self.camp / "study.json"
        manifest = json.loads(path.read_text())
        manifest["files"].pop(str(self.root / "bin/codex"))
        path.write_text(json.dumps(manifest))
        self.terms["study"]["manifest_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            study.verify(self.camp, self.terms)

    def test_drifted_helper_is_rejected_before_registry_import(self):
        self.seal()
        self.write("source/scripts/procontract_canonical_registry.py", "changed helper")
        with mock.patch.object(
            study, "_registry", side_effect=AssertionError("helper was imported")
        ):
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                study.verify(self.camp, self.terms)

    def test_unknown_schema_and_invalid_manifest_limits_are_rejected(self):
        original = self.seal()
        path = self.camp / "study.json"
        for update in (
            {"schema": True},
            {"unknown": 1},
            {"limits": {**self.limits, "learning_launches": 0}},
        ):
            path.write_text(json.dumps({**original, **update}))
            self.terms["study"]["manifest_sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            with self.assertRaises(ValueError):
                study.verify(self.camp, self.terms)


if __name__ == "__main__":
    unittest.main()
