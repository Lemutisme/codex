import unittest

import benchmark_native_goal as goal


class GoalLifecycleTests(unittest.TestCase):
    def test_idle_active_goal_continues(self):
        self.assertIsNone(goal.stop_reason({"status": "active"}, turn_active=False))

    def test_completion_drains_native_turn(self):
        self.assertIsNone(goal.stop_reason({"status": "complete"}, turn_active=True))
        self.assertEqual(goal.stop_reason({"status": "complete"}, turn_active=False),
                         "native_goal_complete")

    def test_lost_goal_is_not_completion(self):
        with self.assertRaises(RuntimeError):
            goal.stop_reason(None, turn_active=False)

    def test_baseline_has_no_procontract_switch(self):
        command = goal.command("/stock/codex")
        self.assertIn("goals", command)
        self.assertNotIn("pro_contract", " ".join(command))


if __name__ == "__main__":
    unittest.main()
