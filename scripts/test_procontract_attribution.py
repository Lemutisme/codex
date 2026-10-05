import json
import tempfile
import unittest
from pathlib import Path

import procontract_attribution as attribution

ORACLE = [r"/workspace/executable", r"\./executable"]


def write_run(root: Path, calls: list[dict], tokens: int = 1000, thread="t1") -> Path:
    run = root
    rollout = run / "codex-home" / "sessions" / "2026" / f"rollout-{thread}.jsonl"
    rollout.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"payload": {"type": "message"}})] + [
        json.dumps({"payload": call}) for call in calls
    ]
    rollout.write_text("\n".join(lines) + "\nnot json\n")
    (run / "run.json").write_text(
        json.dumps(
            {
                "thread_id": thread,
                "turns_completed": 2,
                "status": {"phase": "passed", "class": "behavior", "repairs_used": 1},
                "cost": {"executor": {"total_tokens": tokens}},
            }
        )
    )
    return run


class FlipsTest(unittest.TestCase):
    def test_progress_and_regress_are_counted_by_family(self):
        parent = {
            "a.B.t1": False,
            "a.B.t2": False,
            "a.C.t3": True,
            "x": True,
            "s": True,
        }
        child = {"a.B.t1": True, "a.B.t2": True, "a.C.t3": False, "x": False, "n": True}
        moved = attribution.flips(parent, child)
        self.assertEqual(moved["progress"], ["a.B.t1", "a.B.t2"])
        self.assertEqual(moved["regress"], ["a.C.t3", "x"])
        self.assertEqual(moved["progress_families"], {"a.B": 2})
        self.assertEqual(moved["regress_families"], {"a.C": 1, "x": 1})


class BehaviorTest(unittest.TestCase):
    def test_calls_are_classified_and_workers_rollouts_are_ignored(self):
        calls = [
            {"type": "custom_tool_call", "input": "run /workspace/executable --x"},
            {"type": "function_call", "arguments": "cd src && ./executable -h"},
            {"type": "custom_tool_call", "input": "cargo test -q"},
            {"type": "custom_tool_call", "input": "diff a b"},
            {"type": "custom_tool_call", "input": "*** Update File: a.rs"},
            {"type": "custom_tool_call", "input": "ls"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            run = write_run(Path(tmp), calls, tokens=42)
            other = run / "codex-home" / "sessions" / "2026" / "rollout-worker.jsonl"
            other.write_text(json.dumps({"payload": calls[0]}) + "\n")
            stats = attribution.behavior(run, ORACLE)
        self.assertEqual(
            (stats["tool_calls"], stats["acquire"], stats["verify"], stats["produce"]),
            (6, 2, 2, 1),
        )
        self.assertEqual(
            (stats["tokens"], stats["turns"], stats["phase"], stats["repairs_used"]),
            (42, 2, "passed", 1),
        )

    def test_missing_files_mean_zeros(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = attribution.behavior(Path(tmp, "absent"), ORACLE)
        self.assertEqual(
            [stats[k] for k in attribution.BEHAVIOR_KEYS + ("turns",)], [0] * 6
        )
        self.assertIsNone(stats["phase"])


def stats(calls=100, acquire=50, verify=20, produce=10, tokens=1000):
    return {
        "tool_calls": calls,
        "acquire": acquire,
        "verify": verify,
        "produce": produce,
        "tokens": tokens,
        "turns": 2,
        "phase": "passed",
        "class": None,
        "repairs_used": 0,
    }


def row(delta, child_stats, noise=0.087):
    parent = {"task": "t", "pass_rate": 0.5}
    child = {"task": "t", "pass_rate": 0.5 + delta}
    return attribution.attribute(
        parent, child, {"a.b.x": False}, {"a.b.x": True}, stats(), child_stats, noise
    )


class AttributeTest(unittest.TestCase):
    def test_readings(self):
        cases = [
            (0.05, stats(acquire=300), "behavior changed · outcome within noise"),
            (0.2, stats(calls=110), "behavior unchanged · outcome progress"),
            (-0.2, stats(acquire=30), "behavior changed · outcome regress"),
            (0.2, stats(tokens=2500), "behavior changed · outcome progress"),
            (-0.09, stats(), "behavior unchanged · outcome regress"),
            (0.01, stats(), "behavior unchanged · outcome within noise"),
        ]
        for delta, child, reading in cases:
            self.assertEqual(row(delta, child)["reading"], reading)

    def test_row_carries_flips_and_ratios(self):
        result = row(0.2, stats(acquire=150))
        self.assertEqual((result["progress"], result["regress"]), (1, 0))
        self.assertEqual(result["top_progress"], [("a.b", 1)])
        self.assertAlmostEqual(result["ratios"]["acquire"], 3.0)


class RenderTest(unittest.TestCase):
    def test_document_has_guide_experiment_table_and_totals(self):
        text = "## Hypothesis\nQuery more.\n## Prediction\nMore acquire.\n## Risks\nr\n"
        rows = [row(0.2, stats(acquire=150, tokens=2000)), row(-0.1, stats(acquire=30))]
        doc = attribution.render("a" * 64, "b" * 64, rows, text, 0.087, "repeat runs")
        self.assertIn("aaaaaaaaaaaa", doc)
        self.assertIn("Noise floor: 0.087 (repeat runs)", doc)
        self.assertIn("Query more.", doc)
        self.assertIn("More acquire.", doc)
        self.assertNotIn("## Risks", doc)
        self.assertIn("| t | 0.500 | 0.700 | +0.200 | 1 | 0 |", doc)
        self.assertIn("top progress families: a.b (1)", doc)
        self.assertIn(
            "Totals: mean delta +0.050 over 2 tasks; executor token ratio 1.50.", doc
        )

    def test_missing_experiment_still_renders(self):
        doc = attribution.render("a" * 64, "b" * 64, [], "", 0.1, "s")
        self.assertNotIn("Hypothesis", doc.replace("Hypothesis)", ""))


if __name__ == "__main__":
    unittest.main()
