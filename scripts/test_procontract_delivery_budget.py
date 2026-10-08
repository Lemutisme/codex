import json
import unittest
from types import SimpleNamespace

from procontract_delivery_budget import DeliveryBudget


class FakeServer:
    def __init__(self, response=None, error=None):
        self.response = {"turnId": "executor-turn"} if response is None else response
        self.error = error
        self.calls = []

    def request(self, method, params, handle, timeout):
        self.calls.append((method, params, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class DeliveryBudgetTest(unittest.TestCase):
    def test_invalid_budgets_fail_before_any_request(self):
        for deadline, reserve in [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)]:
            with self.subTest(deadline=deadline, reserve=reserve):
                with self.assertRaises(ValueError):
                    DeliveryBudget(deadline_secs=deadline, reserve_secs=reserve)

    def setUp(self):
        self.budget = DeliveryBudget(deadline_secs=100, reserve_secs=20)
        self.server = FakeServer()
        self.turns = SimpleNamespace(
            active=True, thread_id="executor", turn_id="executor-turn"
        )

    def steer(self, elapsed=80, status=None):
        self.budget.maybe_steer(
            self.server, self.turns, status, lambda message: None, elapsed_secs=elapsed
        )

    def test_disabled_budget_never_sends_a_notice(self):
        self.budget = DeliveryBudget(deadline_secs=100)
        self.steer(elapsed=99)
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.budget.summary(), {"reserve_secs": 0, "attempt": None})

    def test_notice_is_fenced_bounded_and_sent_once_at_the_reserve(self):
        self.steer(elapsed=79)
        self.assertEqual(self.server.calls, [])
        self.steer(status={"phase": "working"})
        self.turns.turn_id = "repair-turn"
        self.steer(elapsed=90)
        self.assertEqual(len(self.server.calls), 1)
        method, params, timeout = self.server.calls[0]
        self.assertEqual(
            (method, params["threadId"], params["expectedTurnId"], timeout),
            ("turn/steer", "executor", "executor-turn", 10.0),
        )
        self.assertLess(len(params["input"][0]["text"]), 1024)
        self.assertEqual(
            json.loads(json.dumps(self.budget.summary())),
            {
                "reserve_secs": 20,
                "attempt": {
                    "turn_id": "executor-turn",
                    "remaining_secs": 20,
                    "outcome": "accepted",
                },
            },
        )

    def test_only_active_executor_with_known_identity_can_be_steered(self):
        for field, value in [("active", False), ("thread_id", None), ("turn_id", None)]:
            with self.subTest(field=field):
                previous = getattr(self.turns, field)
                setattr(self.turns, field, value)
                self.steer()
                setattr(self.turns, field, previous)
        self.assertEqual(self.server.calls, [])
        self.steer()
        self.assertEqual(len(self.server.calls), 1)

    def test_checks_review_and_unknown_status_do_not_consume_the_attempt(self):
        for status in [
            {"phase": "checking"},
            {"phase": "reviewing"},
            {"phase": "supported"},
            {"phase": "unknown"},
            {},
            "working",
        ]:
            with self.subTest(status=status):
                self.steer(status=status)
        self.assertEqual(self.server.calls, [])
        self.steer(status={"phase": "repairing"})
        self.assertEqual(len(self.server.calls), 1)

    def test_deadline_does_not_allow_a_new_steer(self):
        for elapsed in [100, 101]:
            self.steer(elapsed=elapsed)
        self.assertEqual(self.server.calls, [])

    def test_rpc_timeout_is_within_the_remaining_budget(self):
        self.steer(elapsed=99.75)
        self.assertEqual(self.server.calls[0][2], 0.25)

    def test_errors_and_timeouts_are_bounded_and_never_retried(self):
        for error, outcome in [
            (TimeoutError("x" * 1000), "timeout"),
            (RuntimeError("no active turn"), "error"),
            (BrokenPipeError("closed"), "error"),
        ]:
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.server.error = error
                self.steer()
                self.steer(elapsed=90)
                self.assertEqual(len(self.server.calls), 1)
                self.assertEqual(self.budget.summary()["attempt"]["outcome"], outcome)
                self.assertLessEqual(
                    len(self.budget.summary()["attempt"]["error"]), 512
                )

    def test_mismatched_or_malformed_acknowledgement_is_not_acceptance(self):
        for response in [{"turnId": "another-turn"}, {}, "accepted"]:
            with self.subTest(response=response):
                self.setUp()
                self.server.response = response
                self.steer()
                self.steer(elapsed=90)
                self.assertEqual(len(self.server.calls), 1)
                self.assertEqual(self.budget.summary()["attempt"]["outcome"], "error")
