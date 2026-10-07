"""Stream → independent confirmation → kernel settlement, using the real store."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_release as release
import procontract_rsi as rsi
import test_procontract_rsi as fixtures


def campaign(tmp, adoption="presumed", every=2):
    sealed = Path(tmp, "sealed.json")
    sealed.write_text(json.dumps({"select": fixtures.SEALED}))
    main = rsi.main

    def initialize():
        args = [
            *sys.argv,
            "--sealed",
            str(sealed),
            "--release-every",
            str(every),
            "--confirm-tasks",
            "3",
            "--confirm-min-wins",
            "2",
            "--adoption",
            adoption,
        ]
        with mock.patch.object(sys, "argv", args):
            main()

    with mock.patch.object(rsi, "main", side_effect=initialize):
        return fixtures.stream_campaign(tmp)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "better"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_only_the_tested_policy_is_confirmed_and_adoption_respects_authority(self):
        for adoption in ("presumed", "explicit"):
            with self.subTest(adoption=adoption), tempfile.TemporaryDirectory() as tmp:
                tasks = fixtures.FakeTasks()
                h = fixtures.host(campaign(tmp, adoption), tasks)
                root = h.incumbent()
                self.assertFalse(set(h.order()) & set(h.terms["pools"]["confirm"]))
                h.stream_step()
                self.assertEqual(
                    (h.incumbent(), h.used_confirmation_tasks()), (root, [])
                )
                self.assertNotEqual(
                    h.stream_policy(), root, "qualification only permits exploration"
                )
                for event in h.events("exposure"):
                    self.assertFalse(
                        set(event["body"]["sources"]) & set(fixtures.SEALED)
                    )

                h.stream_step()

                tested = h.batches()[-1]["version"]
                self.assertNotEqual(
                    tested, h.stream_policy(), "the next policy is not yet tested"
                )
                pairs = [
                    (version, task)
                    for version, task in tasks.runs
                    if task in fixtures.SEALED
                ]
                self.assertEqual(set(version for version, _ in pairs), {root, tested})
                self.assertEqual(len(pairs), 6)
                self.assertEqual(len(h.used_confirmation_tasks()), 3)
                self.assertEqual(
                    h.incumbent(), tested if adoption == "presumed" else root
                )
                if adoption == "explicit":
                    h.adopt(tested)
                self.assertEqual(
                    h.contract(f"adoption.{tested[:16]}")["settlement"]["decision"],
                    {"type": adoption} if adoption == "explicit" else h.presumed(),
                )
                self.assertIsNone(release.advance(h))

    def test_an_absent_signature_or_failed_challenge_cannot_release_a_policy(self):
        for env in ({"FAKE_SIGNATURE": "absent"}, {"FAKE_CHALLENGE": "fail"}):
            with self.subTest(env=env), tempfile.TemporaryDirectory() as tmp:
                h = fixtures.host(campaign(tmp), fixtures.FakeTasks())
                root = h.incumbent()
                h.stream_step()
                with mock.patch.dict(os.environ, env):
                    h.stream_step()
                    release.advance(h)
                self.assertEqual(
                    (h.incumbent(), h.used_confirmation_tasks()), (root, [])
                )
                self.assertFalse(
                    any(
                        e["body"]["role"] == "stream_release_intent"
                        for e in h.events("selection")
                    )
                )

    def test_the_fixed_final_checkpoint_does_not_restart_learning_after_confirmation(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            h = fixtures.host(campaign(tmp, every=3), fixtures.FakeTasks())
            h.stream_step()
            h.stream_step()
            self.assertEqual(h.used_confirmation_tasks(), [])
            self.assertIn("confirmed and adopted", h.stream_step())
            finished = (h.batches(), h.insights(), h.used_confirmation_tasks())
            self.assertEqual(h.stream_step(), "the stream is complete")
            self.assertEqual(
                (h.batches(), h.insights(), h.used_confirmation_tasks()), finished
            )

    def test_failed_confirmation_keeps_the_incumbent_and_spends_the_reserve_once(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "worse"}),
        ):
            h = fixtures.host(campaign(tmp), fixtures.FakeTasks())
            root = h.incumbent()
            h.stream_step()
            self.assertIn("confirmation failed", h.stream_step())
            tested = h.batches()[-1]["version"]
            self.assertEqual(
                (h.incumbent(), h.contract(f"adoption.{tested[:16]}")["standing"]),
                (root, "released"),
            )
            spent = h.used_confirmation_tasks()
            self.assertIsNone(release.advance(h))
            self.assertEqual(h.used_confirmation_tasks(), spent)

    def test_confirmation_resumes_its_frozen_choice_and_reservation_before_a_new_batch(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            h = fixtures.host(campaign(tmp), tasks)
            h.stream_step()
            measure_all = h.measure_all

            def interrupted(pairs, purpose):
                if purpose == "confirm":
                    h.measure(*pairs[0], purpose)
                    raise InterruptedError("host stopped after one paired arm")
                return measure_all(pairs, purpose)

            with mock.patch.object(h, "measure_all", side_effect=interrupted):
                with self.assertRaises(InterruptedError):
                    h.stream_step()
            tested = h.batches()[-1]["version"]
            spent = h.used_confirmation_tasks()
            self.assertEqual(len(spent), 3)
            resumed = fixtures.host(h.camp, tasks)

            self.assertIn("confirmed and adopted", resumed.stream_step())

            self.assertEqual((resumed.incumbent(), len(resumed.batches())), (tested, 2))
            self.assertEqual(resumed.used_confirmation_tasks(), spent)
            self.assertEqual(len([(v, t) for v, t in tasks.runs if t in spent]), 6)
            intents = [
                e
                for e in resumed.events("selection")
                if e["body"]["role"] == "stream_release_intent"
            ]
            self.assertEqual(len(intents), 1)


if __name__ == "__main__":
    unittest.main()
