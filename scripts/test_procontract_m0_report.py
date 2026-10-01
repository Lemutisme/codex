import unittest

import procontract_m0_report as report


def row(
    task,
    arm,
    role,
    verdict=None,
    solved=False,
    validity="valid",
    score=80.0,
    validated=None,
):
    return {
        "task": task,
        "arm": arm,
        "run_id": f"{task}-{arm}",
        "role": role,
        "verdict": verdict,
        "validity": validity,
        "solved": solved,
        "score": score,
        "validated": validated,
        "cost_total": 10,
    }


class EstimandTest(unittest.TestCase):
    def test_estimands_use_the_specified_denominators(self):
        rows = [
            row("a", "on", "judged", "support", solved=True),
            row("b", "on", "judged", "support", solved=False),
            row("c", "on", "judged", "defeat", solved=True, validated=True),
            row("d", "on", "judged", "support", validity="invalid", solved=None),
            row("a", "on", "final_workspace", solved=True, score=100.0),
            row("a", "off", "final_workspace", solved=False, score=90.0),
        ]
        result = report.estimands(rows, {"a": 67.0}, seed=1)

        self.assertEqual(result["p_solved_given_supported"]["point"], 0.5)
        self.assertEqual(result["p_solved_given_supported"]["n"], 2)
        self.assertEqual(result["missed_defect_rate"]["point"], 0.5)
        self.assertEqual(result["disagreement"]["point"], 1.0)
        self.assertEqual(result["validated_defeats"]["point"], 1.0)
        self.assertEqual(result["excluded"]["invalid"], 1)
        self.assertEqual(
            result["solved_by_arm"],
            {
                "on": {"solved": 1, "valid": 1, "invalid": 0},
                "off": {"solved": 0, "valid": 1, "invalid": 0},
            },
        )
        self.assertEqual(result["score_above_null"]["on"], 33.0)

    def test_clustered_ci_is_deterministic_and_brackets_the_point(self):
        values = {"a": [1.0, 1.0], "b": [0.0], "c": [1.0]}
        point, low, high = report.clustered_ci(values, seed=3)
        self.assertEqual((point, low, high), report.clustered_ci(values, seed=3))
        self.assertTrue(low <= point <= high)


if __name__ == "__main__":
    unittest.main()
