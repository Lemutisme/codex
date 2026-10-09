"""Free synthetic init reaches the intentional H stop, never transport or provisioning."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_episode_init as episode_init
import procontract_fixed_auditor_role as auditor_role
import procontract_native_trace_binding as trace
import procontract_ph_protocol as protocol
import procontract_ph_supervisor as supervisor
import procontract_rsi as rsi
from test_procontract_ph_supervisor import plan_terms, write


class EpisodeInitTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.camp = self.root / "campaign"
        self.terms = plan_terms(self.camp)
        self.plan = Path(self.terms["ph_supervisor"]["plan_path"])

    def h(self):
        plan = protocol.document(self.plan)
        plan.update(
            protocol=protocol.H_PROTOCOL, required_admission=protocol.H_ADMISSION
        )
        write(self.plan, plan)
        self.terms["ph_supervisor"]["plan_sha256"] = protocol.digest(self.plan)
        self.terms.update(
            submission_policy=protocol.BUILD_RUNTIME_POLICY,
            proposal_kind="harness",
            mutable=["harness.json"],
        )

    def test_derives_selected_provider_and_copied_profile_without_operator_knobs(self):
        self.h()
        config = (
            'model_provider="selected"\n[model_providers.decoy]\n'
            'base_url="https://decoy.invalid/v1"\nenv_key="DECOY"\n'
            '[model_providers.selected]\nbase_url="http://127.0.0.1/v1"\n'
            'env_key="PINNED_KEY"\nwire_api="responses"\n'
        )
        with mock.patch.object(
            runner, "config_toml", return_value=config
        ) as configuration:
            episode_init.derive_h_terms(self.terms)
            configuration.assert_called_once_with(model="gpt-5.6-luna", effort="max")
        self.assertEqual(
            self.terms["fixed_auditor"],
            auditor_role.descriptor(
                {"base_url": "http://127.0.0.1/v1", "env_key": "PINNED_KEY"}
            ),
        )
        self.assertEqual(self.terms["native_notice_trace"], trace.PROFILE)
        self.assertIsNot(self.terms["native_notice_trace"], trace.PROFILE)
        with mock.patch.object(runner, "config_toml", return_value=config):
            before = copy.deepcopy(self.terms)
            episode_init.derive_h_terms(self.terms)
            self.assertEqual(self.terms, before)
            self.terms["native_notice_trace"]["max_bytes"] += 1
            before = copy.deepcopy(self.terms)
            with self.assertRaisesRegex(RuntimeError, "existing terms"):
                episode_init.derive_h_terms(self.terms)
            self.assertEqual(self.terms, before)

    def test_legacy_terms_are_byte_stable_and_plan_pin_precedes_derivation(self):
        before = json.dumps(self.terms, sort_keys=True)
        with mock.patch.object(runner, "config_toml") as configuration:
            episode_init.derive_h_terms(self.terms)
            self.assertEqual(json.dumps(self.terms, sort_keys=True), before)
            configuration.assert_not_called()
            self.h()
            self.plan.write_bytes(self.plan.read_bytes() + b" ")
            with self.assertRaisesRegex(RuntimeError, "differs from pin"):
                episode_init.derive_h_terms(self.terms)
            configuration.assert_not_called()

    def test_inspection_requires_exact_typed_trace_profile_and_keeps_old_ph_unopted(
        self,
    ):
        self.h()
        episode_init.derive_h_terms(self.terms)
        protocol.inspect_plan(self.camp, self.terms)
        for value in (
            None,
            {},
            {**trace.PROFILE, "schema": True},
            {**trace.PROFILE, "max_bytes": float(trace.PROFILE["max_bytes"])},
            {**trace.PROFILE, "transport": "websocket"},
            {**trace.PROFILE, "extra": "override"},
        ):
            with (
                self.subTest(profile=value),
                self.assertRaisesRegex(RuntimeError, "native notice trace"),
            ):
                protocol.inspect_plan(
                    self.camp, {**self.terms, "native_notice_trace": value}
                )
        old = plan_terms(self.camp)
        with self.assertRaisesRegex(RuntimeError, "H-only"):
            protocol.inspect_plan(
                self.camp, {**old, "native_notice_trace": trace.PROFILE}
            )

    def test_cli_init_reaches_not_ready_with_derived_terms_before_seal_budget_or_mount(
        self,
    ):
        self.h()
        (self.root / "prompt.txt").write_text("synthetic task")
        (self.root / "stream.txt").write_text("\n".join(self.terms["stream"]["order"]))
        write(self.root / "sealed.json", {"select": self.terms["pools"]["confirm"]})
        flags = {
            "camp": self.camp,
            "codex-bin": self.root / "codex",
            "task-prompt": self.root / "prompt.txt",
            "research-image": "sha256:" + "a" * 64,
            "programbench": self.root / "pb",
            "hf-revision": "a" * 40,
            "instances": self.root / "stream.txt",
            "sealed": self.root / "sealed.json",
            "batch": 1,
            "stream-mode": "guarded",
            "release-every": 1,
            "method-confirmation": "defer",
            "confirm-pool": 4,
            "confirm-tasks": 4,
            "confirm-min-wins": 3,
            "confirm-min-delta": 0.000001,
            "confirmation-exposure-scope": "prospective_lineage",
            "adoption": "presumed",
            "mutable": "harness.json",
            "proposal-kind": "harness",
            "submission-policy": protocol.BUILD_RUNTIME_POLICY,
            "checkpoint": self.root / "checkpoint",
            "checkpoint-sha256": "b" * 64,
            "canonical-registry": self.root / "registry.json",
            "canonical-registry-sha256": "c" * 64,
            "canonical-pins-sha256": "d" * 64,
            "ph-supervisor-plan": self.plan,
            "ph-supervisor-sha256": protocol.digest(self.plan),
            "study-task-launches": 12,
            "study-learning-launches": 21,
            "study-allocated-secs": 291600,
        }
        argv = [
            "rsi",
            "init",
            *[
                part
                for key, value in flags.items()
                for part in ("--" + key, str(value))
            ],
        ]
        checkpoint = SimpleNamespace(
            root=self.root / "checkpoint", descriptor=lambda: {"fixture": True}
        )
        inspected = []

        def validate(camp, terms):
            inspected.append(copy.deepcopy(terms))
            return protocol.validate_plan(camp, terms)

        # Resource validation and the two administrative digest commands are synthetic;
        # derivation, CLI wiring and closed-profile validation execute their real paths.
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                rsi.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="a" * 64 + "\n"),
            ),
            mock.patch.object(rsi.checkpoints, "load", return_value=checkpoint),
            mock.patch.object(rsi.checkpoints, "from_terms", return_value=checkpoint),
            mock.patch.object(canonical, "validate_identity"),
            mock.patch.object(canonical, "registry"),
            mock.patch.object(supervisor, "validate_plan", side_effect=validate),
            mock.patch.object(rsi.study, "freeze") as freeze,
            mock.patch.object(rsi.study_budget, "initialize") as initialize,
            mock.patch.object(runner, "AppServer") as server,
            mock.patch.object(trace, "provision") as mount,
            self.assertRaises(protocol.EpisodeNotReady),
        ):
            rsi.main()
        selected = tomllib.loads(runner.config_toml())
        provider = selected["model_providers"][selected["model_provider"]]
        self.assertEqual(
            inspected[0]["fixed_auditor"],
            auditor_role.descriptor(
                {key: provider[key] for key in ("base_url", "env_key")}
            ),
        )
        self.assertEqual(inspected[0]["native_notice_trace"], trace.PROFILE)
        for operation in (freeze, initialize, server, mount):
            operation.assert_not_called()
        self.assertFalse((self.camp / "campaign.json").exists())
        self.assertFalse((self.camp / "study-budget.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
