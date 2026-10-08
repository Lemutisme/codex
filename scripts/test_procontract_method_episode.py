"""Paired updater isolation with the real Host/store and an offline runner transport."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_method_episode as episode
import procontract_rsi as rsi
import procontract_store as store
import procontract_succession as succession
import test_procontract_rsi as fixtures


RUNNER = ["method-episode-offline-transport"]
METHODS = ("analyst.md", "challenger.md", "research.md")


def files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class MethodEpisodeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.camp = fixtures.stream_campaign(temporary.name, batch=1)
        self.tasks = fixtures.FakeTasks()
        self.host = rsi.Host(self.camp, adapter=self.tasks, runner=RUNNER)
        self.target = self.host.incumbent()
        self.task = self.host.order()[0]
        self.host.measure(self.target, self.task, "stream")
        self.batch = {
            "batch": 1,
            "phase": "serve",
            "version": self.target,
            "expected_incumbent": self.target,
            "expected_incumbent_seq": succession.incumbent_record(self.host)["seq"],
            "tasks": [self.task],
        }
        self.host.record("assignment", self.batch)
        knowledge = self.camp / "knowledge-seed"
        knowledge.mkdir()
        (knowledge / "mechanisms.md").write_text("Shared initial knowledge.\n")
        candidate = self.root / "candidate"
        shutil.copytree(self.host.version_dir(self.target) / "bundle", candidate)
        for name in METHODS:
            path = candidate / name
            path.write_text(path.read_text() + "\nCANDIDATE_METHOD_PRIVATE\n")
        self.candidate = self.host.register(
            candidate, self.target, self.target, "CANDIDATE_EXPERIMENT_PRIVATE"
        )
        self.preparations = []
        self.launches = []
        self.mode = "changed"
        original = rsi.subprocess.run

        def transport(args, **kwargs):
            if args[: len(RUNNER)] != RUNNER:
                return original(args, **kwargs)
            return self.transport(args)

        patch = mock.patch.object(rsi.subprocess, "run", side_effect=transport)
        patch.start()
        self.addCleanup(patch.stop)

    def transport(self, args):
        phase = args[len(RUNNER)]
        rest = list(args[len(RUNNER) + 1 :])
        if "--no-reference" in rest:
            rest.remove("--no-reference")
        options = dict(zip(rest[::2], rest[1::2]))
        run = Path(options["--run-dir"])
        if phase == "prepare":
            role = options["--instructions"]
            producer = Path(options["--policy"]).parent.name
            source = Path(options["--workspace-from"])
            self.preparations.append((role, producer, files(source)))
            run.mkdir(parents=True)
            shutil.copytree(source, run / "workspace")
            shutil.copytree(options["--policy"], run / "policy")
            (run / "manifest.json").write_text(
                json.dumps({"instructions": role, "producer": producer})
            )
            return subprocess.CompletedProcess(args, 0)

        self.assertEqual(phase, "run")
        manifest = json.loads((run / "manifest.json").read_text())
        role, producer = manifest["instructions"], manifest["producer"]
        instructions = (run / "policy" / role).read_text()
        method = (
            "candidate" if "CANDIDATE_METHOD_PRIVATE" in instructions else "control"
        )
        self.assertTrue((run.parent / "launch-claim.json").is_file())
        self.launches.append((role, producer, options["--deadline-secs"]))
        if self.mode == "unknown":
            raise InterruptedError("transport lost before a terminal receipt")
        workspace = run / "workspace"
        if role == "analyst.md":
            if self.mode != "bad_analysis":
                (workspace / "ANALYSIS.md").write_text(
                    "Observed a general mechanism.\n"
                )
            (workspace / "hindsight.json").write_text(json.dumps({"clusters": []}))
            with (workspace / "knowledge" / "mechanisms.md").open("a") as handle:
                handle.write(f"Private analysis by {method}.\n")
        elif role == "challenger.md":
            (workspace / "CHALLENGE.md").write_text("Checked the analysis.\n")
        else:
            self.assertEqual(role, "research.md")
            (workspace / "EXPERIMENT.md").write_text(
                "".join(
                    f"## {name}\nA bounded experiment.\n"
                    for name in rsi.EXPERIMENT_SECTIONS
                )
            )
            if self.mode == "harness":
                (workspace / "policy" / "harness.json").write_text(
                    json.dumps({"schema": 1, "when": {"always": False}})
                )
            elif self.mode != "null":
                name = (
                    "research.md" if self.mode == "forbidden_method" else "executor.md"
                )
                path = workspace / "policy" / name
                path.write_text(path.read_text() + f"\nIntervention by {method}.\n")
        (run / "run.json").write_text(json.dumps({"turn_statuses": ["completed"]}))
        return subprocess.CompletedProcess(
            args, 9 if self.mode == "runner_failed" else 0
        )

    def plan(self):
        return {
            "candidate": self.candidate,
            "confirmation": self.candidate,
            "incumbent": self.target,
            "incumbent_seq": self.batch["expected_incumbent_seq"],
            "class": "paired_updater_v1",
            "tasks": fixtures.SEALED[:1],
            "gate": {
                "confirm_tasks": 1,
                "confirm_min_wins": 1,
                "confirm_min_delta": 0.0,
            },
            "input": episode.freeze_input(self.host, self.batch),
            "batch_id": 1,
            "root_id": self.candidate,
            "deadlines": {"analyst": 31, "challenger": 31, "research": 47},
            "role_attempts": 1,
        }

    def test_frozen_input_excludes_other_tasks_methods_and_confirmation(self):
        other = self.host.order()[1]
        self.host.measure(self.target, other, "stream")
        sealed = fixtures.SEALED[0]
        self.host.record("assignment", {"confirmation": "earlier", "tasks": [sealed]})
        self.host.measure(self.target, sealed, "confirm")
        receipt = episode.freeze_input(self.host, self.batch)
        snapshot = self.root / "snapshot"
        store.materialize(self.host.store, receipt["subject"], snapshot)
        text = "\n".join(
            content.decode("utf-8") for content in files(snapshot).values()
        )
        self.assertEqual(
            {
                key: receipt[key]
                for key in (
                    "schema",
                    "target",
                    "batch_id",
                    "tasks",
                    "runs",
                    "knowledge",
                )
            },
            {
                "schema": 1,
                "target": self.target,
                "batch_id": 1,
                "tasks": [self.task],
                "runs": [f"stream-{self.target[:12]}-{self.task}"],
                "knowledge": rsi.knowledge_identity(self.host.current_knowledge()),
            },
        )
        self.assertIn("Shared initial knowledge.", text)
        for excluded in (
            other,
            sealed,
            "CANDIDATE_METHOD_PRIVATE",
            "CANDIDATE_EXPERIMENT_PRIVATE",
        ):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, text)
        episode.verify_input(self.host, receipt)

    def test_paired_actors_share_inputs_without_changing_global_learning(self):
        plan = self.plan()
        before = (self.host.insights(), files(self.host.current_knowledge()))
        control = episode.run_arm(self.host, plan, self.target, "control")
        candidate = episode.run_arm(self.host, plan, self.candidate, "candidate")
        self.assertEqual(
            [(role, actor, deadline) for role, actor, deadline in self.launches],
            [
                (role, actor, str(plan["deadlines"][role.removesuffix(".md")]))
                for actor in (self.target, self.candidate)
                for role in METHODS
            ],
        )
        self.assertEqual(self.preparations[0][2], self.preparations[3][2])
        research_inputs = [
            value for role, _, value in self.preparations if role == "research.md"
        ]
        self.assertEqual(
            [
                {name: raw for name, raw in value.items() if name.startswith("policy/")}
                for value in research_inputs
            ],
            [
                {
                    f"policy/{name}": raw
                    for name, raw in files(
                        self.host.version_dir(self.target) / "bundle"
                    ).items()
                }
            ]
            * 2,
        )
        self.assertEqual(
            (self.host.insights(), files(self.host.current_knowledge())), before
        )
        self.assertEqual(
            [control["status"], candidate["status"]], ["qualified", "qualified"]
        )
        self.assertNotEqual(control["descendant"], candidate["descendant"])
        for arm, actor, receipt in (
            ("control", self.target, control),
            ("candidate", self.candidate, candidate),
        ):
            with self.subTest(arm=arm):
                self.assertEqual(
                    (receipt["producer"], receipt["arm"], receipt["input_subject"]),
                    (actor, arm, plan["input"]["subject"]),
                )
                descendant = self.host.version_dir(receipt["descendant"]) / "bundle"
                self.assertEqual(
                    {name: (descendant / name).read_bytes() for name in METHODS},
                    {
                        name: (
                            self.host.version_dir(self.target) / "bundle" / name
                        ).read_bytes()
                        for name in METHODS
                    },
                )
                episode.verify_arm(self.host, plan, actor, arm, receipt)
        launches = list(self.launches)
        reopened = rsi.Host(self.camp, adapter=self.tasks, runner=RUNNER)
        self.assertEqual(
            episode.run_arm(reopened, plan, self.candidate, "candidate"), candidate
        )
        self.assertEqual(self.launches, launches)

    def test_null_update_is_the_common_target_not_a_new_method_version(self):
        self.mode = "null"
        receipt = episode.run_arm(self.host, self.plan(), self.candidate, "candidate")
        self.assertEqual(
            (receipt["status"], receipt["descendant"], self.host.incumbent()),
            ("qualified", self.target, self.target),
        )

    def test_later_campaign_knowledge_does_not_change_the_second_arm_input(self):
        plan = self.plan()
        episode.run_arm(self.host, plan, self.target, "control")
        path = self.host.current_knowledge() / "mechanisms.md"
        path.write_text(
            path.read_text() + "New global knowledge after the control arm.\n"
        )
        self.host.measure(self.target, self.host.order()[1], "stream")
        episode.run_arm(self.host, plan, self.candidate, "candidate")
        self.assertEqual(self.preparations[0][2], self.preparations[3][2])
        self.assertNotIn(
            b"New global knowledge after the control arm.",
            b"\n".join(self.preparations[3][2].values()),
        )

    def test_registered_sibling_cannot_replace_the_sealed_research_descendant(self):
        plan = self.plan()
        receipt = episode.run_arm(self.host, plan, self.candidate, "candidate")
        sibling = self.root / "unrelated-child"
        shutil.copytree(self.host.version_dir(self.target) / "bundle", sibling)
        executor = sibling / "executor.md"
        executor.write_text(executor.read_text() + "\nAn unrelated intervention.\n")
        replacement = self.host.register(
            sibling, self.target, self.candidate, "Not this trial's research delivery."
        )
        altered = {**receipt, "descendant": replacement}
        result = (
            self.camp / "method-trials" / self.candidate / "candidate" / "result.json"
        )
        result.write_text(json.dumps(altered))
        launches = list(self.launches)
        with self.assertRaises(RuntimeError):
            episode.verify_arm(self.host, plan, self.candidate, "candidate", altered)
        self.assertEqual(self.launches, launches)

    def test_candidate_role_cannot_have_loaded_the_control_producer(self):
        plan = self.plan()
        receipt = episode.run_arm(self.host, plan, self.candidate, "candidate")
        loaded = (
            self.camp
            / "method-trials"
            / self.candidate
            / "candidate"
            / "analyst"
            / "run"
            / "policy"
        )
        shutil.rmtree(loaded)
        shutil.copytree(self.host.version_dir(self.target) / "bundle", loaded)
        launches = list(self.launches)
        with self.assertRaisesRegex(RuntimeError, "loaded another producer"):
            episode.verify_arm(self.host, plan, self.candidate, "candidate", receipt)
        self.assertEqual(self.launches, launches)

    def test_changed_deadline_cannot_reuse_a_completed_arm_or_launch_again(self):
        plan = self.plan()
        episode.run_arm(self.host, plan, self.candidate, "candidate")
        plan["deadlines"]["research"] += 1
        launches = list(self.launches)
        with self.assertRaises(RuntimeError):
            episode.run_arm(self.host, plan, self.candidate, "candidate")
        self.assertEqual(self.launches, launches)

    def test_forbidden_method_edit_cannot_qualify(self):
        self.mode = "forbidden_method"
        before = self.host.versions()
        receipt = episode.run_arm(self.host, self.plan(), self.candidate, "candidate")
        self.assertEqual((receipt["status"], self.host.versions()), ("failed", before))
        self.assertTrue(receipt["reason"])

    def test_harness_only_descendant_is_not_folded_into_the_target(self):
        self.mode = "harness"
        receipt = episode.run_arm(self.host, self.plan(), self.candidate, "candidate")
        self.assertEqual(receipt["status"], "qualified")
        self.assertNotEqual(receipt["descendant"], self.target)
        self.assertEqual(self.host.twin(receipt["descendant"]), receipt["descendant"])
        target = self.host.version_dir(self.target) / "bundle"
        descendant = self.host.version_dir(receipt["descendant"]) / "bundle"
        self.assertEqual(
            {name: (descendant / name).read_bytes() for name in rsi.BUNDLE_FILES},
            {name: (target / name).read_bytes() for name in rsi.BUNDLE_FILES},
        )

    def test_failed_delivery_stops_the_arm_without_retry_or_child(self):
        for mode in ("bad_analysis", "runner_failed"):
            with self.subTest(mode=mode):
                self.mode = mode
                plan = self.plan()
                arm = "control" if mode == "bad_analysis" else "candidate"
                actor = self.target if arm == "control" else self.candidate
                before, count = self.host.versions(), len(self.launches)
                receipt = episode.run_arm(self.host, plan, actor, arm)
                self.assertEqual(
                    (
                        receipt["status"],
                        self.host.versions(),
                        len(self.launches) - count,
                    ),
                    ("failed", before, 1),
                )
                self.assertEqual(episode.run_arm(self.host, plan, actor, arm), receipt)
                self.assertEqual(len(self.launches) - count, 1)

    def test_unknown_launch_is_not_retried_after_restart(self):
        self.mode = "unknown"
        plan = self.plan()
        with self.assertRaises(InterruptedError):
            episode.run_arm(self.host, plan, self.candidate, "candidate")
        reopened = rsi.Host(self.camp, adapter=self.tasks, runner=RUNNER)
        with self.assertRaisesRegex(RuntimeError, "unreconciled"):
            episode.run_arm(reopened, plan, self.candidate, "candidate")
        self.assertEqual(len(self.launches), 1)


if __name__ == "__main__":
    unittest.main()
