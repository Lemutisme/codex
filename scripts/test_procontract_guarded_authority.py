"""Real Host/store boundaries reject task-score authority over changed methods.

Manually registered versions and synthetic legacy certificates exercise entry points
outside proposal qualification. No model or benchmark process is launched.
"""

import json
import shutil
import unittest

import procontract_harness_program as harness
import procontract_store as store
import procontract_succession as succession
import test_procontract_guarded_stream as fixtures


class GuardedAuthorityTest(unittest.TestCase):
    make_host = fixtures.GuardedStreamTest.make_host
    reopen = fixtures.GuardedStreamTest.reopen

    def candidate(self, host, method, execution):
        incumbent = host.incumbent()
        source = host.camp.parent / "direct-candidate"
        shutil.copytree(host.version_dir(incumbent) / "bundle", source)
        path = source / method
        path.write_text(path.read_text() + "\nA changed research method.\n")
        if execution == "policy":
            path = source / "executor.md"
            path.write_text(path.read_text() + "\nbetter\n")
        elif execution == "harness":
            (source / harness.PROGRAM_FILE).write_text(
                json.dumps({"schema": 1, "when": {"remaining_fraction_lte": [1, 10]}})
            )
        return host.register(source, incumbent, incumbent, "direct entry fixture")

    def snapshot(self, host, candidate):
        return {
            "events": store.events(host.store),
            "assignments": host.events("assignment"),
            "exposures": host.events("exposure"),
            "runs": list(host.adapter.runs),
            "spent": host.used_confirmation_tasks(),
            "incumbent": host.incumbent(),
            "adoption": host.contract(f"adoption.{candidate[:16]}"),
        }

    def ordinary_plan(self, host, candidate, *, support=True):
        """Model an old ordinary plan without claiming genuine task evidence."""
        incumbent = host.incumbent()
        gate = {
            key: host.terms["gates"][key]
            for key in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
        }
        tasks = host.terms["pools"]["confirm"][: gate["confirm_tasks"]]
        sequence = succession.incumbent_record(host)["seq"]
        host.record(
            "assignment",
            {
                "confirmation": candidate,
                "incumbent": incumbent,
                "incumbent_seq": sequence,
                "tasks": tasks,
                "gate": gate,
            },
        )
        adoption = f"adoption.{candidate[:16]}"
        host.issue(
            adoption,
            {
                "campaign": host.campaign_hash(),
                "candidate": candidate,
                "expected_incumbent": incumbent,
                "incumbent_seq": sequence,
                "gate": gate,
            },
            {
                "class": "paired_confirmation",
                "tasks": store.digest("pool", tasks),
                "gate": gate,
            },
            "delegate",
        )
        host.propose(adoption, candidate)
        if support:
            host.support(
                adoption,
                {"synthetic_legacy_certificate": True},
                {"tasks": tasks, "evaluator": host.adapter.evaluator()},
                "beyond",
            )

    def test_direct_confirmation_cannot_certify_any_changed_method(self):
        for method in ("analyst.md", "challenger.md", "research.md"):
            for execution in ("none", "policy", "harness"):
                with self.subTest(method=method, execution=execution):
                    host = self.make_host()
                    candidate = self.candidate(host, method, execution)
                    before = self.snapshot(host, candidate)
                    host = self.reopen(host)
                    with self.assertRaisesRegex(RuntimeError, "changed method"):
                        host.confirm(candidate, host.incumbent())
                    self.assertEqual(self.snapshot(host, candidate), before)

    def test_legacy_mixed_proposal_cannot_start_or_resume_an_ordinary_probe(self):
        for phase in ("selected", "assigned"):
            with self.subTest(phase=phase):
                host = self.make_host()
                incumbent = host.incumbent()
                candidate = self.candidate(host, "research.md", "harness")
                batch = {
                    "batch": 1,
                    "phase": "serve",
                    "version": incumbent,
                    "expected_incumbent": incumbent,
                    "expected_incumbent_seq": succession.incumbent_record(host)["seq"],
                    "tasks": [host.order()[0]],
                }
                # Reconstruct persisted pre-guard routing, not newly qualified evidence.
                host.record("assignment", batch)
                host.record(
                    "selection",
                    {"role": "stream_policy", "version": candidate, "batch": 2},
                )
                host.record(
                    "selection",
                    {
                        **batch,
                        "role": "guarded_batch_result",
                        "candidate": candidate,
                        "outcome": "served",
                        "detail": "synthetic legacy selection",
                    },
                )
                if phase == "assigned":
                    host.record(
                        "assignment",
                        {
                            **batch,
                            "batch": 2,
                            "phase": "probe",
                            "version": candidate,
                            "tasks": [host.order()[1]],
                        },
                    )
                before = self.snapshot(host, candidate)
                host = self.reopen(host)
                with self.assertRaisesRegex(RuntimeError, "changed method"):
                    host.stream_step()
                self.assertEqual(self.snapshot(host, candidate), before)

    def test_supported_ordinary_plan_cannot_bypass_confirmation_or_adoption_guard(self):
        for execution in ("none", "policy", "harness"):
            with self.subTest(execution=execution):
                host = self.make_host()
                candidate = self.candidate(host, "research.md", execution)
                self.ordinary_plan(host, candidate)
                before = self.snapshot(host, candidate)
                host = self.reopen(host)
                # The supplied comparator cannot replace the plan's frozen incumbent.
                with self.assertRaisesRegex(RuntimeError, "changed method"):
                    host.confirm(candidate, candidate)
                self.assertEqual(self.snapshot(host, candidate), before)
                with self.assertRaisesRegex(RuntimeError, "changed method"):
                    host.adopt(candidate)
                self.assertEqual(self.snapshot(host, candidate), before)

    def test_unscored_resumed_plan_cannot_buy_confirmation(self):
        host = self.make_host()
        candidate = self.candidate(host, "challenger.md", "policy")
        self.ordinary_plan(host, candidate, support=False)
        before = self.snapshot(host, candidate)
        host = self.reopen(host)
        with self.assertRaisesRegex(RuntimeError, "changed method"):
            host.confirm(candidate, candidate)
        self.assertEqual(self.snapshot(host, candidate), before)

    def test_inherited_method_change_is_compared_to_incumbent_not_lineage_parent(self):
        host = self.make_host()
        ancestor = self.candidate(host, "analyst.md", "none")
        source = host.camp.parent / "inherited-candidate"
        shutil.copytree(host.version_dir(ancestor) / "bundle", source)
        executor = source / "executor.md"
        executor.write_text(executor.read_text() + "\nbetter\n")
        candidate = host.register(
            source, ancestor, ancestor, "inherited method fixture"
        )
        self.ordinary_plan(host, candidate)
        before = self.snapshot(host, candidate)
        host = self.reopen(host)
        with self.assertRaisesRegex(RuntimeError, "changed method"):
            host.confirm(candidate, ancestor)
        self.assertEqual(self.snapshot(host, candidate), before)
        with self.assertRaisesRegex(RuntimeError, "changed method"):
            host.adopt(candidate)
        self.assertEqual(self.snapshot(host, candidate), before)

    def test_released_confirmation_remains_terminal_without_reading_deleted_artifacts(
        self,
    ):
        host = self.make_host()
        candidate = self.candidate(host, "research.md", "harness")
        self.ordinary_plan(host, candidate)
        host.release(f"adoption.{candidate[:16]}", "historical refusal")
        shutil.rmtree(host.version_dir(candidate) / "bundle")
        before = self.snapshot(host, candidate)
        host = self.reopen(host)
        self.assertEqual(
            host.confirm(candidate, host.incumbent()),
            "confirmation failed; its sources remain spent",
        )
        self.assertEqual(self.snapshot(host, candidate), before)

    def test_discharged_decisions_remain_readable_without_artifacts(self):
        host = self.make_host(adoption="explicit")
        host.stream_step()
        candidate = host.stream_policy()
        host.stream_step()
        host.adopt(candidate)
        shutil.rmtree(host.version_dir(candidate) / "bundle")
        before = self.snapshot(host, candidate)
        host = self.reopen(host)
        self.assertEqual(host.confirm(candidate, candidate), "confirmed and adopted")
        self.assertEqual(host.adopt(candidate), f"{candidate[:12]} was already adopted")
        self.assertEqual(self.snapshot(host, candidate), before)


if __name__ == "__main__":
    unittest.main()
