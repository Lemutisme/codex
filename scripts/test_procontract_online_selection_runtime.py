"""Two runtime episodes exercise reward selection and recursive M/H consumption."""

from concurrent.futures import Future
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_online as online
from procontract_online_lineage import Lineage
from procontract_online_runtime import OnlineRuntime
import procontract_online_selection as selection
from test_procontract_online import candidate


class SelectedRuntimeTests(unittest.TestCase):
    def test_reward_routes_next_runtime_to_child_without_promoting_incumbent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lineage = Lineage(root / "lineage", selection_scope="a" * 64)
            draw = 0
            previous = online.seed()
            for index in range(2):
                episode = str(index)
                with mock.patch.object(
                    selection.random.SystemRandom, "random", return_value=draw
                ):
                    allocation = lineage.begin(episode, 14400, 900)
                runtime = OnlineRuntime(
                    lineage,
                    episode,
                    root / episode,
                    Path("/fixture"),
                    {},
                    "FAKE",
                    allocation=allocation,
                )
                try:
                    self.assertEqual(runtime.initial, previous)
                    turn = SimpleNamespace(
                        active=True, thread_id="t", turn_id="u", completed=0
                    )
                    status = {
                        "phase": "working",
                        "resting": False,
                        "repairs_used": 0,
                        "contract_id": "c",
                    }
                    server = mock.Mock()
                    server.request.return_value = {"turnId": "u"}
                    for _ in range(4):
                        runtime.observe(
                            {
                                "method": "item/completed",
                                "params": {
                                    "threadId": "t",
                                    "item": {
                                        "type": "commandExecution",
                                        "command": "build",
                                        "exitCode": 1,
                                    },
                                },
                            },
                            "t",
                        )
                    future = Future()
                    with mock.patch.object(
                        runtime.pool, "submit", return_value=future
                    ) as submit:
                        runtime.poll(
                            server, turn, status, mock.Mock(), elapsed_secs=100
                        )
                    packet = submit.call_args.args[3]
                    self.assertEqual(
                        packet["program"]["research"], previous["research"]
                    )
                    self.assertEqual(packet["observations"]["failed_commands"], 4)
                    if index:
                        self.assertEqual(packet["past_rewards"][0]["resolved"], 4)
                    successor, raw = candidate(previous, episode)
                    proposed = json.loads(raw)
                    proposed["prediction"] = json.dumps(
                        {
                            "metric": "canonical_fraction",
                            "direction": "at_least",
                            "threshold": 0.5,
                        }
                    )
                    future.set_result(
                        (
                            online.encoded(proposed),
                            {"status": "completed", "elapsed_secs": 5},
                        )
                    )
                    runtime.poll(server, turn, status, mock.Mock(), elapsed_secs=400)
                    self.assertEqual(runtime.status, "experimental")
                    self.assertIn(
                        successor["execution"],
                        server.request.call_args.args[1]["input"][0]["text"],
                    )
                    terminal = runtime.close()
                    reward = lineage.reward(
                        episode,
                        resolved=4,
                        total=5,
                        submission_sha256="b" * 64,
                        evaluator_sha256="c" * 64,
                        selection_evidence={
                            "native_secs": 500,
                            "research_secs": 5,
                            "grading_secs": 20,
                            "episode_secs": 18000,
                            "input_witness": "d" * 64,
                            **terminal["command_metrics"],
                        },
                    )
                    self.assertEqual(
                        reward["producer_method"], online.digest(previous["research"])
                    )
                    self.assertEqual(lineage.current(), online.seed())
                    alternatives = reward["selection"]["next_distribution"]
                    cumulative = 0
                    for action in alternatives:
                        if (
                            action["version"] == online.digest(successor)
                            and action["mode"] == "research"
                        ):
                            draw = cumulative + action["probability"] / 2
                            break
                        cumulative += action["probability"]
                    previous = successor
                finally:
                    runtime.close()

    def test_hold_cannot_launch_worker_even_when_harness_trigger_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lineage = Lineage(root / "lineage", selection_scope="a" * 64)
            with mock.patch.object(
                selection.random.SystemRandom, "random", return_value=0.99
            ):
                runtime = OnlineRuntime(
                    lineage, "one", root / "run", Path("/fixture"), {}, "FAKE"
                )
            try:
                runtime.command_count = 100
                with mock.patch.object(runtime.pool, "submit") as submit:
                    runtime.poll(
                        mock.Mock(),
                        SimpleNamespace(active=True),
                        {"contract_id": "c"},
                        mock.Mock(),
                        elapsed_secs=500,
                    )
                submit.assert_not_called()
                self.assertEqual(runtime.allocation["executor_secs"], 18000)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
