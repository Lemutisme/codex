"""Real Host/store and budget decisions; synthetic grades prove routing, not model gains."""

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_harness_program as harness
import procontract_rsi as rsi
import procontract_store as store
import test_procontract_rsi as fixtures
from test_procontract_recursive_engine import ActivatedTasks
from test_procontract_recursive_engine import RUNNER
from testing import recursive_research_runner as peer


class GradedTasks(ActivatedTasks):
    def __init__(self, quality="behavior"):
        super().__init__()
        self.quality = quality

    def run_and_label(self, host, bundle, task, run_dir):
        result = super().run_and_label(host, bundle, task, run_dir)
        receipt = json.loads((run_dir / "run.json").read_text())
        # This predeclared toy evaluator observes an actual DeliveryBudget/turn-steer decision.
        score = (
            0.5
            if self.quality == "tie"
            else {5: 0.5, 10: 0.6, 15: 0.7}[receipt["steer_at_remaining"]]
        )
        result["pass_rate"] = score
        result["label"]["outcome"]["pass_rate"] = score
        return result


class GuardedStreamTest(unittest.TestCase):
    def make_host(self, *, adoption="presumed", quality="behavior", mode="guarded"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        seed = root / "seed"
        shutil.copytree(rsi.V0_BUNDLE, seed)
        for name in rsi.BUNDLE_FILES:
            path = seed / name
            path.write_text(path.read_text() + "\nPEER_STAGE=0\n")
        peer.write_json(
            seed / harness.PROGRAM_FILE,
            {
                "schema": 1,
                "when": {"remaining_fraction_lte": [1, 20]},
            },
        )
        sealed = root / "sealed.json"
        peer.write_json(sealed, {"select": fixtures.SEALED})
        main = rsi.main

        def initialize():
            extra = (
                []
                if mode == "explore"
                else [
                    "--stream-mode",
                    "guarded",
                    "--release-every",
                    "1",
                    "--sealed",
                    str(sealed),
                    "--task-attempts",
                    "1",
                    "--confirm-tasks",
                    "3",
                    "--confirm-min-wins",
                    "2",
                    "--adoption",
                    adoption,
                ]
            )
            with mock.patch.object(sys, "argv", [*sys.argv, *extra]):
                main()

        with (
            mock.patch.object(rsi, "V0_BUNDLE", seed),
            mock.patch.object(rsi, "main", side_effect=initialize),
        ):
            camp = fixtures.stream_campaign(temporary.name, batch=1)
        return rsi.Host(camp, adapter=GradedTasks(quality), runner=RUNNER)

    def reopen(self, host):
        return rsi.Host(host.camp, adapter=host.adapter, runner=RUNNER)

    def assert_activation(self, host, path, version, role, stage):
        receipt = json.loads(path.read_text())
        bundle = host.version_dir(version) / "bundle"
        self.assertEqual(
            (
                receipt["instructions"],
                receipt["method_stage"],
                receipt["instruction_sha256"],
                receipt["harness_program"]["sha256"],
                receipt["steer_calls"],
                receipt["steer_at_remaining"],
            ),
            (
                role,
                stage,
                hashlib.sha256((bundle / role).read_bytes()).hexdigest(),
                harness.load(bundle).digest,
                1,
                5 * (stage + 1),
            ),
        )
        return receipt

    def assert_adopted_producer(self, host, adopted):
        batch = host.batches()[2]
        self.assertEqual(
            (batch["phase"], batch["version"], batch["expected_incumbent"]),
            ("serve", adopted, adopted),
        )
        receipt = self.assert_activation(
            host,
            host.camp / "research" / "step-3" / "run" / "run.json",
            adopted,
            "research.md",
            1,
        )
        self.assertEqual(receipt["produced_stage"], 2)
        successor = host.stream_policy()
        self.assertNotEqual(successor, adopted)
        self.assertEqual(
            host.versions()[successor]["lineage"],
            {"parent": adopted, "proposed_by": adopted},
        )
        records = store.events(host.store)
        adoption = next(
            r["seq"]
            for r in records
            if r["event"]["kind"] == "selection"
            and r["event"]["body"].get("role") == "incumbent"
            and r["event"]["body"]["version"] == adopted
        )
        assignment = next(
            r["seq"]
            for r in records
            if r["event"]["kind"] == "assignment"
            and r["event"]["body"].get("batch") == 3
        )
        research = next(
            r["seq"]
            for r in records
            if r["event"]["kind"] == "exposure"
            and r["event"]["body"]["view"] == "research:3"
        )
        self.assertEqual(batch["expected_incumbent_seq"], adoption)
        self.assertLess(adoption, assignment)
        self.assertLess(assignment, research)

    def test_probe_adopts_before_the_successor_serves_and_researches(self):
        host = self.make_host()
        root = host.incumbent()
        host.stream_step()
        candidate = host.stream_policy()
        self.assertNotEqual(candidate, root)
        self.assertEqual(host.used_confirmation_tasks(), [])
        self.assertEqual(host.incumbent(), root)
        host = self.reopen(host)
        host.stream_step()
        self.assertEqual(
            [(b["phase"], b["version"]) for b in host.batches()],
            [("serve", root), ("probe", candidate)],
        )
        self.assertEqual(host.incumbent(), candidate)
        self.assertEqual(
            host.contract(f"adoption.{candidate[:16]}")["standing"], "discharged"
        )
        self.assertEqual(len(host.versions()), 2)
        self.assertFalse((host.camp / "research" / "step-2").exists())
        insight = next(i for i in host.insights() if i["experiment"] == candidate)
        self.assertEqual(insight["analysis_identity"]["parent"], root)
        for role in ("analyst", "challenger"):
            self.assert_activation(
                host,
                host.camp
                / "insight"
                / str(insight["k"])
                / f"{role}-1"
                / "run"
                / "run.json",
                root,
                f"{role}.md",
                0,
            )
        archive = host.camp / "research" / "step-1" / "workspace" / "archive" / "runs"
        self.assertFalse(any(p.name.startswith("confirm-") for p in archive.iterdir()))
        host = self.reopen(host)
        host.stream_step()
        self.assert_adopted_producer(host, candidate)
        successor = host.stream_policy()
        host.stream_step()
        host.stream_step()
        self.assertEqual(host.incumbent(), successor)
        self.assertEqual(
            [b["phase"] for b in host.batches()],
            ["serve", "probe", "serve", "probe", "serve"],
        )
        self.assertEqual(
            {r["pass_rate"] for r in host.observed().values()}, {0.5, 0.6, 0.7}
        )


if __name__ == "__main__":
    unittest.main()
