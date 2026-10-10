"""Reward changes future actions, with transactional credit and no inference."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import procontract_online as online
from procontract_online_lineage import Lineage
import procontract_online_selection as selection
from test_procontract_online import candidate


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "lineage"
        self.lineage = Lineage(self.root, selection_scope="a" * 64)

    def begin(self, name="one", draw=0):
        with mock.patch.object(
            selection.random.SystemRandom, "random", return_value=draw
        ):
            return self.lineage.begin(name, 14400, 900)

    def finish(self, name="one", resolved=4, **overrides):
        self.lineage.finish_trial(
            name, status="observing", reason="", commands_after_ack=0
        )
        return self.reward(name, resolved, **overrides)

    def reward(self, name, resolved, **overrides):
        return self.lineage.reward(
            name,
            resolved=resolved,
            total=5,
            submission_sha256="b" * 64,
            evaluator_sha256="c" * 64,
            selection_evidence={
                "native_secs": 100,
                "research_secs": 20,
                "grading_secs": 5,
                "episode_secs": 18000,
                "commands": 10,
                "failed_commands": 2,
                "commands_with_exit": 10,
                "input_witness": None,
                **overrides,
            },
        )

    def propose(self):
        packet = self.lineage.claim("one", {"failures": 2})
        program, raw = candidate(packet["program"], "one")
        body = json.loads(raw)
        body["prediction"] = json.dumps(
            {
                "metric": "command_failure_fraction",
                "direction": "at_most",
                "threshold": 0.3,
            }
        )
        self.lineage.register("one", online.encoded(body))
        self.lineage.dispatch("one", {"outcome": "accepted"})
        return program

    def state(self):
        with self.lineage.transaction() as db:
            return json.loads(
                db.execute("SELECT value FROM state WHERE key='selection'").fetchone()[
                    0
                ]
            )

    def test_reward_changes_probabilities_not_incumbent_and_hold_recovers_capacity(
        self,
    ):
        allocation = self.begin()
        before = allocation["selection"]["alternatives"]
        result = self.finish(resolved=0)
        after = result["selection"]["next_distribution"]
        self.assertLess(after[0]["probability"], before[0]["probability"])
        self.assertEqual(
            result["selection"]["credited_version"], online.digest(online.seed())
        )
        self.assertEqual(self.lineage.current(), online.seed())
        second = self.begin("two", draw=0.99)
        self.assertEqual((second["research_secs"], second["executor_secs"]), (0, 14400))
        with self.assertRaisesRegex(ValueError, "no research authority"):
            self.lineage.claim("two", {})

    def test_consumed_child_is_unmeasured_and_later_research_uses_its_method(self):
        self.begin()
        child = self.propose()
        self.assertEqual(self.lineage.current(), online.seed())
        self.assertEqual(len(self.state()["arms"]), 2)
        reward = self.finish(input_witness="d" * 64)
        self.assertEqual([a["samples"] for a in self.state()["arms"]], [1, 0, 0, 0])
        self.assertEqual(
            reward["producer_method"], online.digest(online.seed()["research"])
        )
        self.assertEqual(reward["selection"]["prediction"]["actual"], 0.2)
        arms = reward["selection"]["next_distribution"]
        draw = sum(a["probability"] for a in arms[:2]) + arms[2]["probability"] / 2
        self.begin("two", draw)
        packet = self.lineage.claim("two", {})
        self.assertEqual(packet["program"], child)
        self.assertEqual(packet["past_rewards"][0]["resolved"], 4)
        self.assertEqual(packet["past_rewards"][0]["prediction"]["actual"], 0.2)
        self.assertEqual(self.lineage.current(), online.seed())

    def test_ack_without_input_witness_never_admits_child(self):
        self.begin()
        self.propose()
        self.finish()
        self.assertEqual(len(self.state()["arms"]), 2)

    def test_unknown_cost_or_duplicate_reward_does_not_change_statistics(self):
        self.begin()
        self.lineage.finish_trial(
            "one", status="observing", reason="", commands_after_ack=0
        )
        before = self.state()
        for bad in (None, float("nan"), float("inf"), -1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.reward("one", 2, native_secs=bad)
            self.assertEqual(self.state(), before)
        self.reward("one", 2)
        after = self.state()
        with self.assertRaises((sqlite3.IntegrityError, ValueError)):
            self.reward("one", 5)
        self.assertEqual(self.state(), after)

    def test_unknown_episode_blocks_resampling_and_runtime_must_close(self):
        self.begin()
        with self.assertRaisesRegex(ValueError, "no terminal reward"):
            self.begin("two")
        with self.assertRaisesRegex(ValueError, "closed runtime"):
            self.reward("one", 4)
        self.assertEqual(self.state()["arms"][0]["samples"], 0)

    def test_cost_changes_utility_but_does_not_change_task_quality(self):
        self.begin()
        result = self.finish(native_secs=17000, research_secs=900, grading_secs=100)
        self.assertEqual((result["resolved"], result["total"]), (4, 5))
        self.assertAlmostEqual(result["selection"]["utility"], 0.8 / 1.1)
        self.assertEqual(result["selection"]["cost_fraction"], 1)

    def test_missing_command_exit_is_unknown_not_a_prediction_success(self):
        self.begin()
        self.propose()
        result = self.finish(commands_with_exit=9)
        self.assertIsNone(result["selection"]["prediction"]["met"])

    def test_scope_and_legacy_results_cannot_be_reinterpreted(self):
        for scope in (None, "b" * 64):
            with self.assertRaises(ValueError):
                Lineage(self.root, selection_scope=scope)
        legacy = Path(self.temp.name) / "legacy"
        Lineage(legacy).begin("old", 14400, 900)
        with self.assertRaisesRegex(ValueError, "legacy"):
            Lineage(legacy, selection_scope="a" * 64)

    def test_predicted_metrics_are_machine_checkable_not_free_form_self_grades(self):
        for value in (
            {"metric": "redundancy", "direction": "at_most", "threshold": 0.2},
            {
                "metric": "canonical_fraction",
                "direction": "at_least",
                "threshold": True,
            },
            {"metric": "canonical_fraction", "direction": "at_least", "threshold": 2},
        ):
            with self.assertRaises(ValueError):
                selection.prediction(json.dumps(value))

    def test_duplicate_prediction_keys_cannot_hide_a_threshold(self):
        with self.assertRaises(ValueError):
            selection.prediction(
                '{"metric":"canonical_fraction","direction":"at_least","threshold":0.9,"threshold":0.0}'
            )

    def test_selection_prefers_better_observed_controller_in_synthetic_environment(
        self,
    ):
        # Deterministic stratified draws, not a claim about ProgramBench performance.
        for index in range(120):
            allocation = self.begin(str(index), ((index * 37) % 120 + 0.5) / 120)
            good = allocation["selection"]["mode"] == "research"
            result = self.finish(str(index), resolved=5 if good else 0)
        research, hold = result["selection"]["next_distribution"]
        self.assertGreater(research["probability"], 0.8)
        self.assertGreater(hold["probability"], 0)


if __name__ == "__main__":
    unittest.main()
