"""Controller action/fence tests: fake transport only, never a model call."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import procontract_harness_program as programs
from procontract_delivery_budget import DeliveryBudget
from test_procontract_delivery_budget import FakeServer

_KNOWN_STATUS = object()


class DeliveryBudgetV2Test(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bundle = Path(directory.name)
        self.turns = SimpleNamespace(
            active=True, thread_id="executor", turn_id="executor-turn", completed=0
        )
        self.server = FakeServer()

    def budget(
        self, action="checkpoint", *, schema=2, when=None, deadline=18000, reserve=3600
    ):
        document = {
            "schema": schema,
            "when": {"always": True} if when is None else when,
        }
        if schema == 2:
            document["action"] = action
        (self.bundle / "harness.json").write_text(json.dumps(document))
        return DeliveryBudget(
            deadline_secs=deadline,
            reserve_secs=reserve,
            program=programs.load(self.bundle),
        )

    def steer(self, budget, elapsed=301, *, status=_KNOWN_STATUS, count=3):
        if status is _KNOWN_STATUS:
            status = {"phase": "working", "repairs_used": 0}
        budget.maybe_steer(
            self.server,
            self.turns,
            status,
            lambda message: None,
            elapsed_secs=elapsed,
            executor_command_completions_observed=count,
        )

    def test_early_checkpoint_is_fenced_in_the_same_short_task_without_a_reserve(self):
        budget = self.budget(deadline=1800, reserve=0)
        self.steer(budget, 180)
        method, params, timeout = self.server.calls[0]
        self.assertEqual(
            (method, params["threadId"], params["expectedTurnId"], timeout),
            ("turn/steer", "executor", "executor-turn", 10.0),
        )
        notice = params["input"][0]["text"]
        self.assertIn("Then continue the task", notice)
        self.assertNotIn("Stop broad exploration", notice)
        self.assertLess(len(notice.encode()), 1024)
        self.assertEqual(
            budget.summary(),
            {
                "reserve_secs": 0,
                "attempt": {
                    "turn_id": "executor-turn",
                    "remaining_secs": 1620,
                    "outcome": "accepted",
                    "action": "checkpoint",
                },
            },
        )
        self.assertEqual(
            budget.activation,
            {
                "sha256": budget.program.digest,
                "interpreter": "bounded-steering-v2",
                "action": "checkpoint",
                "evaluations": 1,
                "last_input": {
                    "deadline_secs": 1800,
                    "remaining_secs": 1620,
                    "turns_completed": 0,
                    "repairs_used": 0,
                    "executor_command_completions_observed": 3,
                },
                "last_decision": True,
                "last_eligibility": {"eligible": True, "reason": "eligible"},
            },
        )

    def test_v1_early_always_remains_blocked_and_ignores_the_new_counter(self):
        budget = self.budget(schema=1)
        self.steer(budget, status=None, count="not a counter")
        self.assertEqual(self.server.calls, [])
        self.assertEqual(
            budget.activation,
            {
                "sha256": budget.program.digest,
                "interpreter": "convergence-v1",
                "evaluations": 1,
                "last_input": {
                    "deadline_secs": 18000,
                    "remaining_secs": 17699,
                    "turns_completed": 0,
                    "repairs_used": 0,
                },
                "last_decision": True,
            },
        )
        self.steer(budget, 14400, status=None, count=None)
        self.assertEqual(len(self.server.calls), 1)
        self.assertNotIn("action", budget.summary()["attempt"])

    def test_checkpoint_window_has_closed_warmup_and_remaining_boundaries(self):
        for deadline, before, first, last in [
            (18000, 299.9, 300, 17940),
            (100, 9.9, 10, 90),
        ]:
            for elapsed, reason in [
                (before, "checkpoint_warmup"),
                (first, "eligible"),
                (last, "eligible"),
                (last + 0.1, "checkpoint_reserve"),
                (deadline, "deadline_expired"),
            ]:
                with self.subTest(deadline=deadline, elapsed=elapsed):
                    self.server = FakeServer()
                    budget = self.budget(deadline=deadline, reserve=0)
                    self.steer(budget, elapsed)
                    self.assertEqual(
                        budget.activation["last_eligibility"],
                        {"eligible": reason == "eligible", "reason": reason},
                    )
                    self.assertEqual(len(self.server.calls), int(reason == "eligible"))

    def test_converge_obeys_supplied_reserve_and_fixed_host_cap(self):
        for deadline, reserve, earliest in [
            (18000, 9000, 14400),
            (100, 80, 75),
            (100, 10, 90),
        ]:
            with self.subTest(deadline=deadline, reserve=reserve):
                self.server = FakeServer()
                budget = self.budget("converge", deadline=deadline, reserve=reserve)
                self.steer(budget, earliest - 0.01)
                self.assertEqual(self.server.calls, [])
                self.assertEqual(
                    budget.activation["last_eligibility"],
                    {"eligible": False, "reason": "convergence_window"},
                )
                self.steer(budget, earliest)
                self.assertEqual(len(self.server.calls), 1)
                self.assertIn(
                    "Stop broad exploration",
                    self.server.calls[0][1]["input"][0]["text"],
                )
        self.server = FakeServer()
        self.steer(self.budget("converge", reserve=0), 17999)
        self.assertEqual(self.server.calls, [])

    def test_predicate_and_eligibility_are_independent_and_false_does_not_consume(self):
        budget = self.budget(when={"command_completions_observed_gte": 4})
        self.steer(budget, count=3)
        self.assertEqual(
            (budget.activation["last_decision"], budget.activation["last_eligibility"]),
            (False, {"eligible": True, "reason": "eligible"}),
        )
        self.assertIsNone(budget.summary()["attempt"])
        self.steer(budget, count=4)
        self.assertEqual(len(self.server.calls), 1)

    def test_missing_and_malformed_counter_fail_closed_without_copying_input(self):
        for count in [
            None,
            True,
            -1,
            1.0,
            programs.MAX_INTEGER + 1,
            "bad",
            {"bad": "x" * 9000},
        ]:
            with self.subTest(count_type=type(count).__name__):
                budget = self.budget()
                self.steer(budget, count=count)
                self.assertEqual(
                    (
                        budget.activation["last_input"],
                        budget.activation["last_decision"],
                        budget.activation["evaluations"],
                        budget.activation["last_eligibility"],
                    ),
                    (None, None, 0, {"eligible": False, "reason": "invalid_facts"}),
                )
                self.assertIsNone(budget.summary()["attempt"])
        self.assertEqual(self.server.calls, [])

    def test_protected_phase_and_executor_identity_fences_do_not_consume(self):
        for action in ("checkpoint", "converge"):
            budget = self.budget(action)
            for status in [
                {"phase": "checking", "repairs_used": 0},
                {"phase": "reviewing", "repairs_used": 0},
                {"phase": "unknown", "repairs_used": 0},
                {"repairs_used": 0},
            ]:
                self.steer(budget, 14400, status=status)
                self.assertEqual(
                    budget.activation["last_eligibility"]["reason"], "protected_phase"
                )
            for field, invalid in [
                ("active", False),
                ("thread_id", None),
                ("turn_id", None),
            ]:
                previous = getattr(self.turns, field)
                setattr(self.turns, field, invalid)
                self.steer(budget, 14400)
                setattr(self.turns, field, previous)
                self.assertEqual(
                    budget.activation["last_eligibility"]["reason"], "inactive_executor"
                )
            self.assertIsNone(budget.summary()["attempt"])
        self.assertEqual(self.server.calls, [])

    def test_v2_unknown_repair_status_is_not_observed_zero(self):
        for action in ("checkpoint", "converge"):
            for status in [
                None,
                {},
                "working",
                {"phase": "working"},
                *(
                    {"phase": "working", "repairs_used": value}
                    for value in (None, True, -1, 1.0, programs.MAX_INTEGER + 1)
                ),
            ]:
                with self.subTest(action=action, status=status):
                    self.server = FakeServer()
                    budget = self.budget(action, when={"not": {"repairs_used_gte": 1}})
                    self.steer(budget, 14400, status=status)
                    self.assertEqual(
                        (
                            budget.activation["last_input"],
                            budget.activation["last_decision"],
                            budget.activation["evaluations"],
                            budget.activation["last_eligibility"],
                        ),
                        (None, None, 0, {"eligible": False, "reason": "invalid_facts"}),
                    )
                    self.assertEqual(self.server.calls, [])
                    self.assertIsNone(budget.summary()["attempt"])
                    self.steer(
                        budget, 14401, status={"phase": "working", "repairs_used": 0}
                    )
                    self.assertEqual(
                        (
                            budget.activation["last_decision"],
                            budget.summary()["attempt"]["outcome"],
                        ),
                        (True, "accepted"),
                    )
                    self.assertEqual(len(self.server.calls), 1)

    def test_each_action_has_one_total_attempt_even_after_timeout_or_turn_change(self):
        for action in ("checkpoint", "converge"):
            for error, outcome in [
                (None, "accepted"),
                (TimeoutError("lost"), "timeout"),
                (RuntimeError("stale"), "error"),
            ]:
                with self.subTest(action=action, outcome=outcome):
                    self.turns.turn_id = "executor-turn"
                    self.server = FakeServer(error=error)
                    budget = self.budget(action)
                    self.steer(budget, 14400)
                    self.turns.turn_id = "next-turn"
                    self.steer(budget, 14401)
                    self.assertEqual(len(self.server.calls), 1)
                    self.assertEqual(budget.summary()["attempt"]["outcome"], outcome)

    def test_v2_mismatched_ack_is_not_acceptance_and_timeout_is_deadline_bounded(self):
        self.server = FakeServer(response={"turnId": "another-turn"})
        budget = self.budget("converge")
        self.steer(budget, 17999.75)
        self.steer(budget, 17999.8)
        self.assertEqual(len(self.server.calls), 1)
        self.assertEqual(self.server.calls[0][2], 0.25)
        self.assertEqual(budget.summary()["attempt"]["outcome"], "error")

    def test_v2_evaluation_receipt_saturates_without_changing_predicate_decisions(self):
        budget = self.budget(when={"always": False})
        budget.activation["evaluations"] = programs.MAX_INTEGER - 1
        self.steer(budget, count=programs.MAX_INTEGER)
        self.steer(budget, count=programs.MAX_INTEGER)
        self.assertEqual(
            (
                budget.activation["evaluations"],
                budget.activation["last_decision"],
                budget.activation["last_input"][
                    "executor_command_completions_observed"
                ],
            ),
            (programs.MAX_INTEGER, False, programs.MAX_INTEGER),
        )
        self.assertEqual(self.server.calls, [])
