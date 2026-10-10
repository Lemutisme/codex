"""Transactional online learning and two-generation inheritance without inference."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

import procontract_online as online
from procontract_online_lineage import Lineage
from test_procontract_online import candidate


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "private"
        self.lineage = Lineage(self.root)

    def reserve(self, episode="one"):
        return self.lineage.begin(episode, 18000, 900)

    def propose(self, episode="one"):
        self.reserve(episode)
        packet = self.lineage.claim(
            episode, {"status": "working", "observed_commands": 4}
        )
        program, raw = candidate(packet["program"], episode)
        self.assertEqual(self.lineage.register(episode, raw), program)
        return packet, program

    def test_two_generations_consume_inherited_method_and_post_submission_reward(self):
        first, successor = self.propose()
        self.lineage.dispatch("one", {"outcome": "accepted", "turn_id": "t1"})
        reward = self.lineage.reward(
            "one",
            resolved=2,
            total=7,
            submission_sha256="a" * 64,
            evaluator_sha256="b" * 64,
        )
        self.assertEqual(
            reward,
            {
                "episode": "one",
                "initial_version": first["parent"],
                "experimental_version": online.digest(successor),
                "resolved": 2,
                "total": 7,
                "submission_sha256": "a" * 64,
                "evaluator_sha256": "b" * 64,
                "credit": "episode_return_not_isolated_causal_effect",
            },
        )
        reopened = Lineage(self.root)
        self.assertEqual(reopened.current(), successor)
        reopened.begin("two", 18000, 900)
        second = reopened.claim("two", {"status": "working"})
        self.assertEqual(
            second,
            {
                "parent": online.digest(successor),
                "program": successor,
                "observations": {"status": "working"},
                "past_rewards": [reward],
                "previous_trial": None,
            },
        )
        next_program, raw = candidate(second["program"], "two")
        reopened.register("two", raw)
        reopened.dispatch("two", {"outcome": "accepted", "turn_id": "t2"})
        self.assertEqual(reopened.current(), next_program)
        claims = [
            event["body"] for event in reopened.events() if event["kind"] == "claim"
        ]
        self.assertEqual(
            [c["producer_method"] for c in claims],
            [
                online.digest(first["program"]["research"]),
                online.digest(successor["research"]),
            ],
        )
        self.assertTrue(
            all(
                e["body"]["certification"] == "none"
                for e in reopened.events()
                if e["kind"] == "dispatch"
            )
        )

    def test_ambiguous_or_failed_dispatch_does_not_publish_or_retry(self):
        for result in ("timeout", "error", "unacknowledged"):
            with self.subTest(result=result):
                before = self.lineage.current()
                self.propose(result)
                self.lineage.dispatch(result, {"outcome": result})
                self.assertEqual(self.lineage.current(), before)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.lineage.dispatch(result, {"outcome": "accepted"})
                self.assertEqual(self.lineage.current(), before)

    def test_claim_survives_crash_and_consumes_the_only_attempt(self):
        self.reserve()
        self.lineage.claim("one", {})
        reopened = Lineage(self.root)
        with self.assertRaises(sqlite3.IntegrityError):
            reopened.claim("one", {})
        with self.assertRaises(sqlite3.IntegrityError):
            reopened.begin("one", 18000, 900)

    def test_stale_concurrent_episode_cannot_publish(self):
        self.propose("one")
        self.propose("two")
        self.lineage.dispatch("one", {"outcome": "accepted", "turn_id": "t1"})
        before = self.lineage.current()
        with self.assertRaisesRegex(ValueError, "stale"):
            self.lineage.dispatch("two", {"outcome": "accepted", "turn_id": "t2"})
        self.assertEqual(self.lineage.current(), before)

    def test_unknown_reward_and_duplicate_reward_never_become_zero_or_extra_samples(
        self,
    ):
        self.reserve()
        for resolved, total in (
            (None, 1),
            (0, None),
            (0, 0),
            (2, 1),
            (True, 1),
            (-1, 1),
        ):
            with self.subTest(resolved=resolved, total=total):
                with self.assertRaises(ValueError):
                    self.lineage.reward(
                        "one",
                        resolved=resolved,
                        total=total,
                        submission_sha256="a" * 64,
                        evaluator_sha256="b" * 64,
                    )
        self.assertEqual(
            [e for e in self.lineage.events() if e["kind"] == "reward"], []
        )
        self.lineage.reward(
            "one",
            resolved=0,
            total=5,
            submission_sha256="a" * 64,
            evaluator_sha256="b" * 64,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.lineage.reward(
                "one",
                resolved=5,
                total=5,
                submission_sha256="a" * 64,
                evaluator_sha256="b" * 64,
            )
        self.assertEqual(
            len([e for e in self.lineage.events() if e["kind"] == "reward"]), 1
        )

    def test_allocation_charges_research_even_if_it_would_run_concurrently(self):
        value = self.reserve()
        self.assertEqual(
            value["executor_secs"] + value["research_secs"], value["total_secs"]
        )
        for total, research in ((18001, 900), (100, 100), (100, 0), (True, 1)):
            with self.assertRaises(ValueError):
                self.lineage.begin("bad", total, research)

    def test_packets_have_hard_bounds_before_reservation(self):
        self.reserve()
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.lineage.claim("one", {"text": "x" * 3500})
        self.lineage.claim("one", {"text": "small"})

    def test_failed_trial_is_future_learning_data_but_never_a_zero_reward(self):
        self.reserve("one")
        self.lineage.claim("one", {})
        self.lineage.finish_trial(
            "one", status="rejected", reason="invalid H predicate", commands_after_ack=0
        )
        self.reserve("two")
        packet = self.lineage.claim("two", {})
        self.assertEqual(
            packet["previous_trial"],
            {
                "episode": "one",
                "status": "rejected",
                "reason": "invalid H predicate",
                "commands_after_ack": 0,
                "scope": "runtime_observation_not_quality_reward",
            },
        )
        self.assertEqual(packet["past_rewards"], [])
        self.assertEqual(self.lineage.current(), online.seed())

    def test_unclaimed_proposal_and_reward_are_rejected(self):
        _, raw = candidate(online.seed(), "new")
        with self.assertRaises(ValueError):
            self.lineage.register("missing", raw)
        with self.assertRaises(ValueError):
            self.lineage.reward(
                "missing",
                resolved=1,
                total=1,
                submission_sha256="a" * 64,
                evaluator_sha256="b" * 64,
            )

    def test_symlinked_state_is_rejected_without_touching_destination(self):
        target = Path(self.temp.name) / "other"
        target.mkdir()
        link = Path(self.temp.name) / "redirect"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            Lineage(link)
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
