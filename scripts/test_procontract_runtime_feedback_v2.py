"""Synthetic host receipts test bounded v2 feedback, not empirical harness benefits."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import procontract_runtime_feedback as feedback
from test_procontract_rsi import DEV, FakeTasks, campaign, host


class RuntimeFeedbackV2Test(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = {
            "deadline_secs": 18000,
            "elapsed_secs": 301,
            "deadline_hit": False,
            "turns_completed": 0,
            "server_exited_early": False,
            "harness_program": {
                "sha256": "b" * 64,
                "interpreter": "bounded-steering-v2",
                "evaluations": 1,
                "last_input": {
                    "deadline_secs": 18000,
                    "remaining_secs": 17699,
                    "turns_completed": 0,
                    "repairs_used": 0,
                    "executor_command_completions_observed": 0,
                },
                "last_decision": False,
                "action": "checkpoint",
                "last_eligibility": {"eligible": True, "reason": "eligible"},
            },
            "delivery_budget": {"reserve_secs": 3600, "attempt": None},
            "execution_activity": {"executor_command_completions_observed": 0},
        }

    def project(self, raw=None):
        (self.root / "run.json").write_text(
            json.dumps(self.raw if raw is None else raw)
        )
        return feedback.read(self.root)

    def test_predicate_eligibility_and_actual_attempt_are_independent_observations(
        self,
    ):
        expected = {
            **self.raw,
            "status": "observed",
            "kind": "host_runtime_facts_v1",
            "null_means": "unobservable (except delivery attempt: explicitly no attempt)",
            "execution_environment": {"status": "unobservable", "reason": "missing"},
            **{
                key: {"status": "observed", **self.raw[key]}
                for key in ("harness_program", "delivery_budget", "execution_activity")
            },
        }
        self.assertEqual(self.project(), expected)
        self.raw["harness_program"]["last_decision"] = True
        self.raw["delivery_budget"]["attempt"] = {
            "action": "checkpoint",
            "remaining_secs": 17699,
            "outcome": "accepted",
            "turn_id": "PRIVATE",
            "error": "PRIVATE",
        }
        self.raw["execution_activity"]["raw_commands"] = ["PRIVATE"]
        projected = self.project()
        expected["harness_program"]["last_decision"] = True
        expected["delivery_budget"]["attempt"] = {
            "status": "observed",
            "action": "checkpoint",
            "remaining_secs": 17699,
            "outcome": "accepted",
        }
        self.assertEqual(projected, expected)
        self.assertNotIn("PRIVATE", json.dumps(projected))
        self.assertLessEqual(len(json.dumps(projected).encode()), 2048)

    def test_unknown_versions_and_nonexact_v2_facts_are_not_reinterpreted(self):
        changes = (
            {"interpreter": "bounded-steering-v3"},
            {"action": "restart"},
            {"action": None},
            {"evaluations": 1 << 31},
            {"last_eligibility": {"eligible": False, "reason": "eligible"}},
            {"last_eligibility": {"eligible": False, "reason": ["PRIVATE"]}},
            {"last_eligibility": {"eligible": True, "reason": "future_rule"}},
        )
        for change in changes:
            raw = copy.deepcopy(self.raw)
            raw["harness_program"].update(change)
            with self.subTest(change=change):
                self.assertEqual(
                    self.project(raw)["harness_program"],
                    {"status": "unobservable", "reason": "malformed"},
                )
        facts = self.raw["harness_program"]["last_input"]
        for changed in (
            {key: value for key, value in facts.items() if key != "repairs_used"},
            {**facts, "raw_command": "PRIVATE"},
            {**facts, "deadline_secs": 0},
            {**facts, "executor_command_completions_observed": True},
            {**facts, "executor_command_completions_observed": 1 << 31},
        ):
            raw = copy.deepcopy(self.raw)
            raw["harness_program"]["last_input"] = changed
            self.assertEqual(
                self.project(raw)["harness_program"],
                {"status": "unobservable", "reason": "malformed"},
            )

    def test_missing_activity_action_and_unevaluated_input_remain_unknown(self):
        del self.raw["execution_activity"]
        self.raw["harness_program"].update(
            evaluations=0, last_input=None, last_decision=None, last_eligibility=None
        )
        projected = self.project()
        self.assertEqual(
            projected["execution_activity"],
            {"status": "unobservable", "reason": "missing"},
        )
        self.assertEqual(
            projected["harness_program"],
            {"status": "observed", **self.raw["harness_program"]},
        )
        for value in (None, True, -1, 1 << 31):
            self.raw["execution_activity"] = {
                "executor_command_completions_observed": value
            }
            self.assertEqual(
                self.project()["execution_activity"],
                {"status": "unobservable", "reason": "malformed"},
            )
        for action in (None, "restart", True):
            attempt = {"remaining_secs": 100, "outcome": "accepted"}
            if action is not None:
                attempt["action"] = action
            self.raw["delivery_budget"]["attempt"] = attempt
            self.assertEqual(
                self.project()["delivery_budget"]["attempt"],
                {"status": "unobservable", "reason": "malformed"},
            )

    def test_research_archive_preserves_v2_projection_and_freezes_observations(self):
        h = host(campaign(str(self.root)), FakeTasks())
        version = h.incumbent()
        h.dev(version)
        observed = h.observed()
        name = f"dev-{version[:12]}-{DEV[0]}"
        run_dir = Path(observed[name]["run_dir"])
        (run_dir / "run.json").write_text(json.dumps(self.raw))
        expected = feedback.read(run_dir)
        archive = h.stage_research(version, 1) / "workspace/archive"
        summary = json.loads((archive / "runs" / name / "summary.json").read_text())
        self.assertEqual(
            (summary["validity"], summary["runtime_receipt"]), ("valid", expected)
        )
        self.assertEqual(
            {path.name for path in (archive / "runs").iterdir()}, set(observed)
        )
        self.assertEqual(
            {path.name for path in (archive / "tasks").iterdir()}, set(DEV)
        )
        saved = (h.camp / "observations" / name / "summary.json").read_bytes()
        (run_dir / "run.json").write_text("malformed")
        h.observe(name, observed[name])
        self.assertEqual(
            (h.camp / "observations" / name / "summary.json").read_bytes(), saved
        )
