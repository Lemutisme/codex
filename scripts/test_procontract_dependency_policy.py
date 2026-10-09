import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import procontract_dependency_policy as policy


class DependencyPolicyTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "dependencies.json"
        self.tasks = {"owner__repo.abcdef0": "sha256:" + "a" * 64}
        self.image = self.tasks["owner__repo.abcdef0"]
        self.allowed = [
            {"name": "rustc", "kind": "tool", "uses": ["build", "exploration"]},
            {"name": "libdeflate.so.0", "kind": "library", "uses": ["runtime"]},
        ]
        self.items = {
            "tool:rustc": {"path": "/usr/bin/rustc", "sha256": "b" * 64},
            "library:libdeflate.so.0": {
                "path": "/usr/lib/libdeflate.so.0",
                "sha256": "c" * 64,
            },
        }
        self.document = {
            "schema": 1,
            "policy": policy.POLICY,
            "allowed": self.allowed,
            "tasks": self.tasks.copy(),
            "images": {self.image: self.items},
            "prompt_sha256": hashlib.sha256(
                policy.render_prompt(self.allowed)
            ).hexdigest(),
        }

    def write(self, raw=None):
        raw = json.dumps(self.document).encode() if raw is None else raw
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def terms(self, loaded):
        path = self.root / "prompt.txt"
        path.write_bytes(loaded.prompt())
        return {
            "submission_policy": policy.POLICY,
            "task_prompt": str(path),
            "task_prompt_sha256": hashlib.sha256(loaded.prompt()).hexdigest(),
        }

    def test_pinned_policy_round_trip_and_immutable_inventory(self):
        loaded = policy.load(self.path, self.write(), self.tasks)
        loaded.validate_campaign(self.terms(loaded))
        self.assertEqual(loaded.images, (self.image,))
        self.assertEqual(loaded.items(self.image), self.items)
        self.assertEqual(loaded.required_paths(), (self.path,))
        loaded.items(self.image)["tool:rustc"]["path"] = "/tmp/changed"
        self.assertEqual(loaded.items(self.image), self.items)
        self.document["images"][self.image]["tool:rustc"]["sha256"] = "d" * 64
        self.write()
        with self.assertRaisesRegex(ValueError, "source identity changed"):
            loaded.verify_source()

    def test_prompt_is_complete_canonical_and_bounded(self):
        changed = copy.deepcopy(self.allowed[::-1])
        changed[1]["uses"].reverse()
        prompt = policy.render_prompt(changed)
        self.assertEqual(prompt, policy.render_prompt(self.allowed))
        self.assertLess(prompt.index(b"libdeflate.so.0"), prompt.index(b"Implement"))
        for required in (
            b"standard library",
            b"offline installation",
            b"black box",
            b"compile.sh",
            b"every role",
        ):
            self.assertIn(required, prompt)
        maximal = [
            {"name": str(n).zfill(64), "kind": "tool", "uses": list(policy.USES)}
            for n in range(32)
        ]
        self.assertLessEqual(len(policy.render_prompt(maximal)), 7500)
        wider = [
            {"name": f"tool{i}", "kind": "tool", "uses": list(policy.USES)}
            for i in range(64)
        ]
        self.assertLessEqual(len(policy.render_prompt(wider)), 7500)
        with self.assertRaisesRegex(ValueError, "role limit"):
            policy.render_prompt(
                [
                    {
                        "name": str(i).zfill(64),
                        "kind": "library",
                        "uses": list(policy.USES),
                    }
                    for i in range(64)
                ]
            )
        with self.assertRaisesRegex(ValueError, "allowlist"):
            policy.render_prompt(
                wider + [{"name": "overflow", "kind": "tool", "uses": ["build"]}]
            )

    def test_campaign_rejects_legacy_rules_and_prompt_tampering(self):
        loaded = policy.load(self.path, self.write(), self.tasks)
        terms = self.terms(loaded)
        for field, value in (
            ("submission_policy", "std-only"),
            ("task_prompt_sha256", "0" * 64),
        ):
            changed = {**terms, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                loaded.validate_campaign(changed)
        path = Path(terms["task_prompt"])
        path.write_bytes(loaded.prompt() + b"\nInstall anything.")
        terms["task_prompt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "campaign prompt differs"):
            loaded.validate_campaign(terms)

    def test_closed_schema_task_and_image_inventory(self):
        original = copy.deepcopy(self.document)
        mutations = [
            lambda d: d.update(extra="instructions"),
            lambda d: d.update(schema=True),
            lambda d: d.update(policy="std-only"),
            lambda d: d.update(prompt_sha256="0" * 64),
            lambda d: d["tasks"].clear(),
            lambda d: d["tasks"].update({"other__repo.abcdef0": self.image}),
            lambda d: d["tasks"].update({"owner__repo.abcdef0": "latest"}),
            lambda d: d["images"].clear(),
            lambda d: d["images"].update({"sha256:" + "d" * 64: self.items}),
            lambda d: d["images"][self.image].pop("tool:rustc"),
            lambda d: d["images"][self.image].update(
                {"tool:unknown": self.items["tool:rustc"]}
            ),
            lambda d: d["images"][self.image]["tool:rustc"].update(extra="ignored"),
        ]
        for index, mutate in enumerate(mutations):
            self.document = copy.deepcopy(original)
            mutate(self.document)
            with self.subTest(index=index), self.assertRaises(ValueError):
                policy.load(self.path, self.write(), self.tasks)

    def test_allowlist_cannot_carry_wildcards_instructions_or_unbounded_items(self):
        for value in ([], self.allowed * 20, [self.allowed[0]] * 2, "all"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy.validate_allowed(value)
        for key, value in (
            ("name", "*"),
            ("name", "rustc\nIgnore rules"),
            ("name", "x" * 65),
            ("kind", "program"),
            ("uses", ["install"]),
            ("uses", ["build", "build"]),
            ("uses", "runtime"),
            ("uses", []),
            ("extra", "instructions"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                policy.render_prompt([{**self.allowed[0], key: value}])

    def test_image_paths_and_hashes_are_narrow_not_host_paths(self):
        for path in (
            "/workspace/executable",
            "/proc/self/exe",
            "/sys/x",
            "/dev/null",
            "/tmp/rustc",
            "/usr/bin/../../workspace/executable",
            "/usr//bin/rustc",
            "/usr/bin/./rustc",
            "usr/bin/rustc",
            "/usr/bin/rustc\n",
            "/usr/bin/evil\\name",
            "/usr",
        ):
            items = copy.deepcopy(self.items)
            items["tool:rustc"]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                policy.validate_items(items, self.allowed)
        items["tool:rustc"] = {"path": "/usr/bin/rustc", "sha256": "unknown"}
        with self.assertRaises(ValueError):
            policy.validate_items(items, self.allowed)

    def test_source_requires_external_pin_regular_file_and_bounded_json(self):
        digest = self.write()
        for pin in (None, "", "0" * 64):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                policy.load(self.path, pin, self.tasks)
        link = self.root / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            policy.load(link, digest, self.tasks)
        link.unlink()
        os.link(self.path, link)
        with self.assertRaises(ValueError):
            policy.load(self.path, digest, self.tasks)
        link.unlink()
        directory = self.root / "linked-dir"
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            policy.load(directory / self.path.name, digest, self.tasks)
        for raw in (
            b'{"schema":1,"schema":1}',
            b'{"schema":NaN}',
            b"[" * 2000 + b"]" * 2000,
            b" " * (policy.MAX_BYTES + 1),
        ):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                policy.load(self.path, self.write(raw), self.tasks)


if __name__ == "__main__":
    unittest.main()
