"""Research scoping narrows permission without restricting nested updater targets."""

import copy
import os
import tempfile
import unittest
from unittest import mock

import procontract_proposal_scope as scope
import test_procontract_rsi as fixtures


class ProposalScopeTest(unittest.TestCase):
    def test_missing_or_null_stream_preserves_legacy_mixed_proposal_behavior(self):
        changed = ["research.md", "executor.md", "harness.json"]
        for terms in ({}, {"stream": None}):
            with self.subTest(terms=terms):
                host = mock.Mock(terms=terms)
                self.assertEqual(
                    (
                        scope.research_constraint(terms),
                        scope.intervention_problem(terms, changed),
                    ),
                    ("", ""),
                )
                scope.assert_task_confirmation(host, "candidate", "incumbent")
                host.validate_harness.assert_not_called()
                host.versions.assert_not_called()

    def test_default_and_explicit_all_preserve_existing_authority(self):
        for extra in ({}, {"proposal_kind": "all"}):
            with self.subTest(extra=extra):
                terms = {"mutable": ["executor.md", "future.md"], **extra}
                selected = scope.editable(terms)
                self.assertEqual(selected, terms["mutable"])
                selected.append("research.md")
                self.assertEqual(terms["mutable"], ["executor.md", "future.md"])

    def test_methods_intersects_authority_and_preserves_order_without_mutation(self):
        terms = {
            "proposal_kind": "methods",
            "mutable": ["harness.json", "research.md", "executor.md", "analyst.md"],
        }
        before = copy.deepcopy(terms)
        self.assertEqual(scope.editable(terms), ["research.md", "analyst.md"])
        self.assertEqual(terms, before)
        # The nested updater retains the original TASK/H authority, not the result above.
        self.assertEqual(
            [
                name
                for name in terms["mutable"]
                if name in ("harness.json", "executor.md")
            ],
            ["harness.json", "executor.md"],
        )

    def test_execution_and_harness_never_add_unauthorized_files(self):
        for kind, expected in (
            ("execution", ["reviewer.md", "executor.md"]),
            ("harness", ["harness.json"]),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    scope.editable(
                        {
                            "proposal_kind": kind,
                            "mutable": [
                                "reviewer.md",
                                "research.md",
                                "harness.json",
                                "executor.md",
                            ],
                        }
                    ),
                    expected,
                )

    def test_empty_authorized_intersection_is_not_a_fallback_to_all(self):
        for kind, mutable in (
            ("all", []),
            ("methods", ["executor.md", "harness.json"]),
            ("execution", ["research.md"]),
            ("harness", ["executor.md"]),
        ):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "no authorized mutable files"):
                    scope.editable({"proposal_kind": kind, "mutable": mutable})

    def test_invalid_kind_is_rejected_instead_of_widening_scope(self):
        for kind in ("method", "ALL", "", None, True, [], {}):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "proposal_kind must be"):
                    scope.editable({"proposal_kind": kind, "mutable": ["research.md"]})

    def test_malformed_authority_is_rejected(self):
        for terms in (
            {},
            {"mutable": "research.md"},
            {"mutable": None},
            {"mutable": [None]},
            {"mutable": [""]},
        ):
            with self.subTest(terms=terms):
                with self.assertRaisesRegex(ValueError, "mutable must be a list"):
                    scope.editable(terms)

    def test_ordinary_methods_scope_keeps_nested_execution_and_null_authorized(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"FAKE_RESEARCH_MODE": "better"}),
        ):
            host = fixtures.host(
                fixtures.campaign(tmp, proposal_kind="methods"), fixtures.FakeTasks()
            )
            parent = host.incumbent()
            self.assertEqual(host.terms["proposal_kind"], "methods")
            self.assertIn("did not qualify", host.step())
            self.assertEqual(list(host.versions()), [parent])
            root = host.camp / "research" / "step-1"
            allowed = scope.editable(host.terms)
            self.assertIn(
                f"You may edit only these files: {', '.join(allowed)}.",
                (root / "prompt.md").read_text(),
            )
            delivery = root / "run" / "workspace"
            # Nested updater calls still use the full campaign authority.
            self.assertEqual(host.qualify(delivery, parent), (True, "qualified", True))
            original = host.version_dir(parent) / "bundle" / "executor.md"
            (delivery / "policy" / "executor.md").write_bytes(original.read_bytes())
            self.assertEqual(
                host.qualify(delivery, parent, allowed_files=allowed),
                (True, "a null experiment: the bundle is unchanged", False),
            )


if __name__ == "__main__":
    unittest.main()
