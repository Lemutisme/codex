"""Real Host/kernel, canonical receipts and paid SQLite; synthetic native transport.

The future profile remains disabled for paid use: only its seal/readiness adapter is
stubbed here. No model/container execution or empirical RSI benefit is claimed.
"""

import contextlib
import copy
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_canonical as canonical
import procontract_compliance_gate as compliance
import procontract_fixed_auditor_role as auditor_role
import procontract_delivery_budget as delivery
import procontract_h_admission as admission
import procontract_harness_program as harness
import procontract_native_trace_binding as trace_binding
import procontract_ph_protocol as protocol
import procontract_rsi as rsi
import procontract_store as store
import procontract_study as study
import procontract_study_budget as budget
import procontract_study_launch as study_launch
import procontract_succession as succession
import test_procontract_canonical_host as fixtures
import test_procontract_study_launch as launch_fixtures
from testing import native_notice_fixture as trace_fixture


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class AdmissionTest(unittest.TestCase):
    args = fixtures.CanonicalHostTest.args
    make_host = fixtures.CanonicalHostTest.make_host
    cached = fixtures.CanonicalHostTest.cached
    balance = launch_fixtures.StudyLaunchTest.balance
    preparation = launch_fixtures.StudyLaunchTest.preparation
    transport = launch_fixtures.StudyLaunchTest.transport
    program_document = {"schema": 2, "action": "checkpoint", "when": {"always": True}}
    root_program_document = None

    def setUp(self):
        fixtures.CanonicalHostTest.setUp(self)
        source = self.host.version_dir(self.parent) / "bundle"
        if self.root_program_document is not None:
            source = shutil.copytree(source, self.root / "initial-bundle")
            write(source / "harness.json", self.root_program_document)
        terms = copy.deepcopy(self.host.terms)
        tasks = [f"fixture__t{i}.000000{i}" for i in range(8)]
        self.task = tasks[1]
        self.data["tasks"] = {
            t: {"total": 3, "image": "sha256:" + "3" * 64} for t in tasks
        }
        write(self.registry_path, self.data)
        self.registry_sha = canonical.sha256(self.registry_path)
        write(
            self.pins_path,
            {"registry_sha256": self.registry_sha, "adapter_sha256": self.adapter_sha},
        )
        self.descriptor.update(
            registry_sha256=self.registry_sha,
            pins_sha256=canonical.sha256(self.pins_path),
        )
        canonical._REGISTRY = canonical._EXPECTED_PINS = None
        self.limits = {
            "task_launches": 12,
            "learning_launches": 21,
            "allocated_seconds": 291600,
        }
        camp = self.root / "h-campaign"
        terms.update(
            canonical=self.descriptor,
            native_notice_trace=dict(trace_binding.PROFILE),
            fixed_auditor=auditor_role.descriptor(
                {
                    "base_url": "http://127.0.0.1/v1",
                    "env_key": "TEST_AUDITOR_KEY",
                }
            ),
            study={
                "manifest_path": str(camp / "study.json"),
                "manifest_sha256": "a" * 64,
            },
            mutable=["harness.json"],
            proposal_kind="harness",
            adoption="presumed",
            task_deadline_secs=18000,
            stream={"mode": "guarded", "order": tasks[:4], "batch": 1},
            pools={"dev": tasks[:4], "confirm": tasks[4:]},
            gates={
                "confirm_tasks": 4,
                "confirm_min_wins": 3,
                "confirm_min_delta": 0.000001,
            },
        )
        terms["budgets"]["task_attempts"] = 1
        write(camp / "campaign.json", terms)
        self.enterContext(
            mock.patch.object(study, "verify", return_value={"limits": self.limits})
        )
        # Focused native-delivery tests do not execute the independent compliance gate.
        for name in ("authorize_confirmation", "authorize_learning", "confirmation"):
            self.enterContext(mock.patch.object(compliance, name))
        self.enterContext(
            mock.patch.object(
                trace_binding, "storage", return_value=trace_fixture.STORAGE
            )
        )
        self.enterContext(
            mock.patch.object(
                trace_binding, "provision", side_effect=trace_fixture.provision
            )
        )
        self.enterContext(
            mock.patch.object(
                protocol,
                "campaign_profile",
                return_value=protocol.profile(protocol.H_PROTOCOL),
            )
        )
        self.host = rsi.Host(camp)
        self.host.issue("campaign", terms, {"class": "campaign_report"}, "human")
        self.parent = self.host.register(source, None, "operator", "fixture root")
        adoption = f"adoption.{self.parent[:16]}"
        self.host.issue(
            adoption,
            {
                "campaign": self.host.campaign_hash(),
                "candidate": self.parent,
                "bootstrap": True,
            },
            {"class": "bootstrap"},
            "human",
        )
        self.host.propose(adoption, self.parent)
        self.host.support(adoption, {"bootstrap": True}, {"operator": True}, "within")
        self.host.adopt(self.parent)
        self.enterContext(mock.patch.object(admission, "enabled", return_value=True))
        bundle = self.root / "h-candidate"
        shutil.copytree(source, bundle)
        write(bundle / "harness.json", self.program_document)
        self.candidate_id = self.host.register(
            bundle, self.parent, self.parent, "synthetic H"
        )
        self.producer = self.candidate_id
        self.database = self.host.camp / "study-budget.sqlite"
        (self.root / "codex-code-mode-host").write_text(
            "synthetic sidecar, never executed"
        )
        (self.root / "codex-code-mode-host").chmod(0o755)
        self.sequence = succession.incumbent_record(self.host)["seq"]
        for number, version in ((1, self.parent), (2, self.candidate_id)):
            self.host.record(
                "assignment",
                {
                    "batch": number,
                    "phase": "serve" if number == 1 else "probe",
                    "version": version,
                    "expected_incumbent": self.parent,
                    "expected_incumbent_seq": self.sequence,
                    "tasks": [tasks[number - 1]],
                },
            )
        self.host.record(
            "selection",
            {"role": "stream_policy", "version": self.candidate_id, "batch": 2},
        )
        self.trace_fixtures = {}
        budget.initialize(camp / "study-budget.sqlite", "a" * 64, self.limits)
        self.complete(self.parent, tasks[0], "stream", 1)
        self.run = self.complete(self.candidate_id, self.task, "stream", 2)
        for role in ("analyst.md", "challenger.md"):
            self.complete(self.parent, role, "learning", 0, role=role)
        observed = self.host.observed()
        self.host.record(
            "insight",
            {
                "k": 1,
                "status": "qualified",
                "verdict": "present",
                "experiment": self.candidate_id,
                "coverage": sorted(observed),
                "analysis_identity": {
                    "parent": self.parent,
                    "coverage": sorted(observed),
                    "experiment": self.candidate_id,
                    "evidence": store.digest("analysis_evidence", observed),
                },
            },
        )
        self.host.record(
            "selection",
            {
                "role": "stream_release_intent",
                "batch": 2,
                "version": self.candidate_id,
                "expected_incumbent": self.parent,
                "insight": 1,
            },
        )

    def complete(self, version, task, purpose, passed, *, role="executor.md"):
        executor = role == "executor.md"
        if executor:
            result = self.cached(version, task, purpose, passed)
            run = Path(result["run_dir"])
        else:
            run = self.host.camp / "insight" / "1" / f"{role[:-3]}-1" / "run"
            run.mkdir(parents=True)
        shutil.copytree(self.host.version_dir(version) / "bundle", run / "policy")
        shutil.copyfile(self.root / "prompt.txt", run / "prompt.txt")
        identity = self.host.versions()[version].get("harness")
        manifest = {
            k: self.host.terms[k]
            for k in ("model", "effort", "codex_bin", "codex_sha256")
        }
        manifest.update(
            study=self.host.terms["study"],
            study_version=version,
            instructions=role,
            instance=task,
            image=self.data["tasks"][task]["image"]
            if executor
            else self.host.terms["research_image"],
            prompt_sha256=protocol.digest(run / "prompt.txt"),
            harness_program=identity,
        )
        trace = trace_fixture.Trace(
            run,
            manifest,
            self.host.terms,
            outcome=self.trace_outcome(version, task, purpose),
        )
        self.trace_fixtures[str(run)] = trace
        write(run / "manifest.json", manifest)
        configuration = {}
        for name in (
            "codex-home/config.toml",
            "codex-home/environments.toml",
            "codex-home/pro_contract/settings.json",
        ):
            write(run / name, {})
            configuration[name] = protocol.digest(run / name)
        reservation = budget.reserve(
            self.host.camp / "study-budget.sqlite",
            "a" * 64,
            str(run.relative_to(self.host.camp)),
            "task" if executor else "learning",
            18000 if executor else self.host.terms["analysis_deadline_secs"],
            self.limits,
            {
                "version": version,
                "role": role,
                "instance": task,
                "manifest_sha256": protocol.digest(run / "manifest.json"),
                "configuration": configuration,
            },
        )
        write(run / "study-launch.json", reservation)
        if not executor:
            claim = {
                "identity": {
                    "parent": version,
                    "instructions": role,
                    "model": self.host.terms["model"],
                    "effort": self.host.terms["effort"],
                    "binary": self.host.terms["codex_sha256"],
                    "image": self.host.terms["research_image"],
                },
                "prepared_manifest": protocol.digest(run / "manifest.json"),
            }
            write(run.parent / "launch-claim.json", claim)
            write(
                run.parent / "launch-exit.json",
                {"claim": store.digest("learning_launch", claim), "returncode": 0},
            )
        program = harness.load(run / "policy")
        controller = delivery.DeliveryBudget(
            deadline_secs=18000,
            reserve_secs=3600 if program is not None else 0,
            program=program,
        )
        server = mock.Mock()
        server.request.side_effect = trace.request
        if program is not None:
            controller.maybe_steer(
                server,
                SimpleNamespace(
                    active=True, thread_id="thread", turn_id="turn", completed=0
                ),
                {"phase": "working", "repairs_used": 0},
                lambda message: None,
                elapsed_secs=400 if program.schema == 2 else 14900,
                executor_command_completions_observed=1,
            )
        summary = {
            "study_launch": reservation,
            "thread_id": "thread",
            "turn_statuses": ["completed"],
            "native_process_exit": {
                "status": "exited",
                "returncode": 0,
                "shutdown": "stdin_closed",
            },
            "harness_program": controller.activation,
            "delivery_budget": controller.summary(),
        }
        summary["native_notice_trace"] = trace.finish(
            controller.summary(), summary["native_process_exit"]
        )
        write(run / "run.json", summary)
        lines = [
            json.dumps(
                {
                    "method": "turn/started",
                    "params": {"threadId": "thread", "turn": {"id": "turn"}},
                }
            )
        ]
        if server.request.called:
            method, params, _ = server.request.call_args.args
            lines += [
                "> " + json.dumps({"id": 7, "method": method, "params": params}),
                json.dumps({"id": 7, "result": {"turnId": "turn"}}),
            ]
        with gzip.open(run / "app-server.jsonl.gz", "wb") as target:
            target.write(("\n".join(lines) + "\n").encode())
        return run

    def trace_outcome(self, version, task, purpose):
        return "observed"

    def unspent(self):
        return (
            [e for e in self.host.events("assignment") if "confirmation" in e["body"]],
            self.host.events("exposure"),
            budget.status(
                self.host.camp / "study-budget.sqlite", "a" * 64, self.limits
            )["reserved"]["task_launches"],
        )

    def assert_inconclusive(self, outcome):
        summary = protocol.document(self.run / "run.json")
        if outcome is None:
            summary["delivery_budget"]["attempt"] = None
            summary["harness_program"].update(
                evaluations=0,
                last_input=None,
                last_decision=None,
                last_eligibility=None,
            )
            with gzip.open(self.run / "app-server.jsonl.gz", "wb") as target:
                target.write(b"{}\n")
        else:
            summary["delivery_budget"]["attempt"]["outcome"] = outcome
        write(self.run / "run.json", summary)
        with mock.patch.object(self.host, "measure_all") as measure:
            self.assertIn(
                "inconclusive", self.host.confirm(self.candidate_id, self.parent)
            )
            measure.assert_not_called()
        self.assertEqual(self.unspent(), ([], [], 2))
        with self.assertRaises(admission.Inconclusive):
            admission.authorize_task(
                self.host,
                self.host.camp / "alias",
                {"instance": self.host.terms["pools"]["confirm"][0]},
            )
        self.assertEqual(self.unspent(), ([], [], 2))

    def test_no_action_stops_without_resampling(self):
        self.assert_inconclusive(None)

    def test_timeout_stays_inconclusive(self):
        self.assert_inconclusive("timeout")

    def test_rpc_error_stays_inconclusive(self):
        self.assert_inconclusive("error")

    def test_unacknowledged_stays_inconclusive(self):
        self.assert_inconclusive("unacknowledged")

    def measured(self, pairs, purpose):
        self.assertEqual(purpose, "confirm")
        self.assertEqual(len(pairs), 8)
        for version, task in pairs:
            admission.authorize_task(
                self.host,
                self.host.camp
                / "runs"
                / f"confirm-{version[:12]}-{task}"
                / "attempt-1",
                {"instance": task, "study_version": version},
            )
            self.complete(
                version, task, purpose, 2 if version == self.candidate_id else 1
            )
        return {
            (v, t): protocol.document(
                self.host.camp / "runs" / f"confirm-{v[:12]}-{t}" / "result.json"
            )
            for v, t in pairs
        }

    def test_accepted_probe_opens_exact_pairs_then_drift_blocks_first_adoption(self):
        entry = admission.check(self.host, self.candidate_id, self.parent, freeze=True)
        self.assertEqual(
            entry, admission.check(self.host, self.candidate_id, self.parent)
        )
        with (
            mock.patch.object(self.host, "measure_all", side_effect=self.measured),
            mock.patch.object(self.host, "adopt"),
        ):
            self.host.confirm(self.candidate_id, self.parent)
        (self.run / "run.json").write_bytes(
            (self.run / "run.json").read_bytes() + b"\n"
        )
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.host.adopt(self.candidate_id, presumed=True)
        self.assertEqual(self.host.incumbent(), self.parent)

    def test_forged_or_missing_receipts_never_reach_confirmation(self):
        summary = protocol.document(self.run / "run.json")
        cases = ("decision", "eligibility", "action", "turn", "exit", "paid")
        for case in cases:
            with self.subTest(case=case):
                broken = copy.deepcopy(summary)
                if case == "decision":
                    broken["harness_program"]["last_decision"] = False
                if case == "eligibility":
                    broken["harness_program"]["last_eligibility"]["eligible"] = False
                if case == "action":
                    broken["delivery_budget"]["attempt"]["action"] = "converge"
                if case == "turn":
                    broken["delivery_budget"]["attempt"]["turn_id"] = "other"
                if case == "exit":
                    broken["native_process_exit"]["status"] = "unknown"
                if case == "paid":
                    broken["study_launch"]["id"] = "b" * 32
                write(self.run / "run.json", broken)
                with (
                    mock.patch.object(self.host, "measure_all") as measure,
                    self.assertRaises((RuntimeError, ValueError)),
                ):
                    self.host.confirm(self.candidate_id, self.parent)
                measure.assert_not_called()
                self.assertEqual(self.unspent(), ([], [], 2))
        write(self.run / "run.json", summary)
        (self.run / "study-launch.json").unlink()
        with self.assertRaises(RuntimeError):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.unspent(), ([], [], 2))

    def test_first_adoption_still_requires_four_pairs_and_settled_replay_is_historical(
        self,
    ):
        with mock.patch.object(self.host, "measure_all", side_effect=self.measured):
            self.assertIn("adopted", self.host.confirm(self.candidate_id, self.parent))
        self.assertEqual(self.host.incumbent(), self.candidate_id)
        self.assertEqual(self.unspent()[2], 10)
        shutil.rmtree(self.run)
        self.assertIn("already adopted", self.host.adopt(self.candidate_id))
        self.assertEqual(
            self.host.confirm(self.candidate_id, self.parent), "confirmed and adopted"
        )

    def test_fixed_role_or_harness_source_drift_never_opens_confirmation(self):
        for name in [*rsi.BUNDLE_FILES, "harness.json"]:
            path = self.host.version_dir(self.candidate_id) / "bundle" / name
            original = path.read_bytes()
            path.write_bytes(original + b"\nCHANGED")
            try:
                with (
                    self.subTest(name=name),
                    self.assertRaises((ValueError, RuntimeError)),
                ):
                    self.host.confirm(self.candidate_id, self.parent)
                self.assertEqual(self.unspent(), ([], [], 2))
            finally:
                path.write_bytes(original)

    def test_analysis_receipt_or_qualified_signature_cannot_be_replayed(self):
        admission.check(self.host, self.candidate_id, self.parent, freeze=True)
        path = self.host.camp / "insight/1/challenger-1/launch-exit.json"
        original = path.read_bytes()
        write(path, {"claim": "0" * 64, "returncode": 0})
        with self.assertRaises(RuntimeError):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.unspent(), ([], [], 2))
        path.write_bytes(original)
        latest = {**self.host.insights()[-1], "k": 2, "verdict": "absent"}
        self.host.record("insight", latest)
        with self.assertRaisesRegex(RuntimeError, "present"):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.unspent(), ([], [], 2))

    def test_a_second_paid_probe_identity_cannot_unlock_confirmation(self):
        budget.reserve(
            self.host.camp / "study-budget.sqlite",
            "a" * 64,
            "runs/replayed/attempt-1",
            "task",
            18000,
            self.limits,
            {
                "version": self.candidate_id,
                "role": "executor.md",
                "instance": self.task,
                "manifest_sha256": protocol.digest(self.run / "manifest.json"),
                "configuration": {},
            },
        )
        with self.assertRaisesRegex(RuntimeError, "another paid attempt"):
            self.host.confirm(self.candidate_id, self.parent)
        self.assertEqual(self.unspent(), ([], [], 3))

    def test_frozen_action_drift_at_real_runner_boundary_cannot_reserve(self):
        with mock.patch.object(self.host, "measure_all", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                self.host.confirm(self.candidate_id, self.parent)
        task = self.host.terms["pools"]["confirm"][0]
        path = (
            self.host.camp
            / "runs"
            / f"confirm-{self.candidate_id[:12]}-{task}"
            / "attempt-1"
        )
        args = self.preparation(name="fenced-confirmation", run_dir=path)
        args.instance = task
        with self.transport() as opened:
            launch_fixtures.runner.prepare(args)
            before = self.balance()
            receipt = self.run / "run.json"
            receipt.write_bytes(receipt.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                launch_fixtures.runner.run(args)
        self.assertEqual((opened, self.balance()), ([], before))

    def test_pending_parallel_confirmation_does_not_reclassify_the_completed_probe(
        self,
    ):
        before = admission.check(self.host, self.candidate_id, self.parent, freeze=True)
        task = self.host.terms["pools"]["confirm"][0]
        # Another confirmation worker has reserved but not yet produced native receipts.
        budget.reserve(
            self.database,
            "a" * 64,
            "runs/pending-confirmation/attempt-1",
            "task",
            18000,
            self.limits,
            {"version": self.parent, "role": "executor.md", "instance": task},
        )
        self.assertEqual(
            admission.check(self.host, self.candidate_id, self.parent), before
        )

    def test_paid_identity_binds_the_exact_frozen_admission(self):
        with mock.patch.object(self.host, "measure_all", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                self.host.confirm(self.candidate_id, self.parent)
        task = self.host.terms["pools"]["confirm"][0]
        path = (
            self.host.camp
            / "runs"
            / f"confirm-{self.candidate_id[:12]}-{task}"
            / "attempt-1"
        )
        args = self.preparation(name="paid-identity", run_dir=path)
        args.instance = task
        with self.transport() as opened:
            launch_fixtures.runner.prepare(args)
            study_launch.authorize(
                args, protocol.document(path / "manifest.json"), launch_fixtures.runner
            )
        with contextlib.closing(sqlite3.connect(self.database)) as database:
            (encoded,) = database.execute(
                "SELECT identity_json FROM reservations WHERE key = ?",
                (str(path.relative_to(self.host.camp)),),
            ).fetchone()
        expected = admission.check(self.host, self.candidate_id, self.parent)["digest"]
        self.assertEqual((json.loads(encoded)["h_admission"], opened), (expected, []))


class LegacyActionTest(unittest.TestCase):
    args = fixtures.CanonicalHostTest.args
    make_host = fixtures.CanonicalHostTest.make_host
    cached = fixtures.CanonicalHostTest.cached
    setUp = AdmissionTest.setUp
    complete = AdmissionTest.complete
    trace_outcome = AdmissionTest.trace_outcome
    root_program_document = None
    program_document = {"schema": 1, "when": {"always": True}}

    def test_legal_v1_convergence_ack_is_not_misclassified_as_invalid(self):
        entry = admission.check(self.host, self.candidate_id, self.parent, freeze=True)
        self.assertEqual(
            (
                entry["evidence"]["harness"]["action"],
                entry["evidence"]["outcome"],
                entry["evidence"]["eligibility_basis"],
            ),
            ("converge", "accepted", "legacy_controller_late_window"),
        )


class LaunchBoundaryTest(unittest.TestCase):
    args = launch_fixtures.StudyLaunchTest.args
    make_host = launch_fixtures.StudyLaunchTest.make_host
    cached = launch_fixtures.StudyLaunchTest.cached
    initialize_study = launch_fixtures.StudyLaunchTest.initialize_study
    setUp = launch_fixtures.StudyLaunchTest.setUp
    balance = launch_fixtures.StudyLaunchTest.balance
    preparation = launch_fixtures.StudyLaunchTest.preparation
    transport = launch_fixtures.StudyLaunchTest.transport

    def test_alternate_confirmation_entry_cannot_reserve_or_open_native_transport(self):
        args = self.preparation(name="alternate-entry")
        args.instance = self.host.terms["pools"]["confirm"][0]
        with (
            self.transport() as opened,
            mock.patch.object(admission, "enabled", return_value=True),
            mock.patch.object(
                study_launch.budget, "reserve", wraps=budget.reserve
            ) as reserve,
        ):
            launch_fixtures.runner.prepare(args)
            before = self.balance()
            with self.assertRaisesRegex(RuntimeError, "predeclared H probe"):
                launch_fixtures.runner.run(args)
        reserve.assert_not_called()
        self.assertEqual((opened, self.balance()), ([], before))
        self.assertEqual(
            (
                [
                    e
                    for e in self.host.events("assignment")
                    if "confirmation" in e["body"]
                ],
                self.host.events("exposure"),
            ),
            ([], []),
        )


if __name__ == "__main__":
    unittest.main()
