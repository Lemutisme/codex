"""Paid task attempts are distinct from evaluator retries of a frozen submission."""

import json
import tempfile
import unittest
from unittest import mock

import procontract_comparison as comparison
import test_procontract_rsi as fixtures


class TaskAttemptTest(unittest.TestCase):
    def test_new_stream_default_does_not_buy_another_invalid_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = fixtures.stream_campaign(tmp)
            tasks = fixtures.FakeTasks()
            host = fixtures.host(camp, tasks)
            version, task = host.incumbent(), host.order()[0]
            tasks.invalid_once.add(task)
            result = host.measure(version, task, "stream")
            resumed = fixtures.host(camp, tasks).measure(version, task, "stream")
            self.assertEqual(resumed, result)
            self.assertEqual(
                (
                    host.terms["budgets"]["task_attempts"],
                    result["validity"],
                    result["pass_rate"],
                    tasks.runs,
                ),
                (1, "invalid", None, [(version, task)]),
            )

    def test_legacy_campaign_keeps_two_attempts_and_then_reuses_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = fixtures.campaign(tmp)
            path = camp / "campaign.json"
            terms = json.loads(path.read_text())
            terms["budgets"].pop("task_attempts")
            path.write_text(json.dumps(terms))
            tasks = fixtures.FakeTasks()
            tasks.invalid_once.add(fixtures.DEV[0])
            host = fixtures.host(camp, tasks)
            version = host.incumbent()
            result = host.measure(version, fixtures.DEV[0], "dev")
            self.assertEqual(result["validity"], "valid")
            self.assertEqual(
                fixtures.host(camp, tasks).measure(version, fixtures.DEV[0], "dev"),
                result,
            )
            self.assertEqual(tasks.runs, [(version, fixtures.DEV[0])] * 2)

    def test_interrupted_attempts_do_not_escape_the_persistent_allowance(self):
        for limit in (1, 2):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as tmp:
                camp = fixtures.campaign(tmp, task_attempts=limit)
                tasks = fixtures.FakeTasks()
                host = fixtures.host(camp, tasks)
                version = host.incumbent()
                with mock.patch.object(
                    tasks, "run_and_label", side_effect=InterruptedError
                ) as paid:
                    for _ in range(limit):
                        with self.assertRaises(InterruptedError):
                            fixtures.host(camp, tasks).measure(
                                version, fixtures.DEV[0], "dev"
                            )
                    result = fixtures.host(camp, tasks).measure(
                        version, fixtures.DEV[0], "dev"
                    )
                    self.assertEqual(
                        (paid.call_count, result["validity"], result["cost_unknown"]),
                        (limit, "invalid", True),
                    )

    def test_invalid_persistent_limits_fail_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            host = fixtures.host(fixtures.campaign(tmp), tasks)
            for limit in (True, 0, 3, "1"):
                with (
                    self.subTest(limit=limit),
                    mock.patch.dict(host.terms["budgets"], task_attempts=limit),
                ):
                    with self.assertRaisesRegex(ValueError, "task_attempts"):
                        host.measure(host.incumbent(), fixtures.DEV[0], "dev")
            self.assertEqual(tasks.runs, [])

    def test_comparison_normalizes_legacy_allowance_not_the_entire_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            stream = fixtures.host(fixtures.stream_campaign(tmp), fixtures.FakeTasks())
            baseline = fixtures.host(
                fixtures.stream_campaign(tmp, name="baseline"), fixtures.FakeTasks()
            )
            stream.terms["budgets"].pop("task_attempts")
            baseline.terms["budgets"].update(task_attempts=2, research_steps=999)
            comparison.validate_comparison(stream, baseline)
            baseline.terms["budgets"]["task_attempts"] = 1
            with self.assertRaisesRegex(ValueError, "task_attempts"):
                comparison.validate_comparison(stream, baseline)


if __name__ == "__main__":
    unittest.main()
