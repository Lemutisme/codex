"""Mocked fixed role launch custody; no model calls or actual study runs."""

import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import procontract_fixed_auditor as lane
import procontract_fixed_auditor_role as role
import procontract_study_budget as budget
from test_procontract_fixed_auditor_role import (
    LIMITS,
    PROVIDER,
    answer,
    pack,
    receipt,
    serve,
)


class LaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = [pack()]
        self.expected_launches = 1
        self.receipts = [receipt(self.values[0])]
        self.host = SimpleNamespace(
            camp=self.root,
            terms={
                "model": role.MODEL,
                "effort": role.EFFORT,
                "codex_bin": "/fixed/native",
                "codex_sha256": "b" * 64,
                "fixed_auditor": role.descriptor(PROVIDER),
                "ph_supervisor": {"plan_sha256": "c" * 64},
                "study": {
                    "manifest_path": str(self.root / "study.json"),
                    "manifest_sha256": "a" * 64,
                },
            },
        )
        self.seal = {"limits": LIMITS}
        budget.initialize(self.root / "study-budget.sqlite", "a" * 64, LIMITS)
        self.profile_patch = patch.object(
            lane.protocol,
            "campaign_profile",
            return_value=SimpleNamespace(protocol=lane.protocol.H_PROTOCOL),
        )
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.verify_patch = patch.object(lane.study, "verify", return_value=self.seal)
        self.verify_patch.start()
        self.addCleanup(self.verify_patch.stop)
        self.env = patch.dict(os.environ, {PROVIDER["env_key"]: "LOCAL_FIXTURE_ONLY"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def native_fixture(self, binary, root, service, provider, credential):
        # Assert the paid allowance and durable claim already exist at invocation.
        self.assertTrue((root / "claim.json").is_file())
        self.assertEqual(
            budget.status(self.root / "study-budget.sqlite", "a" * 64, LIMITS)[
                "reserved"
            ],
            {
                "task_launches": 0,
                "learning_launches": self.expected_launches,
                "allocated_seconds": 3600 * self.expected_launches,
            },
        )
        (root / "codex-home").mkdir()
        (root / "codex-home/config.toml").write_text(role.config(provider))
        (root / "codex-home/environments.toml").write_text("include_local = false\n")
        rows = serve(service)
        for name in ("rpc.jsonl", "stdout.log", "stderr.log"):
            (root / name).write_bytes(b"")
        (root / "evidence-served.jsonl").write_bytes(
            b"".join(role.encoded(row) + b"\n" for row in rows)
        )
        raw = role.encoded(
            {"schema": 1, "audits": [answer(value) for value in service.packs]}
        )
        return raw, {
            "schema": 1,
            "status": "completed",
            "native_exit": 0,
            "final_sha256": hashlib.sha256(raw).hexdigest(),
            "final_usage": {"totalTokens": 17},
        }

    def test_reserve_claim_accept_and_replay_no_new_launch(self):
        with patch.object(lane.native, "run", side_effect=self.native_fixture) as run:
            first = lane.execute(self.host, "probe", self.values, self.receipts)
            replay = lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(first, replay)
        self.assertEqual((first["outcome"], run.call_count), ("accepted", 1))
        self.assertEqual(first["identity"]["role"], "fixed_auditor")
        self.assertEqual(
            lane.audit_reservation(
                self.host,
                self.seal,
                "fixed-auditor/probe",
                first["identity"],
                first["reservation"],
            ),
            first,
        )

    def test_context_or_evidence_rebinding_refused_before_native(self):
        with patch.object(lane.native, "run", side_effect=self.native_fixture):
            lane.execute(self.host, "probe", self.values, self.receipts)
        changed = [{**self.receipts[0], "capture": "different"}]
        with self.assertRaises(ValueError), patch.object(lane.native, "run") as run:
            lane.execute(self.host, "probe", self.values, changed)
        run.assert_not_called()

    def test_claim_without_terminal_never_retries(self):
        with patch.object(
            lane.native, "run", side_effect=RuntimeError("simulated host crash")
        ):
            with self.assertRaises(RuntimeError):
                lane.execute(self.host, "probe", self.values, self.receipts)
        with patch.object(lane.native, "run") as run:
            with self.assertRaises(FileNotFoundError):
                lane.execute(self.host, "probe", self.values, self.receipts)
        run.assert_not_called()
        self.assertEqual(
            budget.status(self.root / "study-budget.sqlite", "a" * 64, LIMITS)[
                "reserved"
            ]["learning_launches"],
            1,
        )

    def test_timeout_terminal_preserves_budget_and_no_retry(self):
        with patch.object(
            lane.native,
            "run",
            return_value=(
                None,
                {
                    "schema": 1,
                    "status": "timeout",
                    "native_exit": -9,
                    "final_usage": None,
                },
            ),
        ) as run:
            value = lane.execute(self.host, "initial_serve", self.values, self.receipts)
            self.assertEqual(
                lane.execute(self.host, "initial_serve", self.values, self.receipts),
                value,
            )
        self.assertEqual((value["outcome"], run.call_count), ("unknown", 1))

    def test_real_provider_blocked_before_reservation(self):
        self.host.terms["fixed_auditor"] = role.descriptor(
            {**PROVIDER, "base_url": "https://example.test/v1"}
        )
        with self.assertRaises(RuntimeError), patch.object(lane.native, "run") as run:
            lane.execute(self.host, "probe", self.values, self.receipts)
        run.assert_not_called()
        self.assertEqual(
            budget.status(self.root / "study-budget.sqlite", "a" * 64, LIMITS)[
                "reserved"
            ]["learning_launches"],
            0,
        )

    def test_wrong_episode_profile_refused_before_spending(self):
        with patch.object(
            lane.protocol,
            "campaign_profile",
            return_value=SimpleNamespace(protocol=lane.protocol.PROTOCOL),
        ):
            with self.assertRaises(ValueError):
                lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(
            budget.status(self.root / "study-budget.sqlite", "a" * 64, LIMITS)[
                "reserved"
            ]["learning_launches"],
            0,
        )

    def test_unknown_judgment_remains_inconclusive(self):
        findings = [{"accepted": False}]
        raw = role.encoded({"audits": [answer(self.values[0], "unknown")]})
        self.assertEqual(lane._decision(findings, raw), "unknown")
        raw = role.encoded({"audits": [answer(self.values[0], "violation")]})
        self.assertEqual(lane._decision(findings, raw), "rejected")

    def test_openai_key_file_precedes_environment_without_persisting_key(self):
        self.host.terms["fixed_auditor"] = role.descriptor(
            {**PROVIDER, "env_key": "OPENAI_API_KEY"}
        )
        key_file = self.root / "synthetic-key"
        key_file.write_text("SYNTHETIC_FILE_KEY\n")
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY_FILE": str(key_file),
                "OPENAI_API_KEY": "SYNTHETIC_ENV_KEY",
            },
        ):
            with patch.object(
                lane.native, "run", side_effect=self.native_fixture
            ) as run:
                terminal = lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(run.call_args.args[-1], "SYNTHETIC_FILE_KEY")
        self.assertNotIn("SYNTHETIC_FILE_KEY", role.encoded(terminal).decode())

    def test_standard_default_key_file_uses_only_synthetic_home(self):
        self.host.terms["fixed_auditor"] = role.descriptor(
            {**PROVIDER, "env_key": "OPENAI_API_KEY"}
        )
        home = self.root / "synthetic-home"
        key_file = home / ".config/openai/api_key"
        key_file.parent.mkdir(parents=True)
        key_file.write_text("SYNTHETIC_DEFAULT_KEY")
        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "SYNTHETIC_ENV_KEY"}, clear=True
        ):
            with patch("procontract_benchmark_runner.Path.home", return_value=home):
                with patch.object(
                    lane.native, "run", side_effect=self.native_fixture
                ) as run:
                    lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(run.call_args.args[-1], "SYNTHETIC_DEFAULT_KEY")

    def test_missing_or_empty_key_file_falls_back_to_environment(self):
        self.host.terms["fixed_auditor"] = role.descriptor(
            {**PROVIDER, "env_key": "OPENAI_API_KEY"}
        )
        key_file = self.root / "synthetic-key"
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY_FILE": str(key_file),
                "OPENAI_API_KEY": "SYNTHETIC_ENV_KEY",
            },
        ):
            with patch.object(
                lane.native, "run", side_effect=self.native_fixture
            ) as run:
                lane.execute(self.host, "initial_serve", self.values, self.receipts)
                key_file.write_text("  \n")
                self.expected_launches = 2
                lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(
            [call.args[-1] for call in run.call_args_list], ["SYNTHETIC_ENV_KEY"] * 2
        )

    def test_rotated_file_is_resolved_per_new_claim_not_replay(self):
        self.host.terms["fixed_auditor"] = role.descriptor(
            {**PROVIDER, "env_key": "OPENAI_API_KEY"}
        )
        key_file = self.root / "synthetic-key"
        key_file.write_text("SYNTHETIC_ROTATION_A")
        with patch.dict(os.environ, {"OPENAI_API_KEY_FILE": str(key_file)}):
            with patch.object(
                lane.native, "run", side_effect=self.native_fixture
            ) as run:
                first = lane.execute(
                    self.host, "initial_serve", self.values, self.receipts
                )
                key_file.write_text("SYNTHETIC_ROTATION_B")
                self.assertEqual(
                    lane.execute(
                        self.host, "initial_serve", self.values, self.receipts
                    ),
                    first,
                )
                self.expected_launches = 2
                lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(
            [call.args[-1] for call in run.call_args_list],
            ["SYNTHETIC_ROTATION_A", "SYNTHETIC_ROTATION_B"],
        )

    def test_custom_test_key_does_not_read_openai_key_file(self):
        with patch(
            "procontract_benchmark_runner.current_key",
            side_effect=AssertionError("must not read OpenAI key"),
        ):
            with patch.object(
                lane.native, "run", side_effect=self.native_fixture
            ) as run:
                lane.execute(self.host, "probe", self.values, self.receipts)
        self.assertEqual(run.call_args.args[-1], "LOCAL_FIXTURE_ONLY")

    def test_file_and_ledger_tampering_refused(self):
        with patch.object(lane.native, "run", side_effect=self.native_fixture):
            lane.execute(self.host, "probe", self.values, self.receipts)
        target = self.root / "fixed-auditor/probe/final.json"
        target.write_text("{}")
        with self.assertRaises(ValueError):
            lane.verify(self.host, "probe", self.values, self.receipts)

    def test_phase_cardinality_fails_without_spending(self):
        with self.assertRaises(ValueError):
            lane.execute(self.host, "confirmation", self.values, self.receipts)
        self.assertFalse((self.root / "fixed-auditor").exists())


if __name__ == "__main__":
    unittest.main()
