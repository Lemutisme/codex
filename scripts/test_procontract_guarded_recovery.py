"""Crash boundaries and fail-closed guarded phases, using real Host/store transactions."""

import hashlib
import json
import shutil
import unittest
from unittest import mock

import procontract_harness_program as harness
import procontract_rsi as rsi
import procontract_store as store
import test_procontract_guarded_stream as fixtures


def paid_runs(transport):
    return [
        tuple(call.args[0])
        for call in transport.call_args_list
        if call.args[0][: len(fixtures.RUNNER)] == fixtures.RUNNER
        and call.args[0][len(fixtures.RUNNER)] == "run"
    ]


class GuardedRecoveryTest(unittest.TestCase):
    make_host = fixtures.GuardedStreamTest.make_host
    reopen = fixtures.GuardedStreamTest.reopen
    assert_activation = fixtures.GuardedStreamTest.assert_activation
    assert_adopted_producer = fixtures.GuardedStreamTest.assert_adopted_producer

    def proposal(self, host):
        root = host.incumbent()
        source = host.camp.parent / "proposal"
        shutil.copytree(host.version_dir(root) / "bundle", source)
        method = source / "analyst.md"
        method.write_text(method.read_text() + "\nRegistration recovery fixture.\n")
        (source / harness.PROGRAM_FILE).write_text(
            json.dumps(
                {
                    "schema": 1,
                    "when": {"remaining_fraction_lte": [1, 10]},
                }
            )
        )
        return root, source

    def publish_without_record(self, host, source, parent):
        record = host.record

        def interrupted(kind, body, epoch=None):
            if kind == "version":
                raise InterruptedError("after source publication, before ledger append")
            return record(kind, body, epoch)

        with mock.patch.object(host, "record", side_effect=interrupted):
            with self.assertRaises(InterruptedError):
                host.register(source, parent, parent, "frozen experiment")
        published = [
            path
            for path in (host.camp / "versions").iterdir()
            if not path.name.startswith(".") and path.name not in host.versions()
        ]
        self.assertEqual(len(published), 1)
        return published[0]

    def test_published_version_reconciles_one_ledger_event_without_rewriting_source(
        self,
    ):
        host = self.make_host()
        parent, source = self.proposal(host)
        target = self.publish_without_record(host, source, parent)
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(target.name, store.digest("version", manifest))
        before = {
            str(p.relative_to(target)): p.read_bytes()
            for p in target.rglob("*")
            if p.is_file()
        }
        host = self.reopen(host)
        candidate = host.register(source, parent, parent, "frozen experiment")
        self.assertEqual(candidate, target.name)
        self.assertEqual(
            host.register(source, parent, parent, "another retry"), candidate
        )
        self.assertEqual(
            [e["body"] for e in host.events("version") if e["body"]["id"] == candidate],
            [
                {
                    "id": candidate,
                    "manifest": manifest,
                    "experiment_sha256": hashlib.sha256(
                        before["EXPERIMENT.md"]
                    ).hexdigest(),
                }
            ],
        )
        self.assertEqual(
            {
                str(p.relative_to(target)): p.read_bytes()
                for p in target.rglob("*")
                if p.is_file()
            },
            before,
        )

    def test_registered_artifact_accepts_a_new_explanation_without_rewriting_history(
        self,
    ):
        host = self.make_host()
        parent, source = self.proposal(host)
        candidate = host.register(source, parent, parent, "First frozen explanation.\n")
        target = host.version_dir(candidate)
        before = (
            {
                str(p.relative_to(target)): p.read_bytes()
                for p in target.rglob("*")
                if p.is_file()
            },
            store.events(host.store),
        )
        host = self.reopen(host)
        self.assertEqual(
            host.register(
                source,
                parent,
                parent,
                "A different explanation for the same artifact.\n",
            ),
            candidate,
        )
        self.assertEqual(
            (
                {
                    str(p.relative_to(target)): p.read_bytes()
                    for p in target.rglob("*")
                    if p.is_file()
                },
                store.events(host.store),
            ),
            before,
        )

    def test_registered_experiment_file_drift_cannot_be_laundered_by_new_explanation(
        self,
    ):
        host = self.make_host()
        parent, source = self.proposal(host)
        candidate = host.register(source, parent, parent, "First frozen explanation.\n")
        ledger = store.events(host.store)
        path = host.version_dir(candidate) / "EXPERIMENT.md"
        tampered = "An unauthorized replacement explanation.\n"
        path.write_text(tampered)
        with self.assertRaisesRegex(RuntimeError, "incomplete or differs"):
            self.reopen(host).register(source, parent, parent, tampered)
        self.assertEqual(
            (path.read_text(), store.events(host.store)), (tampered, ledger)
        )

    def test_partial_or_drifted_published_versions_are_never_overwritten(self):
        for filename in (
            "manifest.json",
            "bundle/analyst.md",
            f"bundle/{harness.PROGRAM_FILE}",
            "bundle/reviewer.md",
        ):
            with self.subTest(filename=filename):
                host = self.make_host()
                parent, source = self.proposal(host)
                target = self.publish_without_record(host, source, parent)
                path = target / filename
                if filename == "bundle/reviewer.md":
                    path.unlink()
                else:
                    path.write_text("{}")
                before = {
                    str(p.relative_to(target)): p.read_bytes()
                    for p in target.rglob("*")
                    if p.is_file()
                }
                ledger = store.events(host.store)
                with self.assertRaisesRegex(RuntimeError, "incomplete or differs"):
                    self.reopen(host).register(
                        source, parent, parent, "frozen experiment"
                    )
                self.assertEqual(store.events(host.store), ledger)
                self.assertEqual(
                    {
                        str(p.relative_to(target)): p.read_bytes()
                        for p in target.rglob("*")
                        if p.is_file()
                    },
                    before,
                )

    def test_discharge_before_candidate_selection_reuses_the_completed_research(self):
        host = self.make_host()
        record = host.record

        def interrupted(kind, body, epoch=None):
            if kind == "selection" and body["role"] == "stream_policy":
                raise InterruptedError(
                    "improvement settled before exploration selection"
                )
            return record(kind, body, epoch)

        with mock.patch.object(
            rsi.subprocess, "run", wraps=rsi.subprocess.run
        ) as transport:
            with mock.patch.object(host, "record", side_effect=interrupted):
                with self.assertRaises(InterruptedError):
                    host.stream_step()
            self.assertEqual(host.contract("improvement.1")["standing"], "discharged")
            self.assertFalse(host.learned(1))
            candidates = [v for v in host.versions() if v != host.incumbent()]
            self.assertEqual(len(candidates), 1)
            before = (paid_runs(transport), list(host.adapter.runs))
            host = self.reopen(host)
            host.stream_step()
            self.assertEqual((paid_runs(transport), host.adapter.runs), before)
            self.assertEqual(
                (host.stream_policy(), len(host.batches()), host.learned(1)),
                (candidates[0], 1, True),
            )
        host.stream_step()
        self.assertEqual(
            (host.batches()[1]["phase"], host.batches()[1]["version"]),
            ("probe", candidates[0]),
        )

    def test_atomic_adoption_before_phase_receipt_never_repeats_confirmation(self):
        host = self.make_host()
        host.stream_step()
        candidate = host.stream_policy()
        record = host.record

        def interrupted(kind, body, epoch=None):
            if (
                kind == "selection"
                and body["role"] == "guarded_batch_result"
                and body["phase"] == "probe"
                and body["outcome"] == "adopted"
            ):
                raise InterruptedError(
                    "atomic adoption committed before guarded phase receipt"
                )
            return record(kind, body, epoch)

        with mock.patch.object(
            rsi.subprocess, "run", wraps=rsi.subprocess.run
        ) as transport:
            with mock.patch.object(host, "record", side_effect=interrupted):
                with self.assertRaises(InterruptedError):
                    host.stream_step()
            self.assertEqual(host.incumbent(), candidate)
            self.assertFalse(host.learned(2))
            before = (
                paid_runs(transport),
                list(host.adapter.runs),
                host.used_confirmation_tasks(),
                host.insights(),
            )
            host = self.reopen(host)
            host.stream_step()
            self.assertEqual(
                (
                    paid_runs(transport),
                    host.adapter.runs,
                    host.used_confirmation_tasks(),
                    host.insights(),
                ),
                before,
            )
            self.assertEqual((len(host.batches()), host.learned(2)), (2, True))
        host.stream_step()
        self.assert_adopted_producer(host, candidate)

    def test_method_only_candidate_is_deferred_without_direct_task_confirmation(self):
        host = self.make_host()
        root = host.incumbent()
        research = host.research

        def method_only(parent, step):
            delivery = research(parent, step)
            # Controlled transport fixture: keep the method edits, omit the harness edit.
            shutil.copyfile(
                host.version_dir(parent) / "bundle" / harness.PROGRAM_FILE,
                delivery / "policy" / harness.PROGRAM_FILE,
            )
            return delivery

        with mock.patch.object(host, "research", side_effect=method_only):
            message = host.stream_step()
        candidate = host.stream_policy()
        self.assertNotEqual(candidate, root)
        self.assertEqual(host.twin(candidate), root)
        self.assertIn("method-only candidate deferred", message)
        deferred = [
            e["body"]
            for e in host.events("selection")
            if e["body"]["role"] == "guarded_method_deferred"
        ]
        self.assertEqual([e["candidate"] for e in deferred], [candidate])
        host = self.reopen(host)
        host.stream_step()
        self.assertEqual(
            [(b["phase"], b["version"]) for b in host.batches()],
            [("serve", root), ("serve", root)],
        )
        self.assertEqual(host.used_confirmation_tasks(), [])
        self.assertIsNone(host.contract(f"adoption.{candidate[:16]}"))

    def test_invalid_execution_or_evaluation_stays_assigned_without_another_attempt(
        self,
    ):
        for phase in ("serve", "probe", "confirm"):
            with self.subTest(phase=phase):
                host = self.make_host()
                root = host.incumbent()
                if phase != "serve":
                    host.stream_step()
                original = host.adapter.run_and_label

                def invalid(h, bundle, task, run_dir):
                    result = original(h, bundle, task, run_dir)
                    if phase != "confirm" or task in h.terms["pools"]["confirm"]:
                        result = {
                            **result,
                            "validity": "invalid",
                            "pass_rate": None,
                            "reason": "fixture evaluator unavailable",
                        }
                        result.pop("label", None)
                    return result

                with mock.patch.object(
                    host.adapter, "run_and_label", side_effect=invalid
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "invalid execution/evaluation"
                    ):
                        host.stream_step()
                    before = (
                        host.batches(),
                        list(host.adapter.runs),
                        host.used_confirmation_tasks(),
                        host.insights(),
                    )
                    host = self.reopen(host)
                    for _ in range(2):
                        with self.assertRaisesRegex(
                            RuntimeError, "invalid execution/evaluation"
                        ):
                            host.stream_step()
                    self.assertEqual(
                        (
                            host.batches(),
                            host.adapter.runs,
                            host.used_confirmation_tasks(),
                            host.insights(),
                        ),
                        before,
                    )
                self.assertEqual(host.incumbent(), root)
                self.assertFalse(host.learned(len(host.batches())))

    def test_failed_probe_analysis_is_reused_after_readiness_receipt_crash(self):
        host = self.make_host()
        root = host.incumbent()
        host.stream_step()
        run_agent, record = host.run_agent, host.record

        def incomplete_challenge(*args):
            delivery = run_agent(*args)
            if args[3] == "challenger.md":
                (delivery / "CHALLENGE.md").unlink(missing_ok=True)
            return delivery

        def interrupted(kind, body, epoch=None):
            if kind == "selection" and body["role"] == "guarded_probe_ready":
                raise InterruptedError(
                    "failed analysis recorded before phase readiness"
                )
            return record(kind, body, epoch)

        with mock.patch.object(
            rsi.subprocess, "run", wraps=rsi.subprocess.run
        ) as transport:
            with (
                mock.patch.object(host, "run_agent", side_effect=incomplete_challenge),
                mock.patch.object(host, "record", side_effect=interrupted),
            ):
                with self.assertRaises(InterruptedError):
                    host.stream_step()
            self.assertEqual(host.insights()[-1]["status"], "failed")
            before = (paid_runs(transport), list(host.adapter.runs), host.insights())
            host = self.reopen(host)
            with mock.patch.object(
                host,
                "run_agent",
                side_effect=AssertionError("failed analysis must not rerun"),
            ):
                host.stream_step()
            self.assertEqual(
                (paid_runs(transport), host.adapter.runs, host.insights()), before
            )
        self.assertEqual((host.incumbent(), host.used_confirmation_tasks()), (root, []))
        self.assertTrue(host.learned(2))
        self.assertFalse((host.camp / "research" / "step-2").exists())
        host.stream_step()
        self.assertEqual(
            (host.batches()[2]["phase"], host.batches()[2]["version"]), ("serve", root)
        )


if __name__ == "__main__":
    unittest.main()
