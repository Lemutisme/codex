"""Evidence gates reject ACK-only, unbound method, and cosmetic H changes."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import procontract_online as online
from procontract_online_lineage import Lineage
from procontract_online_acceptance import assess
from test_procontract_online import candidate


def fixture():
    with tempfile.TemporaryDirectory() as temporary:
        lineage = Lineage(
            Path(temporary) / "lineage",
            selection_scope="a" * 64,
            selection_mode="coverage",
        )
        versions = {online.digest(online.seed()): online.seed()}
        results = []
        for index in range(3):
            key = f"{index}-adaptive"
            allocation = lineage.begin(key, 14400, 900)
            parent = lineage.version(allocation["parent"])
            trial = {"allocation": allocation}
            trace = {"evidence": {"status": "unknown", "reason": "no steer"}}
            if index < 2:
                packet = lineage.claim(key, {})
                child, raw = candidate(parent, str(index))
                child["harness"]["when"] = {
                    "command_completions_observed_gte": 6 + index * 2
                }
                body = json.loads(raw)
                body["harness_json"] = json.dumps(child["harness"])
                body["prediction"] = json.dumps(
                    {
                        "metric": "canonical_fraction",
                        "direction": "at_least",
                        "threshold": 0.5,
                    }
                )
                lineage.register(key, online.encoded(body))
                versions[online.digest(child)] = child
                lineage.dispatch(key, {"outcome": "accepted"})
                facts = {
                    "deadline_secs": 13500,
                    "remaining_secs": 13000,
                    "turns_completed": 0,
                    "repairs_used": 0,
                    "executor_command_completions_observed": 4 + index * 2,
                }
                trial.update(
                    candidate=online.digest(child),
                    dispatch={"attempt": {"outcome": "accepted"}},
                    research={
                        "status": "completed",
                        "native_exit": 0,
                        "input_binding": {
                            "packet_sha256": online.digest(packet),
                            "producer_method": online.digest(parent["research"]),
                        },
                    },
                    harness_decision_difference={
                        "parent": online.digest(parent["harness"]),
                        "candidate": online.digest(child["harness"]),
                        "facts": facts,
                        "parent_decision": True,
                        "candidate_decision": False,
                    },
                )
                trace = {"evidence": {"status": "observed", "fixture": index}}
            lineage.finish_trial(
                key, status="observing", reason="", commands_after_ack=0
            )
            reward = lineage.reward(
                key,
                resolved=3,
                total=5,
                submission_sha256="b" * 64,
                evaluator_sha256="c" * 64,
                selection_evidence={
                    "native_secs": 100,
                    "research_secs": 10,
                    "grading_secs": 1,
                    "episode_secs": 18000,
                    "commands": 10,
                    "failed_commands": 2,
                    "commands_with_exit": 10,
                    "input_witness": online.digest(trace) if index < 2 else None,
                },
            )
            results.append(
                {
                    "episode": key,
                    "status": "scored",
                    "outcome": {
                        "valid": True,
                        "resolved": 3,
                        "total": 5,
                        "submission_sha256": "b" * 64,
                    },
                    "online": trial,
                    "native_context_evidence": trace,
                    "learning_reward": reward,
                }
            )
        return (
            {"tasks": ["a", "b", "c"], "arms": ["adaptive"]},
            results,
            lineage.events(),
            versions,
        )


class AcceptanceTests(unittest.TestCase):
    def test_two_generations_and_real_decision_differences_are_not_a_gain_certificate(
        self,
    ):
        report = assess(*fixture(), evidence_kind="synthetic")
        self.assertEqual(
            (
                report["status"],
                report["recursive_links"],
                report["harness_witnesses"],
                report["policy_after_feedback"],
            ),
            (
                "PASS",
                [("0-adaptive", "1-adaptive")],
                ["0-adaptive", "1-adaptive"],
                ["2-adaptive"],
            ),
        )
        self.assertEqual(
            (report["benefit"], report["interactive_product"]),
            ("NOT_ESTABLISHED", "NOT_TESTED"),
        )

    def test_missing_model_consumption_or_wrong_method_binding_fails(self):
        for kind in ("ack_only", "wrong_method", "wrong_packet", "bad_reward"):
            plan, results, events, versions = fixture()
            result = results[1]
            if kind == "ack_only":
                result["native_context_evidence"]["evidence"]["status"] = "unknown"
            elif kind == "wrong_method":
                result["online"]["research"]["input_binding"]["producer_method"] = (
                    "f" * 64
                )
            elif kind == "wrong_packet":
                result["online"]["research"]["input_binding"]["packet_sha256"] = (
                    "f" * 64
                )
            else:
                result["outcome"]["resolved"] = 5
            with self.subTest(kind=kind):
                report = assess(
                    plan, results, events, versions, evidence_kind="synthetic"
                )
                self.assertEqual(
                    report["gates"]["two_recursive_method_generations"], "FAIL"
                )
                self.assertEqual(report["status"], "FAIL")

    def test_changed_h_digest_or_self_report_without_different_evaluated_decision_is_not_enough(
        self,
    ):
        plan, results, events, versions = fixture()
        for result in results[:2]:
            result["online"]["harness_decision_difference"]["parent_decision"] = False
        report = assess(plan, results, events, versions, evidence_kind="synthetic")
        self.assertEqual(report["gates"]["changed_harness_decision_executed"], "FAIL")

    def test_missing_or_failed_final_policy_episode_is_not_silently_dropped(self):
        plan, results, events, versions = fixture()
        failed = copy.deepcopy(results)
        failed[-1] = {"episode": "2-adaptive", "status": "failed", "outcome": None}
        report = assess(plan, failed, events, versions, evidence_kind="synthetic")
        self.assertEqual(report["failed_episodes"], ["2-adaptive"])
        self.assertEqual(report["gates"]["unforced_selection_after_feedback"], "FAIL")
        report = assess(plan, results[:-1], events, versions, evidence_kind="synthetic")
        self.assertEqual(report["unreported_episodes"], ["2-adaptive"])
        self.assertEqual(report["gates"]["planned_matrix_terminal"], "FAIL")


if __name__ == "__main__":
    unittest.main()
