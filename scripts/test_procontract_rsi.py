import json
import os
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
DEV = ["dev__a.0000001", "dev__b.0000002", "dev__c.0000003"]
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


def campaign(tmp, **overrides) -> Path:
    camp = Path(tmp, "camp")
    pools = Path(tmp, "pools.json")
    pools.write_text(json.dumps({"dev": DEV + ["dev__d.0000004"]}))
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
            # The second research view never contained a confirmation task.
            exposure = [
                e["body"]
                for e in h.events("exposure")
                if e["body"]["view"] == "research:2"
            ]
            self.assertFalse(set(exposure[0]["sources"]) & set(SEALED))

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

    def test_an_invalid_run_is_retried_once_and_never_scored_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            tasks.invalid_once = {DEV[0]}
            h = host(campaign(tmp), tasks)

            results = h.dev(h.incumbent())

            self.assertEqual(results[DEV[0]], 0.5)
            self.assertEqual([t for _, t in tasks.runs].count(DEV[0]), 2)


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
