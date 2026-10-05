import unittest

import procontract_outcomes as po


def run(name, twin, passed, parent=None, missing=(), purpose="dev"):
    """passed: ids that pass; every id in `all` below not in passed fails, except `missing`."""
    items = {
        i: {"passed": i in passed, "message": ""} for i in ALL if i not in missing
    }
    return {"name": name, "version": "v" + twin, "twin": twin, "parent": parent,
            "purpose": purpose, "outcomes": items}


ALL = ["a.x.1", "a.x.2", "a.y.1", "b.z.1", "b.z.2", "c"]


class MatrixTest(unittest.TestCase):
    def test_classification_with_missing_items(self):
        runs = [
            run("r1", "t0", {"a.x.1", "a.x.2", "b.z.1"}),
            run("r2", "t1", {"a.x.1", "b.z.1", "b.z.2"}, parent="t0", missing=("c",)),
        ]
        m = po.matrix(runs)
        self.assertEqual(m["items"], 5)
        self.assertEqual(m["always"], ["a.x.1", "b.z.1"])
        self.assertEqual(m["floor"], ["a.y.1"])
        self.assertEqual(m["sensitive"], ["a.x.2", "b.z.2"])
        self.assertEqual([r["items"] for r in m["runs"]], [6, 5])
        self.assertAlmostEqual(m["runs"][0]["pass_rate"], 3 / 6)
        self.assertAlmostEqual(m["runs"][1]["pass_rate"], 3 / 5)

    def test_families(self):
        runs = [run("r1", "t0", {"a.x.1", "a.x.2"}), run("r2", "t1", {"a.x.1", "b.z.1"})]
        fams = {f["family"]: f for f in po.matrix(runs)["families"]}
        self.assertEqual(set(fams), {"a.x", "a.y", "b.z", "c"})
        ax = fams["a.x"]
        self.assertEqual((ax["n"], ax["always"], ax["sensitive"], ax["floor"]), (2, 1, 1, 0))
        self.assertEqual(ax["passed"], {"r1": 2, "r2": 1})
        self.assertEqual(fams["c"]["floor"], 1)

    def test_replicates(self):
        runs = [
            run("p1", "t0", {"a.x.1", "a.x.2"}),
            run("p2", "t0", {"a.x.1", "b.z.1", "b.z.2", "c"}),
            run("c1", "t1", {"a.x.1"}, parent="t0"),
        ]
        reps = po.matrix(runs)["replicates"]
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["runs"], ["p1", "p2"])
        self.assertAlmostEqual(reps[0]["spread"], 4 / 6 - 2 / 6)
        self.assertEqual(reps[0]["disagree"], ["a.x.2", "b.z.1", "b.z.2", "c"])

    def test_edges_pair_every_parent_replicate(self):
        runs = [
            run("p1", "t0", {"a.x.1"}),
            run("p2", "t0", {"a.x.2"}),
            run("c1", "t1", {"a.x.1", "a.x.2", "a.y.1"}, parent="t0"),
        ]
        edges = po.matrix(runs)["edges"]
        self.assertEqual([(e["child"], e["parent"]) for e in edges], [("c1", "p1"), ("c1", "p2")])
        self.assertEqual(edges[0]["progress"], ["a.x.2", "a.y.1"])
        self.assertEqual(edges[0]["regress"], [])
        self.assertEqual(edges[1]["by_family"]["progress"], {"a.x": 1, "a.y": 1})

    def test_empty(self):
        m = po.matrix([])
        self.assertEqual((m["items"], m["floor"], m["edges"]), (0, [], []))
        self.assertIn("# Outcomes: t", po.render("t", m))


class RenderTest(unittest.TestCase):
    def test_contents(self):
        runs = [
            run("p1", "t0", {"a.x.1"}),
            run("p2", "t0", {"a.x.1", "a.x.2"}),
            run("c1", "t1", {"a.x.1", "b.z.1"}, parent="t0"),
        ]
        text = po.render("task-a", po.matrix(runs))
        self.assertIn("# Outcomes: task-a", text)
        self.assertIn("floor (failed by every run): 3", text)
        self.assertIn("sensitive: 2", text)
        self.assertIn("## Replicates", text)
        self.assertIn("| c1 | p1 | 1 | 0 |", text)
        self.assertNotIn("omitted", text)
        self.assertLess(text.index("| b.z |"), text.index("| a.x |"))

    def test_omission_note_when_capped(self):
        ids = [f"f{i:02d}.t" for i in range(po.MAX_ROWS + 4)]
        mk = lambda n, p: {"name": n, "version": n, "twin": n, "parent": None, "purpose": "dev",
                           "outcomes": {i: {"passed": i in p, "message": ""} for i in ids}}
        text = po.render("t", po.matrix([mk("r1", set()), mk("r2", set(ids[:2]))]))
        self.assertIn("4 more families omitted.", text)

    def test_no_replicates_or_edges_stated(self):
        text = po.render("t", po.matrix([run("r1", "t0", {"c"})]))
        self.assertIn("unmeasured", text)
        self.assertIn("No run has a parent", text)


if __name__ == "__main__":
    unittest.main()
