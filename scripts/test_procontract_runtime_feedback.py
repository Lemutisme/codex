"""Synthetic receipts exercise real Host archive plumbing without paid execution."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_runtime_feedback as feedback
from test_procontract_rsi import DEV, SEALED, FakeTasks, campaign, host


class RuntimeFeedbackTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "run.json"
        self.raw = {
            "deadline_secs": 18000,
            "elapsed_secs": 18001,
            "deadline_hit": True,
            "turns_completed": 0,
            "server_exited_early": False,
            "harness_program": {
                "sha256": "a" * 64,
                "interpreter": "convergence-v1",
                "evaluations": 42431,
                "last_input": {
                    "deadline_secs": 18000,
                    "remaining_secs": 1,
                    "turns_completed": 0,
                    "repairs_used": 0,
                },
                "last_decision": False,
            },
            "delivery_budget": {"reserve_secs": 3600, "attempt": None},
            "execution_environment": {
                "disconnect_observed": False,
                "disconnect_count": 0,
                "events_omitted": 0,
            },
        }

    def write(self, value):
        self.path.write_text(json.dumps(value))
        return feedback.read(self.root)

    def test_projection_preserves_facts_and_removes_non_schema_data(self):
        projected = self.write(self.raw)
        expected = {
            **self.raw,
            "status": "observed",
            "kind": "host_runtime_facts_v1",
            "null_means": "unobservable (except delivery attempt: explicitly no attempt)",
            **{
                key: {"status": "observed", **self.raw[key]}
                for key in (
                    "harness_program",
                    "delivery_budget",
                    "execution_environment",
                )
            },
        }
        self.assertEqual(projected, expected)
        expected = json.loads(json.dumps(expected))
        self.raw["prompt"] = self.raw["turn_errors"] = "SECRET" * 10000
        self.raw["harness_program"]["last_input"]["prompt"] = "SECRET"
        self.raw["execution_environment"]["disconnections"] = [
            {"environment_id": "SECRET"}
        ]
        self.raw["delivery_budget"]["attempt"] = {
            "turn_id": "SECRET",
            "outcome": "accepted",
            "remaining_secs": 3.25,
            "error": "SECRET",
            "prompt": "SECRET",
        }
        expected["delivery_budget"]["attempt"] = {
            "status": "observed",
            "outcome": "accepted",
            "remaining_secs": 3.25,
        }
        self.assertEqual(self.write(self.raw), expected)
        self.assertLess(len(json.dumps(expected)), 2048)

    def test_missing_legacy_malformed_and_oversize_are_not_false_or_zero(self):
        self.assertEqual(
            feedback.read(self.root), {"status": "unobservable", "reason": "missing"}
        )
        for value, reason in (
            ({"thread_id": "old"}, "legacy"),
            ([], "malformed"),
            ({"deadline_secs": True}, "malformed"),
            ({"elapsed_secs": 10**400}, "malformed"),
        ):
            with self.subTest(value=str(value)[:80]):
                self.assertEqual(
                    self.write(value), {"status": "unobservable", "reason": reason}
                )
        for raw, reason in (
            (b'{"elapsed_secs":1,"elapsed_secs":2}', "malformed"),
            (b'{"elapsed_secs":NaN}', "malformed"),
            (b"[" * 2000, "malformed"),
            (b" " * (feedback.MAX_SOURCE_BYTES + 1), "oversize"),
        ):
            self.path.write_bytes(raw)
            self.assertEqual(
                feedback.read(self.root), {"status": "unobservable", "reason": reason}
            )
        projected = self.write({"server_exited_early": False})
        self.assertIs(projected["server_exited_early"], False)
        self.assertIsNone(projected["deadline_hit"])
        self.assertEqual(
            projected["harness_program"],
            {"status": "unobservable", "reason": "missing"},
        )
        self.raw["harness_program"]["evaluations"] = "not a counter"
        self.assertEqual(
            self.write(self.raw)["harness_program"],
            {"status": "unobservable", "reason": "malformed"},
        )
        self.raw["harness_program"].update(
            evaluations=0, last_input=None, last_decision=None
        )
        self.assertEqual(
            self.write(self.raw)["harness_program"],
            {"status": "observed", **self.raw["harness_program"]},
        )
        del self.raw["delivery_budget"]["attempt"]
        self.assertEqual(
            self.write(self.raw)["delivery_budget"],
            {"status": "unobservable", "reason": "malformed"},
        )

    def test_nonregular_symbolic_and_hard_links_are_unobservable(self):
        self.path.mkdir()
        self.assertEqual(
            feedback.read(self.root),
            {"status": "unobservable", "reason": "unsafe_file"},
        )
        self.path.rmdir()
        other = self.root / "other.json"
        other.write_text(json.dumps(self.raw))
        try:
            self.path.symlink_to(other)
            self.assertEqual(
                feedback.read(self.root),
                {"status": "unobservable", "reason": "unsafe_file"},
            )
            self.path.unlink()
            os.link(other, self.path)
        except (OSError, NotImplementedError):
            self.skipTest("links unavailable on this platform")
        self.assertEqual(
            feedback.read(self.root),
            {"status": "unobservable", "reason": "unsafe_file"},
        )

    def test_research_archive_retains_projection_without_new_exposure_or_rewriting(
        self,
    ):
        h = host(campaign(str(self.root)), FakeTasks())
        version = h.incumbent()
        h.dev(version)
        h.measure(version, SEALED[0], "confirm")
        h.measure(version, DEV[0], "baseline")
        h.measure(version, SEALED[1], "baseline")
        h.record("exposure", {"view": "confirmation:fixture", "sources": [SEALED[1]]})
        observed = h.observed()
        name = f"dev-{version[:12]}-{DEV[0]}"
        receipt = Path(observed[name]["run_dir"]) / "run.json"
        # Substitute only the fake transport's telemetry; canonical results stay untouched.
        receipt.write_text(json.dumps(self.raw))
        expected = feedback.read(receipt.parent)
        archive = h.stage_research(version, 1) / "workspace" / "archive"
        shown = {path.name for path in (archive / "runs").iterdir()}
        self.assertEqual(shown, set(observed))
        self.assertEqual(
            {path.name for path in (archive / "tasks").iterdir()}, set(DEV)
        )
        summary = json.loads((archive / "runs" / name / "summary.json").read_text())
        self.assertEqual(
            (summary["validity"], summary["runtime_receipt"]), ("valid", expected)
        )
        legacy = json.loads(
            (
                archive / "runs" / f"dev-{version[:12]}-{DEV[1]}" / "summary.json"
            ).read_text()
        )
        self.assertEqual(
            legacy["runtime_receipt"], {"status": "unobservable", "reason": "legacy"}
        )
        self.assertEqual(h.events("exposure")[-1]["body"]["sources"], sorted(observed))
        saved = (h.camp / "observations" / name / "summary.json").read_bytes()
        receipt.write_text("malformed")
        h.observe(name, observed[name])
        self.assertEqual(
            (h.camp / "observations" / name / "summary.json").read_bytes(), saved
        )
        with mock.patch.object(h, "recent_runs", return_value=set()):
            second = h.stage_research(version, 2) / "workspace" / "archive"
        self.assertFalse((second / "runs" / name / "trajectory.md").exists())
        self.assertEqual((second / "runs" / name / "summary.json").read_bytes(), saved)
