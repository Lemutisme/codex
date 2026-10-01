import tempfile
import unittest
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
        self.assertNotIn("o1", pools.commitment("salt", ["o1__r1.abc0001"]))
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


if __name__ == "__main__":
    unittest.main()
