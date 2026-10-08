"""Real Host/store, deterministic peers: proves recursion plumbing, not model improvement."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_harness_program as harness
import procontract_rsi as rsi
import test_procontract_rsi as fixtures
from testing import recursive_research_runner as peer

RUNNER = [sys.executable, str(Path(peer.__file__).resolve())]


class ActivatedTasks(fixtures.FakeTasks):
    def run_and_label(self, host, bundle, task, run_dir):
        peer.prepare(run_dir, bundle, "executor.md")
        result = super().run_and_label(host, bundle, task, run_dir)
        path = run_dir / "run.json"
        peer.write_json(
            path,
            {
                **json.loads(path.read_text()),
                **peer.activation(run_dir / "policy", "executor.md"),
            },
        )
        return result


class RecursiveEngineTest(unittest.TestCase):
    def test_three_batches_inherit_methods_and_execute_programs_after_restart(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "crash"}),
        ):
            seed = Path(tmp, "seed")
            shutil.copytree(rsi.V0_BUNDLE, seed)
            for name in rsi.BUNDLE_FILES:
                path = seed / name
                path.write_text(path.read_text() + "\nPEER_STAGE=0\n")
            peer.write_json(
                seed / harness.PROGRAM_FILE,
                {"schema": 1, "when": {"remaining_fraction_lte": [1, 20]}},
            )
            missing = Path(tmp, "missing-feedback")
            peer.prepare(missing, seed, "research.md")
            with self.assertRaisesRegex(ValueError, "scored feedback"):
                peer.run(missing)
            with mock.patch.object(rsi, "V0_BUNDLE", seed):
                camp = fixtures.stream_campaign(tmp)
            tasks = ActivatedTasks()
            host = rsi.Host(camp, adapter=tasks, runner=RUNNER)
            root = host.incumbent()
            host.stream_step()
            # Reopen the real persisted campaign between generations.
            host = rsi.Host(camp, adapter=tasks, runner=RUNNER)
            host.stream_step()
            host = rsi.Host(camp, adapter=tasks, runner=RUNNER)
            host.stream_step()
            versions = [batch["version"] for batch in host.batches()]
            self.assertEqual((versions[0], len(set(versions))), (root, 3))
            self.assertEqual(
                [host.versions()[vid]["lineage"] for vid in versions],
                [
                    {"parent": None, "proposed_by": "operator"},
                    {"parent": versions[0], "proposed_by": versions[0]},
                    {"parent": versions[1], "proposed_by": versions[1]},
                ],
            )
            self.assertEqual([host.twin(vid) for vid in versions], versions)
            for index, version in enumerate(versions):
                bundle = host.version_dir(version) / "bundle"
                program = harness.load(bundle)
                self.assertEqual(
                    host.versions()[version]["harness"],
                    {"sha256": program.digest, "interpreter": harness.INTERPRETER},
                )
                self.assertEqual(
                    [peer.stage((bundle / name).read_text()) for name in peer.METHODS],
                    [index] * 3,
                )
                self.assertEqual(
                    (bundle / "executor.md").read_text(),
                    (seed / "executor.md").read_text(),
                )
                task_runs = [
                    Path(row["run_dir"])
                    for row in host.observed().values()
                    if row["version"] == version
                ]
                role_runs = [
                    path.parent
                    for path in (camp / "insight").glob("*/**/run.json")
                    if json.loads(path.read_text()).get("method_stage") == index
                ]
                if index < 2:
                    role_runs.append(camp / "research" / f"step-{index + 1}" / "run")
                self.assertEqual(
                    {
                        json.loads((path / "run.json").read_text())["instructions"]
                        for path in role_runs
                    },
                    set(peer.METHODS) if index < 2 else set(peer.METHODS[1:]),
                )
                for path in task_runs + role_runs:
                    receipt = json.loads((path / "run.json").read_text())
                    role = receipt["instructions"]
                    self.assertEqual(
                        json.loads((path / "manifest.json").read_text()),
                        {
                            "instructions": role,
                            "harness_program": {
                                "sha256": program.digest,
                                "interpreter": harness.INTERPRETER,
                            },
                        },
                    )
                    self.assertEqual(
                        receipt["instruction_sha256"],
                        hashlib.sha256((bundle / role).read_bytes()).hexdigest(),
                    )
                    remaining = 5 * (index + 1)
                    self.assertEqual(
                        (receipt["steer_calls"], receipt["steer_at_remaining"]),
                        (1, remaining),
                    )
                    self.assertEqual(
                        receipt["delivery_budget"],
                        {
                            "reserve_secs": 25,
                            "attempt": {
                                "turn_id": "peer-turn",
                                "remaining_secs": remaining,
                                "outcome": "accepted",
                            },
                        },
                    )
                    self.assertEqual(
                        receipt["harness_program"],
                        {
                            "sha256": program.digest,
                            "interpreter": harness.INTERPRETER,
                            "evaluations": 3 - index,
                            "last_input": {
                                "deadline_secs": 100,
                                "remaining_secs": remaining,
                                "turns_completed": 0,
                                "repairs_used": 0,
                            },
                            "last_decision": True,
                        },
                    )
                if index < 2:
                    research = json.loads((role_runs[-1] / "run.json").read_text())
                    self.assertEqual(
                        (research["method_stage"], research["produced_stage"]),
                        (index, index + 1),
                    )
                    self.assertEqual(
                        sorted(research["feedback"], key=lambda row: row["task"]),
                        [
                            {"task": task, "pass_rate": 0.5}
                            for task in sorted(host.order()[: 2 * (index + 1)])
                        ],
                    )
            executions = list(tasks.runs)
            self.assertEqual(
                sorted(executions),
                sorted(
                    (batch["version"], task)
                    for batch in host.batches()
                    for task in batch["tasks"]
                ),
            )
            receipts = {str(path): path.read_bytes() for path in camp.rglob("run.json")}
            resumed = rsi.Host(camp, adapter=tasks, runner=RUNNER)
            for version, task in executions:
                resumed.measure(version, task, "stream")
            self.assertEqual(resumed.stream_step(), "the stream is complete")
            self.assertEqual(tasks.runs, executions)
            self.assertEqual(
                {str(path): path.read_bytes() for path in camp.rglob("run.json")},
                receipts,
            )
            self.assertEqual(
                {row["pass_rate"] for row in resumed.observed().values()}, {0.5}
            )


if __name__ == "__main__":
    unittest.main()
