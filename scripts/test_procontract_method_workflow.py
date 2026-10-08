"""Pure-method adoption via real Host/store transactions and explicitly synthetic descendants.

The toy evaluator rewards literal executor changes, not method markers. These tests prove
isolation, authority and recursion wiring; they do not establish model or RSI capability gains.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_rsi as rsi
import procontract_store as store
import procontract_succession as succession
import test_procontract_rsi as fixtures
from testing import method_trial_runner as peer

RUNNER = [sys.executable, str(Path(peer.__file__).resolve())]


class Tasks(fixtures.FakeTasks):
    def __init__(self, quality):
        super().__init__()
        self.quality = quality
        self.heldout = []

    def run_and_label(self, host, bundle, task, run_dir):
        heldout = task in host.terms["pools"]["confirm"]
        if heldout:
            sealed = [
                event["body"]
                for event in host.events("selection")
                if event["body"]["role"] == "method_descendants"
            ]
            if not sealed or set(sealed[-1]["arms"]) != {"control", "candidate"}:
                raise AssertionError(
                    "score requested before both descendants were frozen"
                )
            self.heldout.append((bundle.parent.name, task))
        result = super().run_and_label(host, bundle, task, run_dir)
        if heldout and self.quality == "tie" and result["validity"] == "valid":
            result["pass_rate"] = result["label"]["outcome"]["pass_rate"] = 0.5
        return result


class MethodWorkflowTest(unittest.TestCase):
    def make_host(self, *, adoption="presumed", quality="behavior"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        seed = root / "seed"
        shutil.copytree(rsi.V0_BUNDLE, seed)
        for name in peer.METHODS:
            path = seed / name
            path.write_text(path.read_text() + "\nUPDATER_STAGE=0\n")
        sealed = root / "sealed.json"
        sealed.write_text(json.dumps({"select": fixtures.SEALED}))
        main = rsi.main

        def initialize():
            args = [
                *sys.argv,
                "--stream-mode",
                "guarded",
                "--method-confirmation",
                "paired-descendants",
                "--release-every",
                "1",
                "--sealed",
                str(sealed),
                "--task-attempts",
                "1",
                "--confirm-tasks",
                "2",
                "--confirm-min-wins",
                "2",
                "--adoption",
                adoption,
                "--parallel",
                "1",
            ]
            with mock.patch.object(sys, "argv", args):
                main()

        with (
            mock.patch.object(rsi, "V0_BUNDLE", seed),
            mock.patch.object(rsi, "main", side_effect=initialize),
        ):
            camp = fixtures.stream_campaign(directory.name, batch=1)
        return rsi.Host(camp, adapter=Tasks(quality), runner=RUNNER)

    def reopen(self, host):
        return rsi.Host(host.camp, adapter=host.adapter, runner=RUNNER)

    def first(self, **options):
        host = self.make_host(**options)
        original = host.incumbent()
        host.stream_step()
        candidate = host.stream_policy()
        self.assertNotEqual(candidate, original)
        self.assertEqual(host.twin(candidate), original)
        return host, original, candidate

    def sealed(self, host, candidate):
        return next(
            event["body"]
            for event in host.events("selection")
            if event["body"]["role"] == "method_descendants"
            and event["body"]["confirmation"] == candidate
        )

    def receipts(self, host):
        return [
            (path, json.loads(path.read_text())) for path in host.camp.rglob("run.json")
        ]

    def test_method_adoption_changes_research_producer_not_serving_descendant(self):
        host, original, candidate = self.first()
        host.stream_step()
        arms = self.sealed(host, candidate)["arms"]
        self.assertEqual(
            (host.batches()[1]["phase"], host.batches()[1]["version"]),
            ("method_probe", original),
        )
        self.assertEqual(
            (host.incumbent(), host.contract(f"adoption.{candidate[:16]}")["standing"]),
            (candidate, "discharged"),
        )
        self.assertEqual(arms["control"]["descendant"], original)
        descendant = arms["candidate"]["descendant"]
        self.assertNotIn(descendant, (candidate, original))
        host = self.reopen(host)
        host.stream_step()
        next_method = host.stream_policy()
        self.assertEqual(
            (
                host.batches()[2]["phase"],
                host.batches()[2]["version"],
                host.twin(next_method),
            ),
            ("serve", candidate, original),
        )
        research = json.loads(
            (host.camp / "research" / "step-3" / "run" / "run.json").read_text()
        )
        self.assertEqual((research["method_stage"], research["produced_stage"]), (1, 2))
        report = research["method_feedback"][0]
        self.assertEqual(
            (
                report["method"],
                report["comparator"],
                report["descendants"],
                report["passed"],
            ),
            (
                candidate,
                original,
                {arm: data["descendant"] for arm, data in arms.items()},
                True,
            ),
        )
        for unspent in set(host.terms["pools"]["confirm"]) - set(
            host.used_confirmation_tasks()
        ):
            self.assertNotIn(unspent, json.dumps(report))
        self.assertEqual(
            host.versions()[next_method]["lineage"],
            {"parent": candidate, "proposed_by": candidate},
        )

        def task_files(version):
            return {
                name: (host.version_dir(version) / "bundle" / name).read_bytes()
                for name in rsi.TASK_FILES
            }

        self.assertEqual(task_files(candidate), task_files(original))
        self.assertNotIn(descendant, [batch["version"] for batch in host.batches()])

    def test_paired_arms_share_fresh_input_and_never_see_other_arm_or_holdouts(self):
        host, original, candidate = self.first()
        host.stream_step()
        plan = succession.confirmation_plan(host, candidate)
        trial = [
            (path, receipt)
            for path, receipt in self.receipts(host)
            if receipt.get("method_trial")
        ]
        self.assertEqual(len(trial), 6)
        analysts = [
            receipt for _, receipt in trial if receipt["instructions"] == "analyst.md"
        ]
        self.assertEqual(
            [
                receipt["method_stage"]
                for receipt in sorted(analysts, key=lambda row: row["method_stage"])
            ],
            [0, 1],
        )
        self.assertEqual(
            analysts[0]["input_knowledge_sha256"], analysts[1]["input_knowledge_sha256"]
        )
        self.assertEqual(analysts[0]["trial_context"], analysts[1]["trial_context"])
        researchers = [
            receipt for _, receipt in trial if receipt["instructions"] == "research.md"
        ]
        self.assertEqual(
            len({receipt["target_policy_sha256"] for receipt in researchers}), 1
        )
        self.assertEqual(
            [receipt["target_method_stage"] for receipt in researchers], [0, 0]
        )
        for _, receipt in trial:
            source = Path(receipt["source_workspace"])
            text = "\n".join(
                path.read_text() for path in source.rglob("*") if path.is_file()
            )
            for forbidden in [candidate, *plan["tasks"], host.batches()[0]["tasks"][0]]:
                self.assertNotIn(forbidden, text)
            self.assertEqual(
                receipt["trial_context"]["tasks"], host.batches()[1]["tasks"]
            )
            self.assertEqual(receipt["trial_context"]["target"], original)
        for arm in self.sealed(host, candidate)["arms"].values():
            self.assertEqual(arm["input_subject"], plan["input"]["subject"])

    def test_no_scoring_before_both_outputs_then_resume_without_rerunning_updates(self):
        host, _, candidate = self.first()
        record = host.record

        def interrupted(kind, body, epoch=None):
            if kind == "selection" and body["role"] == "method_descendants":
                raise InterruptedError(
                    "both updater outputs complete; scoring not authorized yet"
                )
            return record(kind, body, epoch)

        with mock.patch.object(host, "record", side_effect=interrupted):
            with self.assertRaises(InterruptedError):
                host.stream_step()
        self.assertEqual(host.adapter.heldout, [])
        before = {
            str(path): path.read_bytes()
            for path, receipt in self.receipts(host)
            if receipt.get("method_trial")
        }
        self.assertEqual(len(before), 6)
        host = self.reopen(host)
        host.stream_step()
        self.assertEqual(
            {
                str(path): path.read_bytes()
                for path, receipt in self.receipts(host)
                if receipt.get("method_trial")
            },
            before,
        )
        self.assertEqual((host.incumbent(), len(host.adapter.heldout)), (candidate, 4))

    def test_explicit_adoption_waits_without_extra_work_then_method_research_continues(
        self,
    ):
        host, original, candidate = self.first(adoption="explicit")
        host.stream_step()
        before = (
            host.batches(),
            list(host.adapter.runs),
            {str(path): path.read_bytes() for path, _ in self.receipts(host)},
        )
        host = self.reopen(host)
        for _ in range(2):
            host.stream_step()
        self.assertEqual(
            (
                host.batches(),
                host.adapter.runs,
                {str(path): path.read_bytes() for path, _ in self.receipts(host)},
            ),
            before,
        )
        self.assertEqual(host.incumbent(), original)
        self.assertFalse(host.learned(2))
        host.adopt(candidate)
        for _ in range(2):
            if len(host.batches()) == 3:
                break
            host.stream_step()
        self.assertEqual(host.batches()[2]["version"], candidate)
        self.assertEqual(
            json.loads(
                (host.camp / "research" / "step-3" / "run" / "run.json").read_text()
            )["produced_stage"],
            2,
        )

    def test_tied_or_invalid_downstream_scores_never_adopt_or_buy_another_attempt(self):
        for quality in ("tie", "invalid"):
            with self.subTest(quality=quality):
                host, original, candidate = self.first(quality=quality)
                if quality == "invalid":
                    host.adapter.invalid_once.add(host.terms["pools"]["confirm"][0])
                    with self.assertRaisesRegex(RuntimeError, "invalid downstream"):
                        host.stream_step()
                else:
                    host.stream_step()
                self.assertEqual(host.incumbent(), original)
                expected = "outstanding" if quality == "invalid" else "released"
                self.assertEqual(
                    host.contract(f"adoption.{candidate[:16]}")["standing"], expected
                )
                before = (
                    list(host.adapter.runs),
                    {str(path): path.read_bytes() for path, _ in self.receipts(host)},
                )
                if quality == "invalid":
                    host = self.reopen(host)
                    for _ in range(2):
                        with self.assertRaisesRegex(RuntimeError, "invalid downstream"):
                            host.stream_step()
                    self.assertEqual(
                        (
                            host.adapter.runs,
                            {
                                str(path): path.read_bytes()
                                for path, _ in self.receipts(host)
                            },
                        ),
                        before,
                    )
                self.assertEqual(
                    len(host.adapter.heldout), len(set(host.adapter.heldout))
                )

    def test_ordinary_confirmation_cannot_reuse_a_method_trial_plan(self):
        host, original, candidate = self.first(adoption="explicit")
        host.stream_step()
        before = (store.events(host.store), list(host.adapter.runs))
        with self.assertRaisesRegex(RuntimeError, "method|updater|ordinary"):
            host.confirm(candidate, original)
        self.assertEqual((store.events(host.store), host.adapter.runs), before)

    def test_preexisting_observation_cannot_be_relabelled_as_a_fresh_method_episode(
        self,
    ):
        host, original, _ = self.first()
        host.measure(original, host.order()[1], "stream")
        before = (host.batches(), list(host.adapter.runs))
        with self.assertRaisesRegex(RuntimeError, "fresh|observ|already"):
            host.stream_step()
        self.assertEqual((host.batches(), host.adapter.runs), before)


if __name__ == "__main__":
    unittest.main()
