"""A resting contract lane is not an ended executor; legacy interpretation stays frozen."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import procontract_harness_program as harness
import procontract_runtime_feedback as feedback
from procontract_delivery_budget import DeliveryBudget
from test_procontract_delivery_budget import FakeServer


class LifecycleTests(unittest.TestCase):
    def run_case(self, schema, action, phase, *, resting=True, active=True):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "harness.json").write_text(
                json.dumps(dict(schema=schema, action=action, when={"always": True}))
            )
            program = harness.load(path)
        server = FakeServer()
        budget = DeliveryBudget(deadline_secs=18000, reserve_secs=3600, program=program)
        turns = SimpleNamespace(
            active=active, thread_id="executor", turn_id="executor-turn", completed=0
        )
        budget.maybe_steer(
            server,
            turns,
            dict(phase=phase, repairs_used=0, resting=resting),
            lambda _: None,
            elapsed_secs=15000,
            executor_command_completions_observed=20,
        )
        return program, budget, server

    def test_resting_failed_lane_can_checkpoint_only_with_active_executor(self):
        for phase in ("abstained", "not_verified"):
            program, budget, server = self.run_case(3, "checkpoint", phase)
            self.assertEqual(
                (
                    program.interpreter,
                    len(server.calls),
                    budget.activation["last_eligibility"],
                ),
                ("lifecycle-steering-v3", 1, dict(eligible=True, reason="eligible")),
            )
            for options in ({"resting": False}, {"resting": None}, {"active": False}):
                self.assertEqual(
                    self.run_case(3, "checkpoint", phase, **options)[2].calls, []
                )
            self.assertEqual(self.run_case(2, "checkpoint", phase)[2].calls, [])
            self.assertEqual(self.run_case(3, "converge", phase)[2].calls, [])

    def test_checks_review_success_and_unknown_remain_protected(self):
        for phase in ("checking", "reviewing", "supported", "unknown"):
            self.assertEqual(self.run_case(3, "checkpoint", phase)[2].calls, [])

    def test_new_program_runs_same_predicate_with_distinct_interpreter_identity(self):
        v2, _, _ = self.run_case(2, "checkpoint", "working")
        v3, _, _ = self.run_case(3, "checkpoint", "working")
        self.assertNotEqual((v2.digest, v2.interpreter), (v3.digest, v3.interpreter))
        facts = dict(
            deadline_secs=18000,
            remaining_secs=1000,
            turns_completed=0,
            repairs_used=0,
            executor_command_completions_observed=10,
        )
        self.assertEqual((v2.evaluate(facts), v3.evaluate(facts)), (True, True))


if __name__ == "__main__":
    unittest.main()
