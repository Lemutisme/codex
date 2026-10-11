"""Exercise actual runner inputs: learned strategies must not become human requirements."""

from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import test_procontract_delivery_runner as delivery


class OnlineRunnerTests(unittest.TestCase):
    def drive(self, learning, *, expected_abort=None):
        actual = runner.run
        self.server = None

        def run(args):
            self.server = runner.AppServer.return_value
            if expected_abort is None:
                return actual(args, learning=learning)
            self.server.close.return_value = {"status": "exited", "returncode": 0}
            with self.assertRaises(expected_abort):
                actual(args, learning=learning)

        with mock.patch.object(runner, "run", side_effect=run):
            return delivery.DeliveryRunnerTest().drive(reserve=0)

    def learner(self):
        return SimpleNamespace(
            allocation={"executor_secs": 18000},
            initial={"execution": "LEARNED_STRATEGY_NOT_A_REQUIREMENT"},
            observe=mock.Mock(),
            poll=mock.Mock(),
            close=mock.Mock(return_value={"status": "observing"}),
        )

    def test_strategy_changes_context_but_preserves_exact_contract_request(self):
        learning = self.learner()
        summary, _ = self.drive(learning)
        requests = {c.args[0]: c.args[1] for c in self.server.request.call_args_list}
        self.assertEqual(
            requests["turn/start"]["input"],
            [{"type": "text", "text": "ordinary task", "text_elements": []}],
        )
        self.assertIn(
            learning.initial["execution"],
            requests["thread/start"]["developerInstructions"],
        )
        self.assertEqual(summary["online_learning"], {"status": "observing"})
        learning.close.assert_called_once()

    def test_real_runner_persists_typed_contract_failure_after_native_cleanup(self):
        from procontract_online_failure import (
            ContractUnavailable,
            contained_contract_failure,
        )

        status = {
            "phase": "abstained",
            "resting": True,
            "contract_id": None,
            "detail": "bad fixture",
        }
        learning = self.learner()
        learning.poll.side_effect = ContractUnavailable(status)
        summary, _ = self.drive(learning, expected_abort=ContractUnavailable)
        self.assertEqual(
            contained_contract_failure(summary),
            {"kind": "contract_unavailable", "quality": None, "reason": "bad fixture"},
        )
        self.server.close.assert_called_once()
        learning.close.assert_called_once()

    def test_native_is_closed_even_when_learning_cleanup_raises(self):
        learning = self.learner()
        learning.close.side_effect = RuntimeError("receipt publication failed")
        with self.assertRaisesRegex(RuntimeError, "receipt publication failed"):
            self.drive(learning)
        self.server.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
