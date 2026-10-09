"""Native envelope filtering and bounded activity facts, never inferred tool progress."""

import copy
import json
import unittest
from unittest import mock

import procontract_execution_activity as activity


def completion(*, thread="executor", turn="turn-1", **item):
    return {
        "method": "item/completed",
        "params": {
            "threadId": thread,
            "turnId": turn,
            "item": {"type": "commandExecution", "id": "command-1", **item},
        },
    }


class ExecutorActivityTest(unittest.TestCase):
    def setUp(self):
        self.activity = activity.ExecutorActivity()

    def observe(self, event):
        self.activity.observe(event, thread_id="executor", turn_id="turn-1")

    def test_duplicate_and_failed_completions_are_notifications_not_unique_successes(
        self,
    ):
        event = completion(status="completed", exitCode=0)
        self.observe(event)
        self.observe(event)
        self.observe(completion(status="failed", exitCode=7))
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 3}
        )

    def test_only_typed_matching_notifications_count(self):
        unrelated = [
            completion(thread="worker"),
            completion(turn="previous-turn"),
            completion(type="reasoning"),
            completion(type="agentMessage", text='{"type":"commandExecution"}'),
            {**completion(), "method": "item/started"},
            {**completion(), "method": "item/commandExecution/terminalInteraction"},
            {**completion(), "method": "rawResponseItem/completed"},
            {**completion(), "id": 17},
        ]
        for event in unrelated:
            self.observe(event)
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 0}
        )
        self.observe(completion())
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 1}
        )

    def test_malformed_envelopes_and_absent_executor_identity_are_ignored(self):
        for value in (None, False, 0, "", [], {}):
            with self.subTest(value=value):
                self.observe(value)
                self.observe({**completion(), "params": value})
                event = completion()
                event["params"]["item"] = value
                self.observe(event)
                self.observe(completion(id=value))
                self.activity.observe(completion(), thread_id=value, turn_id="turn-1")
                self.activity.observe(completion(), thread_id="executor", turn_id=value)
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 0}
        )

    def test_command_text_output_and_large_payloads_are_not_interpreted_or_retained(
        self,
    ):
        event = completion(
            command="exec_command write_stdin " * 10000,
            aggregatedOutput="SECRET" * 10000,
        )
        before = copy.deepcopy(event)
        self.observe(event)
        summary = self.activity.summary()
        self.assertEqual(summary, {"executor_command_completions_observed": 1})
        self.assertEqual(event, before)
        self.assertLess(len(json.dumps(summary)), 128)
        summary["executor_command_completions_observed"] = 999
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 1}
        )

    def test_counter_saturates_without_retaining_notification_ids(self):
        with mock.patch.object(activity, "MAX_COUNTER", 2):
            for number in range(1000):
                self.observe(completion(id=str(number)))
        self.assertEqual(
            self.activity.summary(), {"executor_command_completions_observed": 2}
        )


if __name__ == "__main__":
    unittest.main()
