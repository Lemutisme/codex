"""Future dependency rules across real Host, seal, runner dispatch and SQLite budget.

Only Docker/image inspection and model transport are faked. Inventory-only tests use
small on-disk fixtures; no real container, provider or benchmark evaluation runs.
"""

import copy
import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_dependency_inspection as inspection
import procontract_dependency_policy as dependencies
import procontract_rsi as rsi
import procontract_store as store
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_canonical_host as canonical_fixtures
import test_procontract_study as inventory_fixtures
import test_procontract_study_host as host_fixtures
import test_procontract_study_launch as launch_fixtures


def write_policy(root, registry):
    allowed = [
        {"name": "rustc", "kind": "tool", "uses": ["build", "exploration"]},
        {"name": "libdeflate.so.0", "kind": "library", "uses": ["runtime"]},
    ]
    tasks = {task: spec["image"] for task, spec in registry["tasks"].items()}
    items = {
        "tool:rustc": {"path": "/usr/bin/rustc", "sha256": "b" * 64},
        "library:libdeflate.so.0": {
            "path": "/usr/lib/libdeflate.so.0",
            "sha256": "c" * 64,
        },
    }
    path = root / "dependencies.json"
    prompt = dependencies.render_prompt(allowed)
    canonical.write_json(
        path,
        {
            "schema": 1,
            "policy": dependencies.POLICY,
            "allowed": allowed,
            "tasks": tasks,
            "images": {image: items for image in set(tasks.values())},
            "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
        },
    )
    (root / "prompt.txt").write_bytes(prompt)
    registry["dependency_policy"] = {
        "path": str(path),
        "sha256": canonical.sha256(path),
    }
    receipts = {
        image: {
            "schema": "preinstalled-artifact-verification-v1",
            "image_id": image,
            "artifacts": {
                key: {**item, "resolved_path": item["path"]}
                for key, item in items.items()
            },
        }
        for image in set(tasks.values())
    }
    return path, receipts


class DependencyHostTest(unittest.TestCase):
    make_host = canonical_fixtures.CanonicalHostTest.make_host
    balance = launch_fixtures.StudyLaunchTest.balance
    preparation = launch_fixtures.StudyLaunchTest.preparation
    transport = launch_fixtures.StudyLaunchTest.transport

    def args(self, camp):
        args = canonical_fixtures.CanonicalHostTest.args(self, camp)
        if getattr(self, "use_submission_policy", False):
            args += ["--submission-policy", dependencies.POLICY]
        return args

    def setUp(self):
        host_fixtures.StudyHostTest.setUp(self)
        self.use_submission_policy = True
        self.data["tasks"][self.audit[-1]]["image"] = "sha256:" + "4" * 64
        self.policy_path, self.receipts = write_policy(self.root, self.data)
        sidecar = self.root / "codex-code-mode-host"
        sidecar.write_text("fixture tool host, never executed")
        sidecar.chmod(0o755)
        study.mandatory_paths.return_value.update(
            {
                self.root / "codex",
                sidecar,
                Path(store.store_bin()).resolve(),
                self.root / "prompt.txt",
                self.registry_path,
                self.pins_path,
                self.policy_path,
            }
        )
        self.repin()

    def repin(self, *, pins_update=None):
        canonical.write_json(self.registry_path, self.data)
        self.registry_sha = canonical.sha256(self.registry_path)
        pins = {
            "registry_sha256": self.registry_sha,
            "adapter_sha256": self.adapter_sha,
            "dependency_policy": {
                "sha256": self.data.get("dependency_policy", {}).get("sha256"),
                "images": copy.deepcopy(self.receipts),
            },
        }
        if pins_update is not None:
            pins_update(pins)
        canonical.write_json(self.pins_path, pins)
        self.descriptor["pins_sha256"] = canonical.sha256(self.pins_path)
        canonical._REGISTRY = None
        canonical._EXPECTED_PINS = None

    def initialize_study(self, name="study-campaign"):
        host = host_fixtures.StudyHostTest.initialize_study(self, name)
        self.producer = self.parent
        self.database = host.camp / "study-budget.sqlite"
        return host

    def test_declared_policy_missing_manifest_verification_or_prompt_refuses_before_init(
        self,
    ):
        original_data = copy.deepcopy(self.data)
        original_policy = self.policy_path.read_bytes()
        original_prompt = (self.root / "prompt.txt").read_bytes()
        cases = (
            "missing_registry_manifest",
            "missing_file",
            "wrong_manifest_hash",
            "unverified_pins",
            "missing_inspected_image",
            "manifest_prompt_hash",
            "manifest_task_image",
            "task_prompt",
            "missing_explicit_flag",
            "null_receipt",
            "wrong_receipt_schema",
            "wrong_receipt_image",
            "wrong_artifact_hash",
            "missing_artifact",
        )
        for name in cases:
            with self.subTest(name=name):
                self.data = copy.deepcopy(original_data)
                self.policy_path.write_bytes(original_policy)
                (self.root / "prompt.txt").write_bytes(original_prompt)
                self.use_submission_policy = True
                pins_update = None
                if name == "missing_registry_manifest":
                    self.data.pop("dependency_policy")
                elif name == "missing_file":
                    self.policy_path.unlink()
                elif name == "wrong_manifest_hash":
                    self.data["dependency_policy"]["sha256"] = "0" * 64
                elif name == "unverified_pins":
                    pins_update = lambda pins: pins.pop("dependency_policy")
                elif name == "missing_inspected_image":
                    pins_update = lambda pins: pins["dependency_policy"].update(
                        images={}
                    )
                elif name in {
                    "null_receipt",
                    "wrong_receipt_schema",
                    "wrong_receipt_image",
                    "wrong_artifact_hash",
                    "missing_artifact",
                }:
                    image = self.data["tasks"][self.task]["image"]

                    def pins_update(pins):
                        records = pins["dependency_policy"]["images"]
                        if name == "null_receipt":
                            records[image] = None
                        elif name == "wrong_receipt_schema":
                            records[image]["schema"] = "claimed-without-verification"
                        elif name == "wrong_receipt_image":
                            records[image]["image_id"] = "sha256:" + "9" * 64
                        elif name == "wrong_artifact_hash":
                            records[image]["artifacts"]["tool:rustc"]["sha256"] = (
                                "0" * 64
                            )
                        else:
                            records[image]["artifacts"].pop("tool:rustc")
                elif name in {"manifest_prompt_hash", "manifest_task_image"}:
                    document = json.loads(original_policy)
                    if name == "manifest_prompt_hash":
                        document["prompt_sha256"] = "0" * 64
                    else:
                        document["tasks"][self.task] = "sha256:" + "5" * 64
                    canonical.write_json(self.policy_path, document)
                    self.data["dependency_policy"]["sha256"] = canonical.sha256(
                        self.policy_path
                    )
                elif name == "task_prompt":
                    (self.root / "prompt.txt").write_bytes(
                        original_prompt + b"\nInstall arbitrary dependencies.\n"
                    )
                else:
                    self.use_submission_policy = False
                self.repin(pins_update=pins_update)
                with (
                    mock.patch.object(study, "freeze") as freeze,
                    mock.patch.object(budget, "initialize") as initialize,
                    mock.patch.object(runner, "AppServer") as server,
                    self.assertRaises((ValueError, RuntimeError)),
                ):
                    self.initialize_study(name)
                freeze.assert_not_called()
                initialize.assert_not_called()
                server.assert_not_called()
                self.assertFalse((self.root / name / "campaign.json").exists())

    def test_declaring_policy_without_canonical_registry_is_rejected(self):
        camp = self.root / "no-registry"
        with (
            mock.patch.object(sys, "argv", self.args(camp)),
            mock.patch.object(study, "freeze") as freeze,
            self.assertRaisesRegex(SystemExit, "canonical dependency registry"),
        ):
            rsi.main()
        freeze.assert_not_called()
        self.assertFalse((camp / "campaign.json").exists())

    def test_task_inspection_precedes_reservation_and_server_and_is_bound_in_sqlite(
        self,
    ):
        host = self.initialize_study()
        args = self.preparation()
        ordered = []
        expected_image = self.data["tasks"][self.task]["image"]
        real_reserve = budget.reserve

        def verify(policy, image):
            self.assertEqual(
                (policy.digest, image),
                (self.data["dependency_policy"]["sha256"], expected_image),
            )
            self.assertEqual(self.balance()["reserved"], dict.fromkeys(self.limits, 0))
            self.assertEqual(opened, [])
            ordered.append("inspection")
            return self.receipts[image]

        def reserve(*args, **kwargs):
            self.assertEqual(ordered, ["inspection"])
            self.assertEqual(opened, [])
            ordered.append("reservation")
            return real_reserve(*args, **kwargs)

        with (
            self.transport() as opened,
            mock.patch.object(
                inspection, "verify_image", side_effect=verify
            ) as inspector,
            mock.patch.object(budget, "reserve", side_effect=reserve),
        ):
            runner.prepare(args)
            inspector.assert_not_called()
            runner.run(args)
        self.assertEqual((ordered, len(opened)), (["inspection", "reservation"], 1))
        self.assertEqual(
            opened[0][2]["reserved"],
            {"task_launches": 1, "learning_launches": 0, "allocated_seconds": 18000},
        )
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            row = connection.execute(
                "SELECT identity_json FROM reservations"
            ).fetchone()
        identity = json.loads(row[0])
        self.assertEqual(
            identity["dependency_policy"],
            {
                "sha256": self.data["dependency_policy"]["sha256"],
                "image_verification": self.receipts[expected_image],
            },
        )
        self.assertEqual(
            (args.run_dir / "prompt.txt").read_bytes(),
            (self.root / "prompt.txt").read_bytes(),
        )
        self.assertEqual(host.terms["submission_policy"], dependencies.POLICY)

    def test_inspection_unavailable_or_different_from_pins_reserves_zero_and_opens_no_server(
        self,
    ):
        self.initialize_study()
        changed = copy.deepcopy(self.receipts[self.data["tasks"][self.task]["image"]])
        changed["artifacts"]["tool:rustc"]["resolved_path"] = "/opt/other-rustc"
        for name, result in (
            ("denied", ValueError("Docker permission denied")),
            ("drifted", changed),
        ):
            args = self.preparation(name=name)
            with (
                self.transport() as opened,
                mock.patch.object(inspection, "verify_image") as inspector,
            ):
                if isinstance(result, Exception):
                    inspector.side_effect = result
                else:
                    inspector.return_value = result
                runner.prepare(args)
                before = self.balance()
                with self.assertRaises((ValueError, RuntimeError)):
                    runner.run(args)
                self.assertEqual((opened, self.balance()), ([], before))
                self.assertFalse((args.run_dir / "study-launch.json").exists())
                inspector.assert_called_once()
        self.assertEqual(self.balance()["reserved"], dict.fromkeys(self.limits, 0))

    def test_prepared_prompt_image_or_dependency_source_drift_fails_before_inspection(
        self,
    ):
        self.initialize_study()
        for name in ("prompt", "image", "dependency_source"):
            args = self.preparation(name=name)
            with (
                self.transport() as opened,
                mock.patch.object(inspection, "verify_image") as inspector,
            ):
                runner.prepare(args)
                path = (
                    self.policy_path
                    if name == "dependency_source"
                    else args.run_dir
                    / ("prompt.txt" if name == "prompt" else "manifest.json")
                )
                original = path.read_bytes()
                if name == "image":
                    document = json.loads(original)
                    document["image"] = "sha256:" + "0" * 64
                    path.write_text(json.dumps(document))
                else:
                    path.write_bytes(original + b" ")
                try:
                    with self.assertRaises((ValueError, RuntimeError)):
                        runner.run(args)
                    self.assertEqual(
                        (opened, self.balance()["reserved"]),
                        ([], dict.fromkeys(self.limits, 0)),
                    )
                    inspector.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_learning_role_does_not_inspect_or_inherit_task_image_allowance(self):
        self.initialize_study()
        args = self.preparation("research.md", "research")
        with (
            self.transport() as opened,
            mock.patch.object(inspection, "verify_image") as inspector,
        ):
            runner.prepare(args)
            runner.run(args)
            inspector.assert_not_called()
        self.assertEqual(
            (len(opened), self.balance()["reserved"]),
            (
                1,
                {"task_launches": 0, "learning_launches": 1, "allocated_seconds": 3600},
            ),
        )
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            identity = json.loads(
                connection.execute("SELECT identity_json FROM reservations").fetchone()[
                    0
                ]
            )
        self.assertNotIn("dependency_policy", identity)

    def test_pin_state_collects_every_distinct_image_verification(self):
        frozen = canonical.configure(self.registry_path, self.registry_sha)
        tasks_dir = self.root / "task-fixtures"
        instances, blob_hashes = [], {}
        frozen.programbench.mkdir()
        (frozen.programbench / "uv.lock").write_text("fixture lock")
        frozen.wheelhouse.mkdir()
        (frozen.wheelhouse / "fixture.whl").write_bytes(b"fixture wheel")
        for task in frozen.tasks:
            (tasks_dir / task).mkdir(parents=True)
            instance = {
                "instance_id": task,
                "branches": {"b": {"tests": ["one", "two", "three"]}},
            }
            instances.append(instance)
            name = f"{task}/tests/b.tar.gz"
            path = frozen.blob_root / name
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fixture tests")
            blob_hashes[name] = canonical.sha256(path)
        canonical.write_json(
            frozen.blob_manifest,
            {
                "commit": frozen.hf_revision,
                "blob_root": str(frozen.blob_root),
                "blob_sha256": blob_hashes,
            },
        )
        tags = {spec["image_tag"]: spec["image"] for spec in frozen.tasks.values()}

        def external_output(command, **kwargs):
            return (
                self.data["programbench_head"]
                if command[0] == "git"
                else tags[command[3]]
            )

        with (
            mock.patch.object(
                canonical,
                "pb_imports",
                return_value=(
                    tasks_dir,
                    lambda: instances,
                    lambda _: ["b"],
                    lambda _: set(),
                    None,
                ),
            ),
            mock.patch.object(
                canonical.subprocess, "check_output", side_effect=external_output
            ),
            mock.patch.object(canonical.subprocess, "run"),
            mock.patch.object(
                inspection,
                "verify_image",
                side_effect=lambda policy, image: self.receipts[image],
            ) as inspector,
        ):
            pins = canonical.pin_state()
        self.assertEqual(
            [call.args[1] for call in inspector.call_args_list], sorted(self.receipts)
        )
        self.assertEqual(
            pins["dependency_policy"],
            {
                "sha256": self.data["dependency_policy"]["sha256"],
                "images": self.receipts,
            },
        )


class DependencyStudyInventoryTest(inventory_fixtures.StudyFixture):
    def test_manifest_is_mandatory_and_changing_it_invalidates_the_real_seal(self):
        registry_path = self.root / "registry.json"
        data = json.loads(registry_path.read_text())
        policy_path, _ = write_policy(self.root, data)
        canonical.write_json(registry_path, data)
        self.terms["canonical"]["registry_sha256"] = canonical.sha256(registry_path)
        self.terms.update(
            submission_policy=dependencies.POLICY,
            task_prompt_sha256=canonical.sha256(self.root / "prompt.txt"),
        )
        manifest = self.seal()
        self.assertIn(str(policy_path), manifest["files"])
        self.assertEqual(
            manifest["files"][str(policy_path)]["sha256"],
            data["dependency_policy"]["sha256"],
        )
        policy_path.write_bytes(policy_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            study.verify(self.camp, self.terms)


if __name__ == "__main__":
    unittest.main()
