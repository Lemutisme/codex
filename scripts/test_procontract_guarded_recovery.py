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


if __name__ == "__main__":
    unittest.main()
