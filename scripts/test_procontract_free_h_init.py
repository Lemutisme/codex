"""Real CLI/seal/store over file-only fixtures; no live image or model is contacted."""

import argparse
import hashlib
import json
import unittest
from unittest import mock

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_dependency_inspection as inspection
import procontract_dependency_policy as dependencies
import procontract_fixed_auditor as auditor
import procontract_fixed_auditor_role as auditor_role
import procontract_native_trace_binding as trace
import procontract_ph_protocol as protocol
import procontract_ph_supervisor as supervisor
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_canonical_host as canonical_fixtures
import test_procontract_checkpoint_host as checkpoint_fixtures
import test_procontract_dependency_host as dependency_fixtures
import test_procontract_study_launch as launch_fixtures


class FreeHInitTest(unittest.TestCase):
    args = canonical_fixtures.CanonicalHostTest.args
    make_host = canonical_fixtures.CanonicalHostTest.make_host
    repin = checkpoint_fixtures.CheckpointHostTest.repin
    initialize = checkpoint_fixtures.CheckpointHostTest.initialize
    preparation = launch_fixtures.StudyLaunchTest.preparation
    transport = launch_fixtures.StudyLaunchTest.transport
    balance = launch_fixtures.StudyLaunchTest.balance

    def setUp(self):
        self.enterContext(mock.patch.object(auditor, "PAID_ENABLED", False))
        checkpoint_fixtures.CheckpointHostTest.setUp(self)
        stream = [f"free__serve{i}.1234567" for i in range(4)]
        self.task = stream[0]
        self.audit = [f"reserve__held{i}.7654321" for i in range(4)]
        self.data["tasks"] = {
            task: {"total": 3, "image": "sha256:" + "3" * 64}
            for task in [*stream, *self.audit]
        }
        self.instances.write_text("\n".join(stream))
        canonical.write_json(self.root / "sealed.json", {"select": self.audit})
        self.policy_path, self.receipts = dependency_fixtures.write_policy(
            self.root, self.data
        )
        policy = json.loads(self.policy_path.read_bytes())
        prompt = dependencies.render_prompt(
            policy["allowed"], policy_name=dependencies.BUILD_RUNTIME_POLICY
        )
        policy.update(
            policy=dependencies.BUILD_RUNTIME_POLICY,
            prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        )
        canonical.write_json(self.policy_path, policy)
        (self.root / "prompt.txt").write_bytes(prompt)
        self.data["dependency_policy"]["sha256"] = canonical.sha256(self.policy_path)
        self.data["python"] = str(self.root / "pb/.venv/bin/python")
        # Exercise the real mandatory resource inventory, not a mocked study seal.
        for name in (
            "pb/uv.lock",
            "pb/src/module.py",
            "pb/scripts/scorer.py",
            "pb/.venv/pyvenv.cfg",
            "pb/.venv/bin/python",
            "pb/.venv/lib/python3/site-packages/package.py",
            "wheels/package.whl",
            "blob-manifest.json",
            "codex-code-mode-host",
            *[f"blobs/{task}/tests.tar.gz" for task in self.data["tasks"]],
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("file-only fixture " + name)
        (self.root / "codex-code-mode-host").chmod(0o755)
        dependency_fixtures.DependencyHostTest.repin(self)
        self.plan = self.root / "h-plan.json"
        canonical.write_json(
            self.plan,
            {
                "schema": 1,
                "protocol": protocol.H_PROTOCOL,
                "campaign": str(self.root / "h-free"),
                "source_sha256": protocol.digest(protocol.SUPERVISOR),
                "max_phases": 3,
                "required_admission": protocol.H_ADMISSION,
            },
        )
        self.limits = {
            "task_launches": 12,
            "learning_launches": 21,
            "allocated_seconds": 291600,
        }
        extra = [
            "--research-image",
            "sha256:" + "a" * 64,
            "--submission-policy",
            dependencies.BUILD_RUNTIME_POLICY,
            "--proposal-kind",
            "harness",
            "--mutable",
            "harness.json",
            "--method-confirmation",
            "defer",
            "--adoption",
            "presumed",
            "--confirm-pool",
            "4",
            "--confirm-tasks",
            "4",
            "--confirm-min-wins",
            "3",
            "--confirm-min-delta",
            "0.000001",
            "--ph-supervisor-plan",
            str(self.plan),
            "--ph-supervisor-sha256",
            protocol.digest(self.plan),
            "--study-task-launches",
            "12",
            "--study-learning-launches",
            "21",
            "--study-allocated-secs",
            "291600",
        ]
        with (
            mock.patch.object(inspection, "verify_image") as image,
            mock.patch.object(trace, "provision") as provision,
            mock.patch.object(runner, "AppServer") as server,
        ):
            self.host = self.initialize("h-free", extra=extra)
        for operation in (image, provision, server):
            operation.assert_not_called()
        self.parent = self.producer = self.host.incumbent()
        self.database = self.host.camp / "study-budget.sqlite"

    def test_real_free_init_seals_exact_inputs_and_keeps_supervisor_not_ready(self):
        terms = self.host.terms
        sealed = study.verify(self.host.camp, terms, runner=self.host.runner)
        self.assertEqual(sealed["limits"], self.limits)
        self.assertEqual(terms["native_notice_trace"], trace.PROFILE)
        auditor_role.validate_descriptor(terms["fixed_auditor"])
        self.assertEqual(
            protocol.inspect_plan(self.host.camp, terms)["protocol"],
            protocol.H_PROTOCOL,
        )
        self.assertEqual(self.balance()["reserved"], dict.fromkeys(self.limits, 0))
        self.assertEqual(self.host.events("execution"), [])
        for path in (self.plan, self.policy_path, self.artifact / "MANIFEST.json"):
            self.assertIn(str(path), sealed["files"])
        args = argparse.Namespace(
            camp=self.host.camp,
            study_sha256=terms["study"]["manifest_sha256"],
            plan=self.plan,
            plan_sha256=protocol.digest(self.plan),
        )
        controller = supervisor.Supervisor(args)
        with mock.patch.object(controller, "command") as command:
            terminal = controller.run()
        command.assert_not_called()
        self.assertEqual(
            (terminal["protocol"], terminal["outcome"], terminal["phases"]),
            (protocol.H_PROTOCOL, "not_paid_ready", []),
        )
        self.assertEqual(self.balance()["reserved"], dict.fromkeys(self.limits, 0))

    def test_direct_runner_cannot_buy_any_h_task_or_learning_role(self):
        with (
            self.transport() as opened,
            mock.patch.object(runner, "AppServer") as server,
            mock.patch.object(inspection, "verify_image") as image,
            mock.patch.object(trace, "provision") as provision,
            mock.patch.object(budget, "reserve") as reserve,
        ):
            for role in ("executor.md", "analyst.md", "challenger.md", "research.md"):
                args = self.preparation(role, role[:-3])
                runner.prepare(args)
                with (
                    self.subTest(role=role),
                    self.assertRaises(protocol.EpisodeNotReady),
                ):
                    runner.run(args)
                self.assertFalse((args.run_dir / "study-launch.json").exists())
        for operation in (server, image, provision, reserve):
            operation.assert_not_called()
        self.assertEqual(opened, [])
        self.assertEqual(self.balance()["reserved"], dict.fromkeys(self.limits, 0))


if __name__ == "__main__":
    unittest.main()
