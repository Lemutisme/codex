"""The outer entry verifies the operator pin before importing the workflow."""

import builtins
import contextlib
import io
import json
import sys
import unittest
from unittest import mock

import procontract_live as live
import procontract_study_budget as budget
import test_procontract_study as fixtures


class LiveEntryTest(fixtures.StudyFixture):
    def setUp(self):
        super().setUp()
        self.seal()
        (self.camp / "campaign.json").write_text(json.dumps(self.terms))
        self.digest = self.terms["study"]["manifest_sha256"]
        budget.initialize(self.camp / "study-budget.sqlite", self.digest, self.limits)

    def argv(self, command, digest=None):
        return [
            "live",
            command,
            "--camp",
            str(self.camp),
            "--study-sha256",
            digest or self.digest,
        ]

    def test_operator_pin_and_runtime_drift_are_rejected_before_host_import(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "procontract_rsi":
                raise AssertionError("workflow imported before seal validation")
            return original_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", side_effect=guarded_import):
            with mock.patch.object(sys, "argv", self.argv("stream", "0" * 64)):
                with self.assertRaisesRegex(RuntimeError, "operator's study pin"):
                    live.main()
            (self.scripts / "procontract_study.py").write_text("drift")
            with mock.patch.object(sys, "argv", self.argv("stream")):
                with self.assertRaisesRegex(ValueError, "inventory changed"):
                    live.main()

    def test_budget_status_does_not_launch_or_expand_allowances(self):
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", self.argv("budget")),
            contextlib.redirect_stdout(output),
        ):
            live.main()
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "study_sha256": self.digest,
                "limits": self.limits,
                "reserved": {name: 0 for name in self.limits},
                "remaining": self.limits,
            },
        )


if __name__ == "__main__":
    unittest.main()
