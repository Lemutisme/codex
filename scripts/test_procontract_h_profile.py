"""Future profile DATA/audit coverage, never permission to start a paid H episode."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import procontract_fixed_auditor_role as auditor_role
import procontract_native_trace_binding as trace
import procontract_ph_audit as audit
import procontract_ph_protocol as protocol
import procontract_ph_supervisor as supervisor
import procontract_rsi as rsi
import procontract_study as study
from test_procontract_ph_supervisor import plan_terms, write


class HProfileTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.camp = Path(temporary.name) / "campaign"
        self.camp.mkdir()
        self.terms = plan_terms(self.camp)
        self.path = Path(self.terms["ph_supervisor"]["plan_path"])

    def h_terms(self):
        self.terms.update(
            submission_policy=protocol.BUILD_RUNTIME_POLICY,
            proposal_kind="harness",
            mutable=["harness.json"],
            fixed_auditor=auditor_role.descriptor(
                {"base_url": "http://127.0.0.1/v1", "env_key": "TEST_AUDITOR_KEY"}
            ),
            native_notice_trace=dict(trace.PROFILE),
        )
        plan = protocol.document(self.path)
        plan.update(
            protocol=protocol.H_PROTOCOL, required_admission=protocol.H_ADMISSION
        )
        self.publish_plan(plan)
        return plan

    def publish_plan(self, plan):
        write(self.path, plan)
        self.terms["ph_supervisor"]["plan_sha256"] = protocol.digest(self.path)

    def test_old_profile_remains_paid_validation_compatible_without_new_fields(self):
        original = copy.deepcopy(self.terms)
        self.assertEqual(
            protocol.validate_plan(self.camp, self.terms), protocol.document(self.path)
        )
        self.assertEqual(self.terms, original)
        selected = protocol.campaign_profile(self.camp, self.terms)
        self.assertEqual(
            (selected.mutable, selected.fixed_roles, selected.required_admission),
            (protocol.PH, protocol.METHOD_ROLES, None),
        )
        plan = protocol.document(self.path)
        plan["required_admission"] = protocol.H_ADMISSION
        self.publish_plan(plan)
        with self.assertRaisesRegex(RuntimeError, "episode/source"):
            protocol.validate_plan(self.camp, self.terms)

    def test_h_plan_is_inspectable_but_does_not_grant_paid_readiness(self):
        plan = self.h_terms()
        self.assertEqual(protocol.inspect_plan(self.camp, self.terms), plan)
        selected = protocol.campaign_profile(self.camp, self.terms)
        self.assertEqual(selected.fixed_roles, frozenset(rsi.BUNDLE_FILES))
        self.assertEqual(
            (selected.protocol, selected.mutable, selected.required_admission),
            (protocol.H_PROTOCOL, frozenset(("harness.json",)), protocol.H_ADMISSION),
        )
        with self.assertRaises(protocol.EpisodeNotReady) as raised:
            protocol.validate_plan(self.camp, self.terms)
        self.assertEqual(raised.exception.profile, selected)
        self.assertIsNone(protocol.campaign_profile(self.camp, {}))
        self.path.write_bytes(self.path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "differs from pin"):
            protocol.campaign_profile(self.camp, self.terms)

    def test_h_profile_cannot_broaden_scope_or_omit_fixed_admission(self):
        plan = self.h_terms()
        for field, value in (
            ("mutable", ["harness.json", "executor.md"]),
            ("mutable", ["harness.json", "harness.json"]),
            ("proposal_kind", "all"),
            ("submission_policy", "rust-preinstalled-v1"),
            ("model", "gpt-6-astra"),
            ("task_deadline_secs", 18001),
        ):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                protocol.inspect_plan(self.camp, {**self.terms, field: value})
        for changed in (
            {k: v for k, v in plan.items() if k != "required_admission"},
            {**plan, "required_admission": None},
            {**plan, "protocol": "single_candidate_h_v2"},
            {**plan, "max_phases": 4},
        ):
            self.publish_plan(changed)
            with self.subTest(plan=changed), self.assertRaises(RuntimeError):
                protocol.inspect_plan(self.camp, self.terms)

    def test_h_profile_requires_exact_fixed_auditor_and_cannot_apply_it_to_old_ph(self):
        self.h_terms()
        descriptor = self.terms["fixed_auditor"]
        for changed in (
            None,
            {},
            {**descriptor, "deadline_secs": 3601},
            {**descriptor, "instructions_sha256": "0" * 64},
        ):
            with self.subTest(value=changed), self.assertRaises(ValueError):
                protocol.inspect_plan(
                    self.camp, {**self.terms, "fixed_auditor": changed}
                )
        old = plan_terms(self.camp)
        with self.assertRaisesRegex(RuntimeError, "H-only"):
            protocol.inspect_plan(self.camp, {**old, "fixed_auditor": descriptor})

    def test_h_not_ready_terminal_binds_validated_protocol_before_any_launch(self):
        self.h_terms()
        self.terms["study"] = {"manifest_sha256": "a" * 64}
        write(self.camp / "campaign.json", self.terms)
        args = argparse.Namespace(
            camp=self.camp,
            study_sha256="a" * 64,
            plan=self.path,
            plan_sha256=self.terms["ph_supervisor"]["plan_sha256"],
        )
        controller = supervisor.Supervisor(args)
        with (
            mock.patch.object(controller, "command") as phase,
            mock.patch.object(study, "verify") as verify,
            mock.patch.object(supervisor.subprocess, "Popen") as launch,
        ):
            result = controller.run()
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "protocol",
                    "outcome",
                    "required_admission",
                    "phases",
                    "automatic_restart",
                )
            },
            {
                "protocol": protocol.H_PROTOCOL,
                "outcome": "not_paid_ready",
                "required_admission": protocol.H_ADMISSION,
                "phases": [],
                "automatic_restart": False,
            },
        )
        phase.assert_not_called()
        verify.assert_not_called()
        launch.assert_not_called()
        self.assertFalse((self.camp / "study-budget.sqlite").exists())

    def test_h_research_audit_freezes_every_role_while_ph_retains_execution_scope(self):
        delivery = self.camp / "research/step-1/run/workspace"
        registered = self.camp / "versions/candidate"
        for root, name in ((delivery, "policy"), (registered, "bundle")):
            (root / name).mkdir(parents=True)
            (root / name / "harness.json").write_text(
                '{"schema":1,"when":{"always":true}}'
            )
            (root / "EXPERIMENT.md").write_text("fixture experiment")
        bundles = {name: "same" for name in rsi.BUNDLE_FILES}
        versions = {
            "parent": {"bundle": bundles},
            "candidate": {
                "bundle": bundles.copy(),
                "lineage": {"parent": "parent", "proposed_by": "parent"},
            },
        }
        host = mock.Mock(camp=self.camp, terms={"mutable": ["harness.json"]})
        host.contract.return_value = {
            "standing": "discharged",
            "candidate": {"subject_hash": "subject"},
            "support": {"coordinate": {"subject_hash": "subject"}},
        }
        host.qualify.return_value = (True, "fixture-qualified", True)
        host.events.return_value = [
            {"body": {"role": "stream_policy", "version": "candidate", "batch": 2}}
        ]
        host.versions.return_value = versions
        host.version_dir.return_value = registered
        with mock.patch.object(rsi, "delivery_subject", return_value="subject"):
            for name in rsi.BUNDLE_FILES:
                versions["candidate"]["bundle"] = {**bundles, name: "changed"}
                controlled = audit.Audit(
                    host, {}, episode_profile=protocol.profile(protocol.H_PROTOCOL)
                )
                with (
                    self.subTest(role=name),
                    mock.patch.object(controlled, "role"),
                    self.assertRaisesRegex(RuntimeError, "policies changed"),
                ):
                    controlled.research(1, "parent", "candidate")
            versions["candidate"]["bundle"] = {**bundles, "executor.md": "changed"}
            legacy = audit.Audit(
                host, {}, episode_profile=protocol.profile(protocol.PROTOCOL)
            )
            with mock.patch.object(legacy, "role", return_value={"fixture": True}):
                self.assertEqual(
                    legacy.research(1, "parent", "candidate")["candidate"], "candidate"
                )
            versions["candidate"]["bundle"] = bundles.copy()
            with mock.patch.object(controlled, "role", return_value={"fixture": True}):
                self.assertEqual(
                    controlled.research(1, "parent", "candidate")["candidate"],
                    "candidate",
                )


if __name__ == "__main__":
    unittest.main()
