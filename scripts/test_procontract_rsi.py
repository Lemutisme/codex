import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_rsi as rsi

FAKE_RUNNER = [
    sys.executable,
    str(Path(__file__).parent / "testing" / "fake_research_runner.py"),
]
DEV = ["acme__widget.0000001", "acme__gadget.0000002", "zeta__sprocket.0000003"]
SEALED = [f"sel__t{index}.000000{index}" for index in range(8)]


class FakeTasks:
    """A task family whose hidden pass rate rewards `better` lines in executor.md and punishes
    `worse` ones; every run is valid unless the task is listed in `invalid_once`."""

    def __init__(self):
        self.runs = []
        self.invalid_once = set()

    def environment(self):
        return {"family": "fake"}

    def evaluator(self):
        return {"metric": "pass_rate"}

    def run_and_label(self, host, bundle, task, run_dir):
        self.runs.append((bundle.parent.name, task))
        if task in self.invalid_once:
            self.invalid_once.discard(task)
            return {
                "validity": "invalid",
                "pass_rate": None,
                "reason": "the executor turn failed",
            }
        executor = (bundle / "executor.md").read_text()
        self.write_evidence(run_dir, executor.count("better"))
        rate = 0.5 + 0.1 * executor.count("better") - 0.1 * executor.count("worse")
        return {
            "validity": "valid",
            "pass_rate": round(rate, 3),
            "failures": "t1: assert\n",
            "label": {
                "task": task,
                "evaluator_epoch": "e" * 64,
                "outcome": {"pass_rate": rate},
            },
        }

    def witness(self, host, vid):
        return ""

    @staticmethod
    def write_evidence(run_dir, wins):
        """Hidden tests m.A.t0..t2 where the first `wins` pass, and one executor rollout whose
        reference calls and file writes grow with `wins`."""
        results = [
            {"name": f"m.A.t{i}", "status": "passed" if i < wins else "failure"}
            for i in range(3)
        ]
        eval_file = run_dir / "eval" / "attempt-1" / "task" / "task.eval.json"
        eval_file.parent.mkdir(parents=True)
        eval_file.write_text(json.dumps({"test_results": results}))
        calls = [{"type": "custom_tool_call", "input": "./executable --help"}] * (
            1 + wins
        )
        calls += [{"type": "function_call", "arguments": "apply_patch"}]
        (run_dir / "run.json").write_text(json.dumps({"thread_id": "x"}))
        rollout = run_dir / "codex-home" / "sessions" / "2026" / "rollout-x.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text(
            "".join(json.dumps({"payload": call}) + "\n" for call in calls)
        )

    def items(self, run_dir):
        return rsi.ProgramBench.items(self, run_dir)

    def outcomes(self, run_dir):
        return rsi.ProgramBench.outcomes(self, run_dir)

    def task_tokens(self, task):
        return rsi.ProgramBench.task_tokens(self, task)

    def oracle_patterns(self):
        return rsi.ProgramBench.oracle_patterns(self)


def campaign(tmp, **overrides) -> Path:
    camp = Path(tmp, "camp")
    pools = Path(tmp, "pools.json")
    pools.write_text(json.dumps({"dev": DEV + ["acme__extra.0000004"]}))
    sealed = Path(tmp, "sealed.json")
    sealed.write_text(
        json.dumps({"select": SEALED, "confirm": ["never__used.0000009"]})
    )
    codex = Path(tmp, "codex")
    codex.write_text("binary")
    prompt = Path(tmp, "prompt.txt")
    prompt.write_text("Implement the program.")
    argv = [
        "rsi",
        "init",
        "--camp",
        str(camp),
        "--pools",
        str(pools),
        "--sealed",
        str(sealed),
        "--codex-bin",
        str(codex),
        "--task-prompt",
        str(prompt),
        "--research-image",
        "img",
        "--programbench",
        tmp,
        "--hf-revision",
        "rev",
        "--dev",
        *DEV,
        "--confirm-pool",
        "8",
        "--confirm-tasks",
        "3",
        "--confirm-min-wins",
        "2",
        "--research-steps",
        "4",
    ]
    for flag, value in overrides.items():
        argv += [f"--{flag.replace('_', '-')}", str(value)]
    with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout"):
        rsi.main()
    return camp


def host(camp: Path, tasks: FakeTasks) -> rsi.Host:
    return rsi.Host(camp, adapter=tasks, runner=FAKE_RUNNER)


class SuccessionTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "better"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_init_adopts_v0_on_an_explicit_human_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = campaign(tmp)
            h = host(camp, FakeTasks())
            v0 = h.incumbent()
            adoption = h.contract(f"adoption.{v0[:16]}")
            self.assertEqual(adoption["standing"], "discharged")
            self.assertEqual(adoption["settlement"]["decision"], {"type": "explicit"})
            self.assertEqual(adoption["support"]["coordinate"]["reach"], "within")
            self.assertEqual(h.contract("campaign")["standing"], "outstanding")
            bundle = h.version_dir(v0) / "bundle"
            self.assertEqual(
                sorted(p.name for p in bundle.iterdir()), sorted(rsi.BUNDLE_FILES)
            )

    def test_a_better_candidate_is_confirmed_on_fresh_tasks_and_adopted_by_the_principal(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            h = host(campaign(tmp), tasks)
            v0 = h.incumbent()

            outcome = h.step()

            self.assertIn("awaiting the principal's adoption", outcome)
            [v1] = [vid for vid in h.versions() if vid != v0]
            self.assertEqual(
                h.versions()[v1]["lineage"], {"parent": v0, "proposed_by": v0}
            )
            self.assertEqual(h.incumbent(), v0, "confirmation alone adopts nothing")
            improvement = h.contract("improvement.1")
            self.assertEqual(improvement["standing"], "discharged")
            self.assertEqual(improvement["settlement"]["decision"]["type"], "presumed")
            self.assertEqual(improvement["support"]["coordinate"]["reach"], "beyond")
            adoption = h.contract(f"adoption.{v1[:16]}")
            self.assertEqual(adoption["support"]["coordinate"]["reach"], "beyond")
            confirmed = {task for vid, task in tasks.runs if task in SEALED}
            self.assertEqual(len(confirmed), 3)

            h.adopt(v1)

            self.assertEqual(h.incumbent(), v1)
            self.assertEqual(
                h.contract(f"adoption.{v1[:16]}")["settlement"]["decision"],
                {"type": "explicit"},
            )

    def test_the_successor_runs_the_next_research_step_and_spends_fresh_confirmation_tasks(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            h = host(campaign(tmp, adoption="presumed"), tasks)
            v0 = h.incumbent()

            h.step()
            v1 = h.incumbent()
            h.step()
            v2 = h.incumbent()

            self.assertNotIn(v0, (v1, v2))
            self.assertEqual(
                h.versions()[v2]["lineage"], {"parent": v1, "proposed_by": v1}
            )
            research = [
                e["body"]
                for e in h.events("selection")
                if e["body"]["role"] == "research_parent"
            ]
            self.assertEqual([r["version"] for r in research], [v0, v1])
            spent = h.used_confirmation_tasks()
            self.assertEqual(len(spent), 6)
            self.assertEqual(len(set(spent)), 6, "a confirmation task certifies once")
            # Each research view held its parent's development runs and never a confirmation task.
            first = [
                e["body"]
                for e in h.events("exposure")
                if e["body"]["view"] == "research:1"
            ]
            self.assertEqual(len(first[0]["sources"]), len(DEV))
            exposure = [
                e["body"]
                for e in h.events("exposure")
                if e["body"]["view"] == "research:2"
            ]
            second = {name.split("-", 2)[2] for name in exposure[0]["sources"]}
            self.assertEqual(second - set(DEV), set(spent[:3]), "only spent tasks")

    def test_the_research_view_explains_a_child_against_its_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp, adoption="presumed"), FakeTasks())
            v0 = h.incumbent()
            h.step()
            v1 = h.incumbent()
            h.step()

            view = h.camp / "research" / "step-2" / "workspace" / "archive"
            report = (view / "attribution" / f"{v1[:12]}-vs-{v0[:12]}.md").read_text()

            self.assertIn("attribution/", (view / "README.md").read_text())
            self.assertEqual(len(list((view / "attribution").iterdir())), 1)
            for task in DEV:
                self.assertIn(f"| {task} | 0.500 | 0.600 | +0.100 | 1 | 0 |", report)
            self.assertIn("acquire 1 -> 2", report)
            self.assertIn("Noise floor: 0.087", report)
            self.assertFalse(
                [p for p in (view / "attribution").iterdir() if "confirm" in p.name]
            )
            self.assertIn("## Child's Hypothesis", report)

    def test_a_worse_candidate_stays_in_research_and_the_incumbent_keeps_serving(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "worse"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()

            outcome = h.step()

            self.assertIn("stays in research", outcome)
            self.assertEqual(h.incumbent(), v0)
            self.assertEqual(h.used_confirmation_tasks(), [])
            # It regressed past the tolerance against its parent, so the next parent is the best
            # by development mean: the incumbent.
            self.assertEqual(h.choose_parent(), (v0, "best_dev_mean"))

    def test_a_method_only_candidate_is_not_measured_and_researches_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            os.environ["FAKE_RESEARCH_MODE"] = "method"
            h = host(campaign(tmp), tasks)
            v0 = h.incumbent()

            outcome = h.step()

            self.assertIn("changes only the research method", outcome)
            [v1] = [vid for vid in h.versions() if vid != v0]
            self.assertEqual(h.twin(v1), v0)
            self.assertEqual(
                len(tasks.runs), len(DEV), "only the parent's development runs"
            )
            self.assertEqual(h.dev_results(v1), h.dev_results(v0))
            self.assertEqual(h.choose_parent(), (v1, "newest_qualified"))

            os.environ["FAKE_RESEARCH_MODE"] = "better"
            h.step()

            [v2] = [vid for vid in h.versions() if vid not in (v0, v1)]
            self.assertEqual(h.versions()[v2]["lineage"]["parent"], v1)
            self.assertIn(
                "Count distinct tasks.",
                (
                    h.camp
                    / "research"
                    / "step-2"
                    / "workspace"
                    / "policy"
                    / "research.md"
                ).read_text(),
            )

    def test_a_null_experiment_completes_research_without_a_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "null"
            h = host(campaign(tmp), FakeTasks())

            outcome = h.step()

            self.assertIn("null experiment", outcome)
            self.assertEqual(len(h.versions()), 1)
            self.assertEqual(h.contract("improvement.1")["standing"], "discharged")

    def test_an_incomplete_experiment_is_released_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "incomplete"
            h = host(campaign(tmp), FakeTasks())

            outcome = h.step()

            self.assertIn("lacks Change", outcome)
            improvement = h.contract("improvement.1")
            self.assertEqual(improvement["standing"], "released")
            self.assertEqual(len(h.versions()), 1)

    def test_an_interrupted_step_resumes_instead_of_starting_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            os.environ["FAKE_RESEARCH_MODE"] = "crash"
            with self.assertRaises(rsi.subprocess.CalledProcessError):
                h.step()
            self.assertEqual(h.contract("improvement.1")["standing"], "outstanding")

            os.environ["FAKE_RESEARCH_MODE"] = "better"
            h.step()

            parents = [
                e
                for e in h.events("selection")
                if e["body"]["role"] == "research_parent"
            ]
            self.assertEqual(len(parents), 1)
            self.assertEqual(h.contract("improvement.1")["standing"], "discharged")

    def test_analysis_runs_before_the_first_research_and_its_knowledge_reaches_the_research_view(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()

            h.step()

            first = h.insight(1)
            self.assertEqual(
                (first["status"], first["verdict"], first["experiment"]),
                ("qualified", None, None),
            )
            view = h.camp / "research" / "step-1" / "workspace" / "archive"
            self.assertIn(
                "a mechanism the analyst noted",
                (view / "knowledge" / "mechanisms.md").read_text(),
            )
            self.assertEqual(
                sorted(p.name for p in (view / "insight" / "1").iterdir()),
                ["ANALYSIS.md", "CHALLENGE.md"],
            )
            self.assertNotIn("Pending experiment", (view / "README.md").read_text())
            # The second analysis settles the candidate, which the analyst's view names.
            [v1] = [vid for vid in h.versions() if vid != v0]
            second = h.insight(2)
            self.assertEqual((second["experiment"], second["verdict"]), (v1, "present"))
            readme = (
                h.camp
                / "insight"
                / "2"
                / "analyst-1"
                / "workspace"
                / "archive"
                / "README.md"
            ).read_text()
            self.assertIn(f"\nPending experiment: {v1[:12]}\n", readme)
            self.assertIn(f"| {v1[:12]} | {v0[:12]} | 0.600 | 3 |", readme)
            # The confirmation runs the step spent are new evidence; asking again adds nothing.
            self.assertEqual(h.analyze(v0), 3)
            self.assertEqual(h.analyze(v0), 3)
            self.assertEqual(len(h.insights()), 3)

    def test_knowledge_carries_from_one_steps_analysis_into_the_next_steps_analyst_workspace(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "worse"
            h = host(campaign(tmp), FakeTasks())
            h.step()
            os.environ["FAKE_RESEARCH_MODE"] = "better"

            h.step()

            workspace = h.camp / "insight" / "3" / "analyst-1" / "workspace"
            line = "- a mechanism the analyst noted\n"
            self.assertEqual(
                (workspace / "archive" / "knowledge" / "mechanisms.md").read_text(),
                line * 2,
            )
            self.assertEqual(
                (workspace / "knowledge" / "mechanisms.md").read_text(), line * 2
            )
            self.assertEqual(
                (h.current_knowledge() / "mechanisms.md").read_text(), line * 3
            )

    def test_the_seed_knowledge_appears_in_the_first_analyst_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp, "seed")
            seed.mkdir()
            (seed / "mechanisms.md").write_text("a seed claim\n")
            camp = campaign(tmp, knowledge=seed)
            h = host(camp, FakeTasks())
            v0 = h.incumbent()
            self.assertEqual(h.current_knowledge(), camp / "knowledge-seed")

            h.dev(v0)
            h.analyze(v0)

            workspace = camp / "insight" / "1" / "analyst-1" / "workspace"
            self.assertEqual(
                (workspace / "archive" / "knowledge" / "mechanisms.md").read_text(),
                "a seed claim\n",
            )
            self.assertEqual(
                (workspace / "knowledge" / "mechanisms.md").read_text(),
                "a seed claim\n",
            )
            self.assertEqual(
                (h.current_knowledge() / "mechanisms.md").read_text(),
                "a seed claim\n- a mechanism the analyst noted\n",
            )
            self.assertEqual(
                h.current_knowledge(), camp / "insight" / "1" / "knowledge"
            )

    def test_seed_knowledge_that_is_not_utf8_text_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp, "seed")
            seed.mkdir()
            (seed / "blob").write_bytes(b"\xff\xfe")
            with self.assertRaises(SystemExit):
                campaign(tmp, knowledge=seed)

    def test_a_better_candidate_whose_signature_is_absent_stays_in_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_SIGNATURE"] = "absent"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()

            outcome = h.step()

            self.assertIn("stays in research", outcome)
            self.assertIn("development delta +0.100", outcome)
            self.assertIn("signature absent", outcome)
            self.assertEqual(h.used_confirmation_tasks(), [])
            [v1] = [vid for vid in h.versions() if vid != v0]
            self.assertEqual(h.insight(2)["verdict"], "absent")
            roles = [e["body"]["role"] for e in h.events("selection")]
            self.assertNotIn("put_forward", roles)

    def test_a_failed_challenge_leaves_the_verdict_unknown_and_keeps_the_knowledge(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "log")
            os.environ["FAKE_LOG"] = str(log)
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)
            h.analyze(v0)
            kept = h.current_knowledge()
            os.environ["FAKE_CHALLENGE"] = "fail"

            outcome = h.step()

            self.assertIn("stays in research", outcome)
            self.assertIn("signature unknown", outcome)
            failed = h.insight(2)
            self.assertEqual(
                (failed["status"], failed["verdict"]), ("failed", "unknown")
            )
            self.assertIn("challenger: no CHALLENGE.md was delivered", failed["reason"])
            self.assertEqual(h.current_knowledge(), kept)
            self.assertEqual(h.used_confirmation_tasks(), [])
            self.assertFalse((h.camp / "insight" / "2" / "knowledge").exists())
            # The analysis ran once, the challenger twice (its one retry), after the first analysis.
            self.assertEqual(
                log.read_text().split(),
                ["analyst.md", "challenger.md", "research.md", "analyst.md"]
                + ["challenger.md"] * 2,
            )

    def test_a_failed_analysis_is_recorded_without_a_challenge(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_ANALYSIS"] = "fail"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)

            k = h.analyze(v0)

            body = h.insight(k)
            self.assertEqual((body["status"], body["verdict"]), ("failed", "unknown"))
            self.assertIn("analyst: no ANALYSIS.md", body["reason"])
            self.assertTrue((h.camp / "insight" / "1" / "analyst-2").exists())
            self.assertFalse((h.camp / "insight" / "1" / "challenger-1").exists())
            self.assertIsNone(h.current_knowledge())

    def test_a_candidate_that_names_a_development_task_does_not_qualify(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "leak"
            h = host(campaign(tmp), FakeTasks())

            outcome = h.step()

            self.assertIn("did not qualify", outcome)
            self.assertIn("executor.md names the exposed task token 'widget'", outcome)
            self.assertEqual(h.contract("improvement.1")["standing"], "released")
            self.assertEqual(len(h.versions()), 1)

    def test_a_candidate_that_deletes_a_task_shaping_file_is_judged_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_RESEARCH_MODE"] = "delete"
            h = host(campaign(tmp), FakeTasks())

            outcome = h.step()

            self.assertIn("candidate", outcome)
            self.assertEqual(len(h.versions()), 2)
            self.assertEqual(h.contract("improvement.1")["standing"], "discharged")

    def test_a_failed_analysis_is_tried_again_for_the_same_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)
            h.analyze(v0)
            os.environ["FAKE_CHALLENGE"] = "fail"
            h.step()
            [v1] = [vid for vid in h.versions() if vid != v0]
            self.assertEqual(h.insight(2)["status"], "failed")
            self.assertEqual(h.settled_verdict(v1), "unknown")
            del os.environ["FAKE_CHALLENGE"]

            k = h.analyze(v0)

            self.assertEqual(k, 3, "no new runs, yet the failed analysis is not final")
            self.assertEqual(h.insight(3)["experiment"], v1)
            self.assertEqual(h.settled_verdict(v1), "present")
            self.assertEqual(h.analyze(v0), 3, "a qualified analysis is final")

    def test_only_the_analysis_of_this_candidate_gives_its_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.step()
            [v1] = [vid for vid in h.versions() if vid != v0]

            # The confirmation runs brought a later analysis, about no experiment; it is not v1's.
            self.assertIsNone(h.insight(h.analyze(v0))["experiment"])
            self.assertEqual(h.settled_verdict(v1), "present")
            self.assertEqual(h.settled_verdict(v0), "unknown")
            self.assertEqual(h.settled_verdict("other"), "unknown")

    def test_a_run_that_ends_without_run_json_is_one_spent_attempt_across_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "log")
            os.environ["FAKE_LOG"] = str(log)
            os.environ["FAKE_ANALYSIS"] = "silent"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)

            h.analyze(v0)

            self.assertEqual(log.read_text().split(), ["analyst.md"] * 2)
            first = h.camp / "insight" / "1" / "analyst-1"
            h.run_agent(first, "analyst-1-1", v0, "analyst.md", 1)
            self.assertEqual(log.read_text().split(), ["analyst.md"] * 2)

    def test_a_spent_confirmation_run_enters_a_later_view_and_an_unspent_task_never_does(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp, adoption="presumed"), FakeTasks())
            v0 = h.incumbent()

            h.step()
            v1 = h.incumbent()
            spent = h.used_confirmation_tasks()
            h.step()

            self.assertEqual(len(spent), 3)
            # Not while the confirmation was still to come: analysis 2 read the candidate's
            # development runs only.
            before = h.camp / "insight" / "2" / "analyst-1" / "workspace" / "archive"
            self.assertFalse(list((before / "runs").glob("confirm-*")))
            view = h.camp / "research" / "step-2" / "workspace" / "archive"
            confirmed = {p.name for p in (view / "runs").glob("confirm-*")}
            self.assertEqual({name.split("-", 2)[2] for name in confirmed}, set(spent))
            self.assertEqual(len(confirmed), 2 * len(spent), "candidate and incumbent")
            self.assertEqual(
                {p.name for p in (view / "tasks").iterdir()}, set(DEV) | set(spent)
            )
            matrix = (view / "tasks" / spent[0] / "outcomes.md").read_text()
            for name in confirmed:
                if name.endswith(spent[0]):
                    self.assertIn(name, matrix)
            self.assertEqual(
                json.loads((view / "versions" / v1[:12] / "verdict.json").read_text())[
                    "experiment"
                ],
                v1[:12],
            )
            self.assertFalse((view / "versions" / v0[:12] / "verdict.json").exists())

    def test_an_interrupted_analysis_resumes_without_rerunning_a_finished_analyst(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "log")
            os.environ["FAKE_LOG"] = str(log)
            os.environ["FAKE_CHALLENGE"] = "crash"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)
            with self.assertRaises(rsi.subprocess.CalledProcessError):
                h.analyze(v0)
            self.assertEqual(h.insights(), [])
            del os.environ["FAKE_CHALLENGE"]

            k = h.analyze(v0)

            self.assertEqual(h.insight(k)["status"], "qualified")
            self.assertEqual(log.read_text().split(), ["analyst.md", "challenger.md"])
            exposures = [
                e["body"]["view"]
                for e in h.events("exposure")
                if "analysis" in e["body"]["view"]
            ]
            self.assertEqual(exposures, ["analysis:1"], "one view, recorded once")

    def test_analysis_restarts_when_the_runs_changed_during_an_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_CHALLENGE"] = "crash"
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.measure(v0, DEV[0], "dev")
            with self.assertRaises(rsi.subprocess.CalledProcessError):
                h.analyze(v0)
            del os.environ["FAKE_CHALLENGE"]
            h.dev(v0)

            h.analyze(v0)

            self.assertEqual(len(h.insight(1)["coverage"]), len(DEV))
            archive = h.camp / "insight" / "1" / "analyst-1" / "workspace" / "archive"
            self.assertEqual(len(list((archive / "runs").iterdir())), len(DEV))

    def test_status_lists_the_latest_verdicts_and_the_head_of_the_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            camp = campaign(tmp)
            h = host(camp, FakeTasks())
            h.step()
            (h.current_knowledge() / "proposals.md").write_text("Fix the harness.\n")

            out = io.StringIO()
            with (
                mock.patch.object(sys, "argv", ["rsi", "status", "--camp", str(camp)]),
                contextlib.redirect_stdout(out),
            ):
                rsi.main()

            status = json.loads(out.getvalue())
            self.assertEqual(
                [(a["k"], a["verdict"], a["status"]) for a in status["analyses"]],
                [(1, None, "qualified"), (2, "present", "qualified")],
            )
            self.assertEqual(status["proposals"], ["Fix the harness."])

    def test_every_valid_run_is_observed_once_with_its_trajectory_and_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            v0 = h.incumbent()
            h.dev(v0)

            h.analyze(v0)

            observed = sorted(p.name for p in (h.camp / "observations").iterdir())
            self.assertEqual(observed, sorted(f"dev-{v0[:12]}-{t}" for t in DEV))
            run = h.camp / "observations" / f"dev-{v0[:12]}-{DEV[0]}"
            summary = json.loads((run / "summary.json").read_text())
            self.assertNotIn("label", summary)
            self.assertNotIn("failures", summary)
            self.assertEqual(summary["final"], {"copied": 0, "omitted": 0})
            self.assertEqual(summary["trajectory"]["compactions"], 0)
            self.assertEqual(
                json.loads((run / "outcomes.json").read_text()),
                {f"m.A.t{i}": {"passed": False, "message": ""} for i in range(3)},
            )
            self.assertEqual((run / "failures.txt").read_text(), "t1: assert\n")
            self.assertTrue((run / "trajectory.md").exists())
            self.assertTrue((run / "events.jsonl").exists())

    def test_a_run_without_a_rollout_is_observed_with_a_null_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = host(campaign(tmp), FakeTasks())
            attempt = Path(tmp, "elsewhere", "dev-x-task", "attempt-1")
            attempt.mkdir(parents=True)
            result = {
                "validity": "valid",
                "run_dir": str(attempt),
                "pass_rate": 0.5,
                "failures": "t: boom\n",
                "label": {"task": "task"},
                "status": None,
            }

            dest = h.observe(result)

            self.assertEqual(dest, h.camp / "observations" / "dev-x-task")
            summary = json.loads((dest / "summary.json").read_text())
            self.assertIsNone(summary["trajectory"])
            self.assertEqual(summary["pass_rate"], 0.5)
            self.assertEqual(json.loads((dest / "outcomes.json").read_text()), {})
            self.assertFalse((dest / "trajectory.md").exists())
            self.assertEqual(h.observe(result), dest, "cached")

    def test_an_invalid_run_is_retried_once_and_never_scored_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            tasks.invalid_once = {DEV[0]}
            h = host(campaign(tmp), tasks)

            results = h.dev(h.incumbent())

            self.assertEqual(results[DEV[0]], 0.5)
            self.assertEqual([t for _, t in tasks.runs].count(DEV[0]), 2)


class ProgramBenchTest(unittest.TestCase):
    def test_outcomes_keep_the_message_and_omit_skipped_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "eval", "attempt-1", "t", "t.eval.json")
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "test_results": [
                            {"name": "m.T.a", "status": "passed"},
                            {
                                "name": "m.T.b",
                                "status": "failure",
                                "extra": {"message": "x" * 5000},
                            },
                            {"name": "m.T.c", "status": "skipped"},
                        ]
                    }
                )
            )

            outcomes = rsi.ProgramBench({}).outcomes(Path(tmp))

            self.assertEqual(set(outcomes), {"m.T.a", "m.T.b"})
            self.assertEqual(outcomes["m.T.a"], {"passed": True, "message": ""})
            self.assertFalse(outcomes["m.T.b"]["passed"])
            self.assertLess(len(outcomes["m.T.b"]["message"]), 1100)

    def test_task_tokens_are_the_owner_and_the_repository_but_not_the_commit(self):
        tokens = rsi.ProgramBench({}).task_tokens
        self.assertEqual(
            tokens("Yoav-Lavi__Melody.f4af9b4"),
            {"yoav-lavi", "melody", "yoav-lavi__melody"},
        )
        self.assertEqual(
            tokens("owner__re.po.0123456"), {"owner", "re.po", "owner__re.po"}
        )
        self.assertEqual(
            tokens("ab__cd.0123456"), {"ab__cd"}, "only the full name is long enough"
        )

    def test_a_repository_named_like_an_ordinary_word_is_not_a_token_by_itself(self):
        tokens = rsi.ProgramBench({}).task_tokens
        self.assertEqual(
            tokens("antonmedv__walk.1234567"), {"antonmedv", "antonmedv__walk"}
        )
        self.assertEqual(
            tokens("esubaalew__run.1234567"), {"esubaalew", "esubaalew__run"}
        )
        self.assertEqual(tokens("pls-rs__pls.4e1ae50"), {"pls-rs", "pls-rs__pls"})


class KnowledgeTest(unittest.TestCase):
    def test_knowledge_is_a_real_directory_of_regular_text_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp, "outside")
            outside.mkdir()
            (outside / "secret.md").write_text("host data\n")
            ws = Path(tmp, "ws")
            ws.mkdir()
            self.assertEqual(
                rsi.knowledge_problem(ws / "knowledge"), "knowledge/ is missing"
            )
            (ws / "knowledge").symlink_to(outside)
            self.assertEqual(
                rsi.knowledge_problem(ws / "knowledge"), "knowledge/ is a link"
            )
            (ws / "knowledge").unlink()
            (ws / "knowledge").mkdir()
            self.assertEqual(rsi.knowledge_problem(ws / "knowledge"), "")
            os.mkfifo(ws / "knowledge" / "pipe")
            self.assertIn("not a regular file", rsi.knowledge_problem(ws / "knowledge"))

    def test_a_linked_verdict_or_document_does_not_qualify_a_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp, "ws")
            (ws / "knowledge").mkdir(parents=True)
            (ws / "CHALLENGE.md").write_text("The challenge.\n")
            real = Path(tmp, "real.json")
            real.write_text(json.dumps({"experiment": "abc", "signature": "present"}))
            (ws / "verdict.json").symlink_to(real)
            self.assertEqual(
                rsi.delivery_problem(ws, "CHALLENGE.md", "abc"),
                "verdict.json is a link",
            )
            (ws / "verdict.json").unlink()
            shutil.copy(real, ws / "verdict.json")
            self.assertEqual(rsi.delivery_problem(ws, "CHALLENGE.md", "abc"), "")
            shutil.rmtree(ws / "knowledge")
            self.assertEqual(
                rsi.delivery_problem(ws, "CHALLENGE.md", "abc"), "knowledge/ is missing"
            )


class ItemsTest(unittest.TestCase):
    def items(self, payload, name="task.eval.json"):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            if payload is not None:
                path = run / "eval" / "attempt-1" / "t" / name
                path.parent.mkdir(parents=True)
                path.write_text(payload)
            return rsi.ProgramBench({}).items(run)

    def test_last_record_wins_and_skipped_tests_are_omitted(self):
        records = [
            {"name": "m.T.a", "status": "failure", "branch": "b"},
            {"name": "m.T.a", "status": "passed", "branch": "b"},
            {"name": "m.T.b", "status": "failure", "branch": "b"},
            {"name": "m.T.c", "status": "skipped"},
            {"status": "passed"},
        ]
        self.assertEqual(
            self.items(json.dumps({"test_results": records}), "t.eval.json"),
            {"m.T.a": True, "m.T.b": False},
        )

    def test_missing_or_malformed_evaluations_yield_nothing(self):
        self.assertEqual(self.items(None), {})
        self.assertEqual(self.items("{not json", "t.eval.json"), {})
        self.assertEqual(self.items("[1]", "t.eval.json"), {})


class OraclePatternTest(unittest.TestCase):
    def count(self, command):
        patterns = [re.compile(p) for p in rsi.ProgramBench({}).oracle_patterns()]
        return any(p.search(command) for p in patterns)

    def test_only_invocations_of_the_reference_count(self):
        for command in [
            "ls -l ./executable",
            "cat /workspace/executable",
            "chmod +x ./executable",
            "sha256sum ./executable",
            "grep -in ./executable notes",
            "cp ./executable ./backup",
        ]:
            self.assertFalse(self.count(command), command)
        for command in [
            "./executable --help",
            "printf a | ./executable",
            "cd x && /workspace/executable -v",
            'bash -lc "/workspace/executable a"',
            "diff <(./executable a) <(./mine a)",
            "timeout 5 ./executable",
            "for exe in ./executable ./mine; do echo $exe; done",
            "for i in 1 2; do ./executable $i; done",
            "if true; then /workspace/executable a; fi",
            r"cd /workspace\n./executable --help",
            "cd /workspace\n./executable --help",
            'tools.exec_command({cmd:"ls; FOO=1 ./executable x"})',
        ]:
            self.assertTrue(self.count(command), command)


class HelperTest(unittest.TestCase):
    def test_paired_delta_uses_shared_tasks_only(self):
        self.assertAlmostEqual(
            rsi.paired_delta({"a": 0.9, "b": 0.5}, {"a": 0.7, "c": 0.1}), 0.2
        )
        self.assertEqual(rsi.paired_delta({}, {"a": 1.0}), 0.0)

    def test_failure_excerpt_keeps_the_last_record_of_failing_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "attempt-1", "t", "t.eval.json")
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "test_results": [
                            {"name": "m.T.test_a", "status": "passed"},
                            {
                                "name": "m.T.test_a",
                                "status": "failure",
                                "extra": {"message": "boom\nmore"},
                            },
                            {"name": "m.T.test_b", "status": "passed"},
                        ]
                    }
                )
            )
            self.assertEqual(rsi.failure_excerpt(Path(tmp)), "test_a: boom\n")


if __name__ == "__main__":
    unittest.main()
