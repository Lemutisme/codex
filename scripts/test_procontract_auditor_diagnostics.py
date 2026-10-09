"""Future diagnostics and legacy unknown replay; all native/model transport is fake."""

from functools import partial
import hashlib
import json
import unittest
from unittest import mock

import procontract_compliance_adapter as adapter
import procontract_compliance_gate as gate
import procontract_fixed_auditor as lane
import procontract_fixed_auditor_role as role
import test_procontract_fixed_auditor as fixtures


class DiagnosticTest(unittest.TestCase):
    setUp = fixtures.LaneTests.setUp
    native_fixture = fixtures.LaneTests.native_fixture

    def result(self, status):
        def native(*args):
            raw, terminal = self.native_fixture(*args)
            data = json.loads(raw)
            requirements = data["audits"][0]["requirements"]
            if status == "invalid_citation":
                next(iter(requirements.values()))["citations"][0]["sha256"] += "0"
            elif status == "unknown":
                requirements["no_install_or_external_network"]["status"] = "unknown"
            raw = role.encoded(data)
            return raw, {**terminal, "final_sha256": hashlib.sha256(raw).hexdigest()}

        with mock.patch.object(lane.native, "run", side_effect=native):
            return lane.execute(self.host, "probe", self.values, self.receipts)

    def test_invalid_citation_remains_unknown_with_authenticated_diagnostic(self):
        first = self.result("invalid_citation")
        self.assertEqual(
            (
                first["schema"],
                first["outcome"],
                first["findings"],
                first["validation_error"],
            ),
            (
                2,
                "unknown",
                [],
                {
                    "type": "ValueError",
                    "message": "compliance evidence: invalid citation identity/range",
                    "truncated": False,
                },
            ),
        )
        path = self.root / "fixed-auditor/probe/receipt.json"
        original = path.read_bytes()
        with mock.patch.object(lane.native, "run") as native:
            self.assertEqual(
                lane.execute(self.host, "probe", self.values, self.receipts), first
            )
            for error in (
                None,
                {**first["validation_error"], "message": "altered"},
                {**first["validation_error"], "truncated": 0},
            ):
                path.write_bytes(role.encoded({**first, "validation_error": error}))
                with self.subTest(error=error), self.assertRaises(ValueError):
                    lane.verify(self.host, "probe", self.values, self.receipts)
            for schema in (1, 2):
                changed = {k: v for k, v in first.items() if k != "validation_error"}
                path.write_bytes(role.encoded({**changed, "schema": schema}))
                with self.assertRaises(ValueError):
                    lane.verify(self.host, "probe", self.values, self.receipts)
            path.write_bytes(original)
        native.assert_not_called()
        # Stripping even the claim/terminal version cannot remove the ledger binding.
        claim_path = path.parent / "claim.json"
        claim = json.loads(claim_path.read_bytes())
        claim["identity"].pop("receipt_schema")
        claim_path.write_bytes(role.encoded(claim))
        changed = {k: v for k, v in first.items() if k != "validation_error"}
        changed.update(
            schema=1,
            identity=claim["identity"],
            identity_sha256=role.digest(claim["identity"]),
            files=lane._files(path.parent),
        )
        path.write_bytes(role.encoded(changed))
        with self.assertRaisesRegex(ValueError, "reservation"):
            lane.verify(self.host, "probe", self.values, self.receipts)

    def test_semantic_unknown_has_findings_but_no_validation_error(self):
        result = self.result("unknown")
        self.assertEqual(
            (result["outcome"], bool(result["findings"]), result["validation_error"]),
            ("unknown", True, None),
        )

    def test_valid_result_has_no_validation_error(self):
        result = self.result("valid")
        self.assertEqual(
            (result["outcome"], result["validation_error"]), ("accepted", None)
        )

    def test_long_unicode_error_is_bounded_and_stable_on_replay(self):
        with mock.patch.object(
            role.EvidenceService, "validate", side_effect=ValueError("错" * 1000)
        ):
            result = self.result("valid")
            self.assertEqual(
                result["validation_error"],
                {"type": "ValueError", "message": "错" * 170, "truncated": True},
            )
            self.assertLessEqual(
                len(result["validation_error"]["message"].encode()), 512
            )
            self.assertEqual(
                lane.verify(self.host, "probe", self.values, self.receipts), result
            )

    def test_legacy_unknown_replay_is_unchanged_and_cannot_advance(self):
        # Produce the actual historical shape and reservation identity, without a v2 marker.
        with mock.patch.object(
            lane, "_identity", side_effect=partial(lane._identity, receipt_schema=1)
        ):
            legacy = self.result("invalid_citation")
        self.assertEqual(
            (legacy["schema"], legacy["outcome"], legacy["findings"]),
            (1, "unknown", []),
        )
        self.assertNotIn("receipt_schema", legacy["identity"])
        self.assertNotIn("validation_error", legacy)
        path = self.root / "fixed-auditor/probe/receipt.json"
        original = path.read_bytes()
        run = self.root / "runs/stream-v-t/attempt-1"
        run.mkdir(parents=True)
        (run.parent / "result.json").write_bytes(
            role.encoded(
                {
                    "version": "v",
                    "task": "t",
                    "purpose": "stream",
                    "run_dir": str(run),
                    "validity": "valid",
                }
            )
        )
        self.host.events, self.host.record = mock.Mock(return_value=[]), mock.Mock()
        with (
            mock.patch.object(lane.native, "run") as native,
            mock.patch.object(
                adapter,
                "build_run_pack",
                return_value=(self.values[0], self.receipts[0]),
            ),
            mock.patch.object(
                gate.store,
                "digest",
                side_effect=lambda domain, value: role.digest([domain, value]),
            ),
        ):
            self.assertEqual(
                lane.execute(self.host, "probe", self.values, self.receipts), legacy
            )
            with self.assertRaisesRegex(
                gate.Inconclusive, "unknown; no advancement or retry"
            ):
                gate._check(self.host, "probe", {}, [("v", "t", "stream")], freeze=True)
        native.assert_not_called()
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
