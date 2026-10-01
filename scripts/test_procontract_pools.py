import errno
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import procontract_pools as pools


def task(i: int, difficulty: str = "easy") -> dict:
    return {
        "id": f"o{i}__r{i}.abc{i:04d}",
        "repository": f"o{i}/r{i}",
        "language": "rs",
        "difficulty": difficulty,
    }


class SplitTest(unittest.TestCase):
    def test_split_is_deterministic_stratified_and_seen_goes_to_dev(self):
        tasks = [task(i, "easy" if i % 2 else "hard") for i in range(40)]
        seen = {tasks[0]["id"], tasks[1]["id"]}

        first = pools.split(tasks, seen, "salt", (40, 30, 30))
        second = pools.split(tasks, seen, "salt", (40, 30, 30))
        other = pools.split(tasks, seen, "other-salt", (40, 30, 30))

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(seen <= set(first["dev"]))
        self.assertEqual(
            sorted(first["dev"] + first["select"] + first["confirm"]),
            sorted(t["id"] for t in tasks),
        )
        # 19 non-seen tasks per stratum: dev round(7.6)=8, select round(5.7)=6, confirm 5.
        self.assertEqual((len(first["select"]), len(first["confirm"])), (12, 10))

    def test_commitments_hide_lists_but_bind_them(self):
        self.assertNotEqual(
            pools.commitment("salt", ["a"]), pools.commitment("other", ["a"])
        )
        self.assertEqual(
            pools.commitment("salt", ["a", "b"]), pools.commitment("salt", ["b", "a"])
        )
        self.assertNotEqual(
            pools.commitment("salt", ["a"]), pools.commitment("salt", ["b"])
        )


class SeenTest(unittest.TestCase):
    def test_seen_ids_come_from_artifacts_but_never_from_tests_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "report.md").write_text(
                "ran wfxr__csview.8ac4de0 and junk__x.zzzzzzz"
            )
            Path(tmp, "tests").mkdir()
            Path(tmp, "tests", "list.json").write_text("sharkdp__hexyl.1234567")
            found = pools.seen_ids(
                [Path(tmp)], {"wfxr__csview.8ac4de0", "sharkdp__hexyl.1234567"}
            )
        self.assertEqual(found, {"wfxr__csview.8ac4de0"})

    def test_long_identifier_like_runs_scan_in_bounded_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "blob.txt").write_text("a" * 300_000 + " wfxr__csview.8ac4de0")
            start = time.monotonic()
            found = pools.seen_ids([Path(tmp)], {"wfxr__csview.8ac4de0"})
            elapsed = time.monotonic() - start
        self.assertEqual(found, {"wfxr__csview.8ac4de0"})
        self.assertLess(elapsed, 5)

    def test_paths_the_filesystem_rejects_are_skipped_not_fatal(self):
        too_long = OSError(errno.ENAMETOOLONG, "File name too long")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "report.md").write_text("ran wfxr__csview.8ac4de0")
            real_is_file = Path.is_file

            def is_file(path):
                if path.name == "report.md":
                    raise too_long
                return real_is_file(path)

            with mock.patch.object(Path, "is_file", is_file):
                found = pools.seen_ids([Path(tmp)], {"wfxr__csview.8ac4de0"})
        self.assertEqual(found, set())

    def test_unreadable_files_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "report.md").write_text("ran wfxr__csview.8ac4de0")
            locked = Path(tmp, "locked.json")
            locked.write_text("sharkdp__hexyl.1234567")
            locked.chmod(0)
            sealed = Path(tmp, "sealed")
            sealed.mkdir()
            Path(sealed, "inner.json").write_text("sharkdp__hexyl.1234567")
            sealed.chmod(0)
            found = pools.seen_ids(
                [Path(tmp)], {"wfxr__csview.8ac4de0", "sharkdp__hexyl.1234567"}
            )
            locked.chmod(0o600)
            sealed.chmod(0o700)
        self.assertEqual(found, {"wfxr__csview.8ac4de0"})

    def test_test_named_paths_are_never_read_and_roots_under_tests_still_scan(self):
        known = {"wfxr__csview.8ac4de0", "sharkdp__hexyl.1234567"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "tests", "artifacts")
            (root / "tests").mkdir(parents=True)
            (root / "tests.json").write_text("sharkdp__hexyl.1234567")
            (root / "tests" / "test_x.md").write_text("sharkdp__hexyl.1234567")
            (root / "notes.md").write_text("wfxr__csview.8ac4de0")
            self.assertEqual(pools.seen_ids([root], known), {"wfxr__csview.8ac4de0"})
            (root / "notes.md").unlink()
            (root / "test_classification.py").write_text("# sharkdp__hexyl.1234567")
            self.assertEqual(pools.seen_ids([root], known), {"sharkdp__hexyl.1234567"})
            self.assertEqual(pools.seen_ids([root / "tests.json"], known), set())


if __name__ == "__main__":
    unittest.main()
