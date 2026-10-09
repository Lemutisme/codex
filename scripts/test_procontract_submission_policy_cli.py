"""Explicit policy scope through CLI/canonical init; no paid task or image inspection."""

import copy
import hashlib
import json
import sys
import unittest
from unittest import mock

import procontract_canonical as canonical
import procontract_dependency_inspection as inspection
import procontract_dependency_policy as policies
import procontract_rsi as rsi
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_canonical_host as canonical_fixtures
import test_procontract_dependency_host as dependency_fixtures


class SubmissionPolicyCliTest(unittest.TestCase):
    make_host = canonical_fixtures.CanonicalHostTest.make_host
    initialize_study = dependency_fixtures.DependencyHostTest.initialize_study
    repin = dependency_fixtures.DependencyHostTest.repin

    def args(self, camp):
        args = canonical_fixtures.CanonicalHostTest.args(self, camp)
        if getattr(self, "use_submission_policy", False):
            args += ["--submission-policy", self.policy_name]
        return args

    def setUp(self):
        self.policy_name = policies.BUILD_RUNTIME_POLICY
        dependency_fixtures.DependencyHostTest.setUp(self)
        self.select(self.policy_name)

    def select(self, name):
        self.policy_name = name
        value = json.loads(self.policy_path.read_bytes())
        prompt = policies.render_prompt(value["allowed"], policy_name=name)
        value.update(policy=name, prompt_sha256=hashlib.sha256(prompt).hexdigest())
        canonical.write_json(self.policy_path, value)
        (self.root / "prompt.txt").write_bytes(prompt)
        self.data["dependency_policy"]["sha256"] = canonical.sha256(self.policy_path)
        self.repin()

    def test_new_scope_initializes_with_exact_pins_and_zero_unchanged_budget(self):
        limits = copy.deepcopy(self.limits)
        original = (
            self.policy_path.read_bytes(),
            (self.root / "prompt.txt").read_bytes(),
        )
        with mock.patch.object(inspection, "verify_image") as inspect_image:
            host = self.initialize_study()
        inspect_image.assert_not_called()
        frozen = study.verify(host.camp, host.terms, runner=host.runner)
        self.assertEqual(frozen["limits"], limits)
        self.assertEqual(host.terms["submission_policy"], policies.BUILD_RUNTIME_POLICY)
        self.assertEqual(
            canonical.registry().dependency_policy.name, policies.BUILD_RUNTIME_POLICY
        )
        self.assertEqual(
            host.terms["task_prompt_sha256"], hashlib.sha256(original[1]).hexdigest()
        )
        self.assertEqual(
            (self.policy_path.read_bytes(), (self.root / "prompt.txt").read_bytes()),
            original,
        )
        self.assertEqual(
            budget.status(
                host.camp / "study-budget.sqlite",
                host.terms["study"]["manifest_sha256"],
                limits,
            )["reserved"],
            {"task_launches": 0, "learning_launches": 0, "allocated_seconds": 0},
        )
        self.assertEqual(host.events("execution"), [])

    def test_cli_scope_cannot_reinterpret_manifest_or_prompt(self):
        self.policy_name = policies.POLICY
        with self.assertRaisesRegex(ValueError, "campaign rule differs"):
            self.make_host(self.root / "wrong-scope")
        self.policy_name = policies.BUILD_RUNTIME_POLICY
        manifest = json.loads(self.policy_path.read_bytes())
        (self.root / "prompt.txt").write_bytes(
            policies.render_prompt(manifest["allowed"])
        )
        with self.assertRaisesRegex(ValueError, "campaign prompt differs"):
            self.make_host(self.root / "wrong-prompt")
        for name in ("wrong-scope", "wrong-prompt"):
            self.assertFalse((self.root / name / "campaign.json").exists())

    def test_legacy_scope_round_trip_keeps_legacy_prompt_and_identity(self):
        self.select(policies.POLICY)
        original = (
            self.policy_path.read_bytes(),
            (self.root / "prompt.txt").read_bytes(),
        )
        host = self.make_host(self.root / "legacy-policy")
        self.assertEqual(host.terms["submission_policy"], policies.POLICY)
        self.assertEqual(canonical.registry().dependency_policy.name, policies.POLICY)
        self.assertEqual(
            (self.policy_path.read_bytes(), (self.root / "prompt.txt").read_bytes()),
            original,
        )
        self.assertEqual(
            host.terms["task_prompt_sha256"], hashlib.sha256(original[1]).hexdigest()
        )

    def test_new_scope_still_requires_registry_and_unknown_scope_never_dispatches(self):
        with (
            mock.patch.object(sys, "argv", self.args(self.root / "missing-registry")),
            mock.patch.object(rsi.subprocess, "run") as external,
            self.assertRaisesRegex(SystemExit, "canonical dependency registry"),
        ):
            rsi.main()
        external.assert_not_called()
        self.policy_name = "rust-preinstalled-latest"
        with (
            mock.patch.object(sys, "argv", self.args(self.root / "unknown-scope")),
            mock.patch.object(sys, "stderr"),
            mock.patch.object(rsi, "cmd_init") as initialize,
            self.assertRaises(SystemExit) as raised,
        ):
            rsi.main()
        initialize.assert_not_called()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
