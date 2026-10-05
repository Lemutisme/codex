import unittest

import procontract_calibration as calibration

POLICY = {"min_sealed_qualified": 4, "min_success_permille": 500}


def receipts(sealed: list[str], others: list[str] = ("pass",), exits=None) -> dict:
    steps = [{"step": "build", "outcome": others[0]}]
    steps += [
        {"step": f"public:p{index}", "outcome": outcome}
        for index, outcome in enumerate(others[1:])
    ]
    steps += [
        {
            "step": f"sealed:s{index}",
            "outcome": outcome,
            "reference_exit": (exits or [0] * len(sealed))[index],
        }
        for index, outcome in enumerate(sealed)
    ]
    return {"steps": steps, "complete": True}


def row(instance: str, sealed: list[str], hidden: float) -> dict:
    return {
        "instance": instance,
        "subject": f"{instance}-{hidden}",
        "hidden": hidden,
        "facts": calibration.tally(receipts(sealed)),
        "policy": POLICY,
    }


class TallyTest(unittest.TestCase):
    def test_tally_counts_like_the_lanes_sealed_tally(self):
        facts = calibration.tally(
            receipts(["pass", "fail", "unqualified", "pass"], exits=[0, 2, 0, 0])
        )
        self.assertEqual(
            facts,
            {
                "complete": True,
                "mechanical_ok": True,
                "qualified": 3,
                "passed": 2,
                "succeeded": 2,
                "unqualified": 1,
            },
        )

    def test_a_failed_public_case_or_build_fails_the_mechanical_gate(self):
        facts = calibration.tally(receipts(["pass"] * 4, others=["pass", "fail"]))
        self.assertFalse(facts["mechanical_ok"])
        self.assertFalse(calibration.mechanically_supported(facts, POLICY, 800))

    def test_the_gate_needs_enough_qualified_and_successful_cases(self):
        enough = calibration.tally(receipts(["pass"] * 4))
        self.assertTrue(calibration.mechanically_supported(enough, POLICY, 1000))
        few = calibration.tally(receipts(["pass"] * 3 + ["unqualified"]))
        self.assertFalse(calibration.mechanically_supported(few, POLICY, 800))
        failing_paths = calibration.tally(receipts(["pass"] * 4, exits=[0, 1, 1, 1]))
        self.assertFalse(calibration.mechanically_supported(failing_paths, POLICY, 800))
        three_of_four = calibration.tally(receipts(["pass"] * 3 + ["fail"]))
        self.assertTrue(calibration.mechanically_supported(three_of_four, POLICY, 750))
        self.assertFalse(calibration.mechanically_supported(three_of_four, POLICY, 760))


class ThetaTest(unittest.TestCase):
    def test_theta_is_the_smallest_with_few_missed_defects(self):
        rows = [
            row("a", ["pass"] * 10, 0.99),
            row("b", ["pass"] * 9 + ["fail"], 0.70),
            row("c", ["pass"] * 10, 0.97),
        ]
        rows = [
            {**r, "policy": {"min_sealed_qualified": 10, "min_success_permille": 0}}
            for r in rows
        ]
        # At 900 the 0.70 subject is supported (1 of 3 missed); at 910 it is not.
        self.assertEqual(calibration.missed_rate(rows, 900), (1 / 3, 3))
        self.assertEqual(calibration.choose_theta(rows), 910)

    def test_no_theta_when_even_perfect_sealed_scores_miss(self):
        rows = [
            {**row("a", ["pass"] * 4, 0.5), "policy": POLICY},
            {**row("b", ["pass"] * 4, 0.6), "policy": POLICY},
        ]
        self.assertIsNone(calibration.choose_theta(rows))


class StatisticsTest(unittest.TestCase):
    def test_spearman_handles_ties_and_degenerate_input(self):
        self.assertAlmostEqual(
            calibration.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0
        )
        self.assertAlmostEqual(calibration.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertEqual(calibration.ranks([5, 1, 5, 2]), [3.5, 1.0, 3.5, 2.0])
        self.assertIsNone(calibration.spearman([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(calibration.spearman([1, 2], [1, 2]))

    def test_the_split_is_seeded_and_disjoint(self):
        names = [f"t{index}" for index in range(30)]
        first = calibration.split(names, 7)
        self.assertEqual(first, calibration.split(list(reversed(names)), 7))
        self.assertEqual((len(first[0]), len(first[1])), (20, 10))
        self.assertFalse(set(first[0]) & set(first[1]))

    def test_the_report_applies_the_gate(self):
        good = [row(f"t{index}", ["pass"] * 4, 0.99) for index in range(30)] + [
            row(f"t{index}", ["pass", "fail", "fail", "fail"], 0.4 + index / 100)
            for index in range(30)
        ]
        controls = {
            f"t{index}": {
                "negative": receipts(["pass"] * 4),
                "positive": receipts(["fail"] * 4),
            }
            for index in range(30)
        }
        result = calibration.report(good, controls, seed=3)
        self.assertEqual(result["controls"]["negative_false_alarm_rate"], 0.0)
        self.assertEqual(result["controls"]["positive_catch_rate"], 1.0)
        self.assertEqual(result["theta_permille"], 800)
        self.assertTrue(result["gate"]["passed"], result["gate"])


if __name__ == "__main__":
    unittest.main()
