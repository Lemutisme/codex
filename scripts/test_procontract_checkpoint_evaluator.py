"""Real sanitized evaluator child plus checkpoint/store verification; no Docker/models.

Only the post-fence preflight body is replaced: this exercises canonical.main's real
entry, explicit study seal, dependency inventory and native checkpoint digests.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest import mock

import procontract_canonical as canonical
import procontract_checkpoint as checkpoints
import procontract_rsi as rsi
import procontract_store as store
import procontract_study as study
import test_procontract_checkpoint as fixtures


class CheckpointEvaluatorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.binary = Path(store.store_bin()).absolute()
        self.enterContext(
            mock.patch.dict(os.environ, {"PRO_CONTRACT_STORE_BIN": str(self.binary)})
        )
        self.enterContext(
            mock.patch.multiple(canonical, _REGISTRY=None, _EXPECTED_PINS=None)
        )
        self.scripts = self.root / "runtime/scripts"
        self.scripts.mkdir(parents=True)
        for source in study.SCRIPTS.glob("procontract_*.py"):
            shutil.copyfile(source, self.scripts / source.name)
        shutil.copytree(
            rsi.V0_BUNDLE, self.scripts.parent / "codex-rs/ext/pro-contract/policies"
        )
        self.assertFalse(
            (self.scripts.parent / "codex-rs/target/debug/pro-contract-store").exists()
        )
        pb = self.root / "pb"
        venv.EnvBuilder(with_pip=False).create(pb / ".venv")
        self.python = (
            pb / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        for name in ("uv.lock", "src/module.py", "scripts/evaluate.py"):
            self.write(pb / name, "fixture resource")
        native = self.root / "bin/codex"
        self.write(native, "fixture native binary, never launched")
        self.write(native.with_name("codex-code-mode-host"), "fixture sidecar")
        checkpoint_path = self.root / "checkpoint"
        pin = fixtures.make_checkpoint(
            checkpoint_path, native_sha256=canonical.sha256(native)
        )
        checkpoint = checkpoints.load(checkpoint_path, pin)
        tasks = ["fresh__serve.123abcd", "fresh__confirm.456abcd"]
        for task in tasks:
            self.write(self.root / "blobs" / task / "tests.tar.gz", "fixture tests")
        self.write(self.root / "wheels/fixture.whl", "fixture wheel")
        self.write(self.root / "blob-manifest.json", "{}")
        self.write(self.root / "prompt.txt", "Fixture requirements.")
        registry = {
            "schema": 1,
            "tasks": {
                task: {"total": 3, "image": "sha256:" + "3" * 64} for task in tasks
            },
            "programbench": str(pb),
            "programbench_head": "1" * 40,
            "hf_revision": "2" * 40,
            "python": str(self.python),
            "wheelhouse": str(self.root / "wheels"),
            "blob_root": str(self.root / "blobs"),
            "blob_manifest": str(self.root / "blob-manifest.json"),
            "pins_file": str(self.root / "pins.json"),
            "exposure_scope": "prospective_lineage",
            "exposed_tasks": list(checkpoint.excluded_tasks),
            "operator_exposed_tasks": list(checkpoint.operator_exposed_tasks),
        }
        canonical.write_json(self.root / "registry.json", registry)
        identity = {
            "registry_path": str(self.root / "registry.json"),
            "registry_sha256": canonical.sha256(self.root / "registry.json"),
            "adapter_sha256": canonical.sha256(
                self.scripts / "procontract_canonical.py"
            ),
        }
        canonical.write_json(
            self.root / "pins.json",
            {key: identity[key] for key in ("registry_sha256", "adapter_sha256")},
        )
        identity["pins_sha256"] = canonical.sha256(self.root / "pins.json")
        self.terms = {
            "model": "gpt-5.6-luna",
            "effort": "max",
            "task_deadline_secs": 18000,
            "research_deadline_secs": 3600,
            "analysis_deadline_secs": 3600,
            "budgets": {"task_attempts": 1},
            "research_image": "sha256:" + "a" * 64,
            "codex_bin": str(native),
            "codex_sha256": canonical.sha256(native),
            "task_prompt": str(self.root / "prompt.txt"),
            "stream": {"mode": "guarded", "release_every": 1, "order": tasks[:1]},
            "pools": {"dev": [], "confirm": tasks[1:]},
            "canonical": identity,
            "confirmation_exposure_scope": "prospective_lineage",
            "checkpoint": {"path": str(checkpoint_path), **checkpoint.descriptor()},
            **{
                key: registry[key]
                for key in ("programbench", "programbench_head", "hf_revision")
            },
        }
        self.camp = self.root / "campaign"
        self.limits = {
            "task_launches": 11,
            "learning_launches": 14,
            "allocated_seconds": 248400,
        }
        with mock.patch.object(study, "SCRIPTS", self.scripts):
            self.terms["study"] = study.freeze(self.camp, self.terms, self.limits)
        canonical.write_json(self.camp / "campaign.json", self.terms)
        canonical.configure(self.root / "registry.json", identity["registry_sha256"])
        self.marker = self.root / "UNTRUSTED_STORE_EXECUTED"
        self.trap = self.root / "untrusted-store"
        self.write(
            self.trap,
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(self.marker)!r}).write_text('executed')\nraise SystemExit(71)\n",
        )
        self.trap.chmod(0o755)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def child(self, *, hostile=False):
        env = canonical.evaluator_env()
        self.assertNotIn("PRO_CONTRACT_STORE_BIN", env)
        if hostile:
            env["PRO_CONTRACT_STORE_BIN"] = str(self.trap)
        script = (
            f"import sys; sys.path.insert(0, {str(self.scripts)!r}); "
            "import procontract_canonical as canonical; "
            "canonical.preflight = lambda: {'verified_evaluator_entry': True}; "
            "canonical.main()"
        )
        identity, seal = self.terms["canonical"], self.terms["study"]
        return subprocess.run(
            [
                str(self.python),
                "-c",
                script,
                "preflight",
                "--registry",
                identity["registry_path"],
                "--registry-sha256",
                identity["registry_sha256"],
                "--pins-sha256",
                identity["pins_sha256"],
                "--study-manifest",
                seal["manifest_path"],
                "--study-sha256",
                seal["manifest_sha256"],
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )

    def test_sanitized_and_hostile_child_env_both_use_authenticated_store(self):
        sealed = json.loads((self.camp / "study.json").read_text())
        self.assertEqual(sealed["store_bin"], str(self.binary))
        for hostile in (False, True):
            with self.subTest(hostile=hostile):
                child = self.child(hostile=hostile)
                self.assertEqual(child.returncode, 0, child.stderr)
                self.assertEqual(
                    json.loads(child.stdout), {"verified_evaluator_entry": True}
                )
                self.assertFalse(self.marker.exists())

    def test_resealed_uninventoried_store_is_rejected_before_executing_it(self):
        path = self.camp / "study.json"
        sealed = json.loads(path.read_text())
        self.assertNotIn(str(self.trap), sealed["files"])
        sealed["store_bin"] = str(self.trap)
        canonical.write_json(path, sealed)
        self.terms["study"]["manifest_sha256"] = canonical.sha256(path)
        canonical.write_json(self.camp / "campaign.json", self.terms)
        child = self.child(hostile=True)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("study command or campaign identity changed", child.stderr)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
