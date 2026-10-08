import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import procontract_canonical_registry as registry


class RegistryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "registry.json"
        self.task = "example__first.1234567"
        self.fresh = "different__project.abcdef0"
        self.document = {
            "schema": 1,
            "tasks": {
                self.task: {"total": 3, "image": "sha256:" + "a" * 64},
                self.fresh: {"total": 2, "image": "sha256:" + "b" * 64},
            },
            "programbench": str(self.root / "pb"),
            "programbench_head": "a" * 40,
            "hf_revision": "b" * 40,
            **{
                name: str(self.root / name)
                for name in ("wheelhouse", "blob_root", "blob_manifest", "pins_file")
            },
        }

    def write(self):
        raw = json.dumps(self.document).encode()
        self.path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def terms(self):
        return {
            **{
                key: self.document[key]
                for key in ("programbench", "programbench_head", "hf_revision")
            },
            "stream": {"order": [self.task]},
            "pools": {"dev": [], "confirm": [self.fresh]},
        }

    def test_fresh_registry_is_loaded_without_the_old_three_task_allowlist(self):
        loaded = registry.load(self.path, self.write())
        loaded.validate_campaign(self.terms())
        self.assertEqual(
            dict(loaded.tasks[self.fresh]),
            {
                "total": 2,
                "image": "sha256:" + "b" * 64,
                "image_tag": "programbench/different_1776_project.abcdef0:task_cleanroom_v6",
            },
        )
        with self.assertRaises(TypeError):
            loaded.tasks[self.fresh]["total"] = 99

    def test_frozen_registry_drift_is_rejected_on_resume(self):
        loaded = registry.load(self.path, self.write())
        self.document["tasks"][self.fresh]["total"] = 5
        self.write()
        with self.assertRaisesRegex(ValueError, "identity"):
            loaded.verify_source()

    def test_unknown_tasks_and_known_repo_exposure_do_not_enter_confirmation(self):
        loaded = registry.load(self.path, self.write())
        terms = self.terms()
        terms["pools"]["confirm"] = ["missing__repo.1234567"]
        with self.assertRaisesRegex(ValueError, "outside"):
            loaded.validate_campaign(terms)
        self.document["exposed_tasks"] = ["different__project.1111111"]
        loaded = registry.load(self.path, self.write())
        with self.assertRaisesRegex(ValueError, "repository"):
            loaded.validate_campaign(self.terms())

    def test_commits_of_the_same_repository_are_not_split_across_confirmation(self):
        related = "example__first.7654321"
        self.document["tasks"][related] = self.document["tasks"][self.task]
        loaded = registry.load(self.path, self.write())
        terms = self.terms()
        terms["pools"]["confirm"] = [related]
        with self.assertRaisesRegex(ValueError, "repository"):
            loaded.validate_campaign(terms)

    def test_unpinned_images_counts_paths_and_unknown_fields_are_rejected(self):
        for key, value in (
            ("image", "latest"),
            ("total", True),
            ("total", 0),
            ("extra", "ignored"),
        ):
            with self.subTest(key=key):
                old = dict(self.document["tasks"][self.task])
                self.document["tasks"][self.task][key] = value
                with self.assertRaises(ValueError):
                    registry.load(self.path, self.write())
                self.document["tasks"][self.task] = old
        self.document["pins_file"] = "relative/pins.json"
        with self.assertRaises(ValueError):
            registry.load(self.path, self.write())

    def test_duplicate_keys_and_unpinned_source_are_rejected(self):
        raw = (
            json.dumps(self.document)
            .replace('"schema": 1', '"schema": 1, "schema": 1')
            .encode()
        )
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            registry.load(self.path, hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            registry.load(self.path, "not-a-digest")


if __name__ == "__main__":
    unittest.main()
