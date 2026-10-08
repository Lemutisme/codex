"""Fenced succession and interrupted workflow recovery, using the real store."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_store as store
import procontract_succession as succession
import test_procontract_rsi as fixtures
from test_procontract_release import campaign as release_campaign


class SuccessionRecoveryTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "better"})
        patch.start()
        self.addCleanup(patch.stop)

    def test_legacy_support_cannot_acquire_a_fresh_confirmation_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            h = fixtures.host(fixtures.campaign(tmp), tasks)
            candidate = store.digest("candidate", "legacy")
            adoption = f"adoption.{candidate[:16]}"
            h.issue(
                adoption,
                {"candidate": candidate, "expected_incumbent": h.incumbent()},
                {"class": "paired_confirmation"},
                "delegate",
            )
            h.propose(adoption, candidate)
            h.support(
                adoption, {"legacy": True}, {"tasks": fixtures.SEALED[:3]}, "beyond"
            )
            before = store.events(h.store)
            with self.assertRaisesRegex(RuntimeError, "frozen confirmation assignment"):
                h.confirm(candidate, h.incumbent())
            self.assertEqual((store.events(h.store), tasks.runs), (before, []))

    def test_a_stale_release_terminates_without_spending_another_holdout(self):
        for reserved in (False, True):
            with self.subTest(reserved=reserved), tempfile.TemporaryDirectory() as tmp:
                tasks = fixtures.FakeTasks()
                h = fixtures.host(
                    release_campaign(tmp, adoption="explicit", every=1), tasks
                )
                h.stream_step()
                h.stream_step()
                confirmed = h.batches()[-1]["version"]
                measure_all = h.measure_all

                def interrupted(pairs, purpose):
                    if purpose == "confirm":
                        raise InterruptedError("confirmation stopped")
                    return measure_all(pairs, purpose)

                patch = (
                    mock.patch.object(h, "measure_all", side_effect=interrupted)
                    if reserved
                    else mock.patch.object(h, "confirm", side_effect=InterruptedError)
                )
                with patch, self.assertRaises(InterruptedError):
                    h.stream_step()
                stale = h.batches()[-1]["version"]
                h.adopt(confirmed)
                before = (h.used_confirmation_tasks(), list(tasks.runs))
                resumed = fixtures.host(h.camp, tasks)
                self.assertIn("stale", resumed.stream_step())
                self.assertEqual(
                    (
                        resumed.incumbent(),
                        resumed.used_confirmation_tasks(),
                        tasks.runs,
                    ),
                    (confirmed, *before),
                )
                if reserved:
                    self.assertEqual(
                        resumed.contract(f"adoption.{stale[:16]}")["standing"],
                        "released",
                    )
                self.assertEqual(resumed.stream_step(), "the stream is complete")

    def test_interrupted_attempts_are_spent_across_host_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            h = fixtures.host(fixtures.campaign(tmp), tasks)
            args = (h.incumbent(), fixtures.DEV[0], "dev")
            with mock.patch.object(
                tasks, "run_and_label", side_effect=InterruptedError
            ) as run:
                for _ in range(2):
                    with self.assertRaises(InterruptedError):
                        fixtures.host(h.camp, tasks).measure(*args)
                result = fixtures.host(h.camp, tasks).measure(*args)
                self.assertEqual(fixtures.host(h.camp, tasks).measure(*args), result)
                self.assertEqual(
                    (run.call_count, result["validity"], result["cost_unknown"]),
                    (2, "invalid", True),
                )

    def test_confirmation_stops_if_incumbent_is_revoked_without_another_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = fixtures.FakeTasks()
            h = fixtures.host(fixtures.campaign(tmp), tasks)
            root = h.incumbent()
            h.step()
            incumbent = next(v for v in h.versions() if v != root)
            h.adopt(incumbent)
            draft = Path(tmp, "successor")
            shutil.copytree(h.version_dir(incumbent) / "bundle", draft)
            executor = draft / "executor.md"
            executor.write_text(executor.read_text() + "\nbetter\n")
            candidate = h.register(draft, incumbent, incumbent, "revocation fixture")
            with mock.patch.object(h, "measure_all", side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):
                    h.confirm(candidate, incumbent)
            selection = succession.incumbent_record(h)
            adoption = f"adoption.{incumbent[:16]}"
            state = h.contract(adoption)
            h.apply(
                adoption,
                "settler",
                "human",
                {
                    "type": "challenge",
                    "target": {
                        "type": "settlement",
                        "coordinate": state["settlement"]["coordinate"],
                    },
                    "defeater": store.digest("defeater", "revoked fixture"),
                },
                "revoke-incumbent",
            )
            self.assertEqual(succession.incumbent_record(h), selection)
            self.assertEqual(h.incumbent(), root)
            before = (list(tasks.runs), h.used_confirmation_tasks())
            resumed = fixtures.host(h.camp, tasks)
            self.assertEqual(
                resumed.confirm(candidate, incumbent),
                "confirmation stale; incumbent changed",
            )
            self.assertEqual((tasks.runs, resumed.used_confirmation_tasks()), before)
            self.assertEqual(
                resumed.contract(f"adoption.{candidate[:16]}")["standing"], "released"
            )

    def test_writer_excludes_another_writer_and_unlocks_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = Path(tmp, "campaign")
            with self.assertRaises(InterruptedError), succession.writer(camp):
                with self.assertRaisesRegex(RuntimeError, "another workflow writer"):
                    with succession.writer(camp):
                        self.fail("two writers acquired the same campaign")
                raise InterruptedError
            with succession.writer(camp):
                pass


if __name__ == "__main__":
    unittest.main()
