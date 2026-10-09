"""The real runner loop observes native events without changing v1 model interaction."""

import unittest

import test_procontract_delivery_runner as fixture
from test_procontract_execution_activity import completion


def turn_event(method, turn, status):
    return {
        "method": method,
        "params": {
            "threadId": "executor",
            "turn": {"id": turn, "status": status},
        },
    }


class ExecutionActivityRunnerTest(unittest.TestCase):
    def test_only_executor_completion_notifications_enter_the_bounded_receipt(self):
        event = completion()
        summary, methods = fixture.DeliveryRunnerTest().drive(
            reserve=0,
            environment_disconnects=(
                event,
                event,
                completion(exitCode=9, status="failed"),
                completion(thread="worker"),
                completion(turn="another-turn"),
                completion(type="reasoning"),
                {**completion(), "method": "item/commandExecution/terminalInteraction"},
            ),
        )
        self.assertEqual(
            (summary["execution_activity"], summary["delivery_budget"], methods),
            (
                {"executor_command_completions_observed": 3},
                {"reserve_secs": 0, "attempt": None},
                ["initialize", "thread/start", "turn/start"],
            ),
        )

    def test_inactive_and_previous_turn_notifications_do_not_count_during_repair(self):
        summary, methods = fixture.DeliveryRunnerTest().drive(
            reserve=0,
            environment_disconnects=(
                completion(),
                turn_event("turn/completed", "turn-1", "completed"),
                completion(),
                turn_event("turn/started", "repair-turn", "inProgress"),
                completion(),
                completion(turn="repair-turn"),
            ),
        )
        self.assertEqual(
            (summary["execution_activity"], methods),
            (
                {"executor_command_completions_observed": 2},
                ["initialize", "thread/start", "turn/start"],
            ),
        )

    def test_v1_keeps_its_four_facts_and_one_late_notice(self):
        summary, methods = fixture.DeliveryRunnerTest().drive(
            reserve=0,
            program={"schema": 1, "when": {"always": True}},
            environment_disconnects=(completion(),),
        )
        self.assertEqual(
            (
                summary["execution_activity"],
                summary["harness_program"]["last_input"],
                summary["delivery_budget"]["attempt"]["remaining_secs"],
                methods,
            ),
            (
                {"executor_command_completions_observed": 1},
                {
                    "deadline_secs": 18000,
                    "remaining_secs": 3600,
                    "turns_completed": 0,
                    "repairs_used": 0,
                },
                3600,
                ["initialize", "thread/start", "turn/start", "turn/steer"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
