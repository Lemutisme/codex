"""Coverage probes burn their slots and never masquerade as deployment draws."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import procontract_online as online
from procontract_online_lineage import Lineage
import procontract_online_selection as selection
from test_procontract_online import candidate


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lineage = Lineage(
            self.root, selection_scope="a" * 64, selection_mode="coverage"
        )

    def close(self, episode):
        self.lineage.finish_trial(
            episode, status="observing", reason="fixture", commands_after_ack=0
        )

    def reward(self, episode, witness):
        return self.lineage.reward(
            episode,
            resolved=1,
            total=5,
            submission_sha256="b" * 64,
            evaluator_sha256="c" * 64,
            selection_evidence={
                "native_secs": 100,
                "research_secs": 10,
                "grading_secs": 1,
                "episode_secs": 18000,
                "commands": 4,
                "failed_commands": 0,
                "commands_with_exit": 4,
                "input_witness": witness,
            },
        )

    def propose(self, episode):
        packet = self.lineage.claim(episode, {})
        program, raw = candidate(packet["program"], episode)
        body = json.loads(raw)
        body["prediction"] = json.dumps(
            {"metric": "canonical_fraction", "direction": "at_least", "threshold": 0.5}
        )
        self.lineage.register(episode, online.encoded(body))
        self.lineage.dispatch(episode, {"outcome": "accepted"})
        self.close(episode)
        return program

    def fail(self, episode, **overrides):
        return self.lineage.fail_episode(
            episode,
            reason="draft unavailable",
            summary_sha256="d" * 64,
            native_exit={"status": "exited", "returncode": 0, **overrides},
        )

    def test_two_declared_probes_then_unforced_selection_with_real_propensities(self):
        with mock.patch.object(
            selection.random.SystemRandom,
            "random",
            side_effect=AssertionError("coverage must not draw"),
        ):
            first = self.lineage.begin("one", 14400, 900)
            child = self.propose("one")
            measured = self.reward("one", "e" * 64)
            second = self.lineage.begin("two", 14400, 900)
        for allocation, purpose in (
            (first, "coverage_seed"),
            (second, "coverage_successor"),
        ):
            decision = allocation["selection"]
            self.assertEqual(
                (decision["purpose"], decision["probability"], decision["draw"]),
                (purpose, 1.0, None),
            )
            self.assertEqual(sum(a["probability"] for a in decision["alternatives"]), 1)
        self.assertEqual(second["parent"], online.digest(child))
        self.assertEqual(measured["selection"]["propensity"], 1)
        packet = self.lineage.claim("two", {})
        self.assertEqual(packet["program"]["research"], child["research"])
        self.close("two")
        self.reward("two", None)
        with mock.patch.object(
            selection.random.SystemRandom, "random", return_value=0.999
        ) as rng:
            third = self.lineage.begin("three", 14400, 900)
        rng.assert_called_once()
        self.assertEqual(
            (third["selection"]["purpose"], third["selection"]["mode"]),
            ("policy", "hold"),
        )
        self.assertEqual(self.lineage.current(), online.seed())

    def test_ack_without_request_consumption_cannot_force_child_exploration(self):
        self.lineage.begin("one", 14400, 900)
        child = self.propose("one")
        self.reward("one", None)
        second = self.lineage.begin("two", 14400, 900)
        self.assertEqual(second["selection"]["purpose"], "coverage_unavailable")
        self.assertNotEqual(second["parent"], online.digest(child))

    def test_local_failure_is_terminal_but_not_reward_or_a_new_coverage_allowance(self):
        first = self.lineage.begin("one", 14400, 900)
        self.close("one")
        failure = self.fail("one")
        self.assertIsNone(failure["quality"])
        second = self.lineage.begin("two", 14400, 900)
        self.assertEqual(second["selection"]["purpose"], "coverage_unavailable")
        self.assertEqual(
            second["selection"]["state_sha256"], first["selection"]["state_sha256"]
        )
        self.close("two")
        self.fail("two")
        third = self.lineage.begin("three", 14400, 900)
        self.assertEqual(third["selection"]["purpose"], "policy")
        self.assertEqual(
            [e for e in self.lineage.events() if e["kind"] == "reward"], []
        )
        with self.assertRaisesRegex(ValueError, "cannot later"):
            self.reward("one", None)
        with self.assertRaises(ValueError):
            self.fail("one")

    def test_unresolved_process_or_research_claim_cannot_be_locally_closed(self):
        self.lineage.begin("one", 14400, 900)
        self.close("one")
        for exit in ({"status": "unknown"}, {"returncode": 1}, {"returncode": False}):
            with self.assertRaises(ValueError):
                self.fail("one", **exit)
        with self.assertRaisesRegex(ValueError, "no terminal"):
            self.lineage.begin("two", 14400, 900)
        self.fail("one")
        with mock.patch.object(selection.random.SystemRandom, "random", return_value=0):
            second = self.lineage.begin("two", 14400, 900)
        self.assertEqual(second["research_secs"], 900)
        self.lineage.claim("two", {})
        self.close("two")
        with self.assertRaisesRegex(ValueError, "reclassify"):
            self.fail("two")

    def test_mode_is_frozen_not_changed_after_an_unwanted_draw(self):
        with self.assertRaisesRegex(ValueError, "algorithm changed"):
            Lineage(self.root, selection_scope="a" * 64, selection_mode="deployment")
        with self.assertRaisesRegex(ValueError, "unknown selection mode"):
            Lineage(self.root, selection_scope="a" * 64, selection_mode="adaptive")


if __name__ == "__main__":
    unittest.main()
