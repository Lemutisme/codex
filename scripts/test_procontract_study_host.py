"""Host study boundaries with the real seal, canonical identities and SQLite store.

The inventory enumeration covers the real host scripts and one local source fixture.
No model, container, evaluator or production runner process is launched.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import procontract_canonical as canonical
import procontract_rsi as rsi
import procontract_store as store
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_canonical_host as canonical_fixtures


class StudyHostTest(unittest.TestCase):
    args = canonical_fixtures.CanonicalHostTest.args
    make_host = canonical_fixtures.CanonicalHostTest.make_host
    cached = canonical_fixtures.CanonicalHostTest.cached
    candidate = canonical_fixtures.CanonicalHostTest.candidate

    def setUp(self):
        canonical_fixtures.CanonicalHostTest.setUp(self)
        self.legacy = self.host
        self.sealed_source = self.root / "source-fixture.py"
        self.sealed_source.write_text("# frozen runtime source fixture\n")
        paths = {path.absolute() for path in study.SCRIPTS.glob("*.py")} | {
            self.sealed_source
        }
        self.enterContext(
            mock.patch.object(study, "mandatory_paths", return_value=paths)
        )
        self.instances = self.root / "instances.txt"
        self.instances.write_text(self.task + "\n")
        self.limits = {
            "task_launches": 6,
            "learning_launches": 8,
            "allocated_seconds": 180000,
        }

    def initialize_study(self, name="study-campaign"):
        camp = self.root / name
        flags = [
            "--instances",
            str(self.instances),
            "--batch",
            "1",
            "--stream-mode",
            "guarded",
            "--release-every",
            "1",
            "--task-attempts",
            "1",
            "--research-image",
            "sha256:" + "a" * 64,
            "--canonical-registry",
            str(self.registry_path),
            "--canonical-registry-sha256",
            self.registry_sha,
            "--canonical-pins-sha256",
            self.descriptor["pins_sha256"],
            "--study-task-launches",
            "6",
            "--study-learning-launches",
            "8",
            "--study-allocated-secs",
            "180000",
        ]
        real_run = rsi.subprocess.run

        def pinned_head(command, **kwargs):
            if command == ["git", "-C", self.data["programbench"], "rev-parse", "HEAD"]:
                return rsi.subprocess.CompletedProcess(
                    command, 0, stdout=self.data["programbench_head"] + "\n"
                )
            return real_run(command, **kwargs)

        with (
            mock.patch.object(sys, "argv", [*self.args(camp), *flags]),
            mock.patch.object(rsi.subprocess, "run", side_effect=pinned_head),
            mock.patch("sys.stdout"),
        ):
            rsi.main()
        self.host = rsi.Host(camp)
        self.parent = self.host.incumbent()
        return self.host

    def test_init_seals_then_provisions_zero_budget_before_writing_campaign(self):
        calls = []
        real_freeze, real_initialize = study.freeze, budget.initialize

        def freeze(camp, terms, limits):
            self.assertFalse((camp / "campaign.json").exists())
            self.assertNotIn("study", terms)
            self.assertEqual(limits, self.limits)
            calls.append("freeze")
            return real_freeze(camp, terms, limits)

        def initialize(database, identity, limits):
            self.assertTrue((database.parent / "study.json").exists())
            self.assertFalse((database.parent / "campaign.json").exists())
            calls.append("initialize")
            return real_initialize(database, identity, limits)

        with (
            mock.patch.object(study, "freeze", side_effect=freeze),
            mock.patch.object(budget, "initialize", side_effect=initialize),
        ):
            host = self.initialize_study()
        descriptor = json.loads((host.camp / "campaign.json").read_text())["study"]
        manifest = study.verify(host.camp, host.terms, runner=host.runner)
        self.assertEqual(
            (calls, host.terms["study"], manifest["limits"]),
            (["freeze", "initialize"], descriptor, self.limits),
        )
        self.assertEqual(
            budget.status(
                host.camp / "study-budget.sqlite",
                descriptor["manifest_sha256"],
                self.limits,
            )["reserved"],
            {"task_launches": 0, "learning_launches": 0, "allocated_seconds": 0},
        )
        self.assertEqual(
            host.contract("campaign")["bindings"]["terms_hash"],
            store.digest("terms", host.terms),
        )

    def test_partial_study_limits_fail_before_freeze_or_external_initialization(self):
        flags = [
            ("--study-task-launches", "6"),
            ("--study-learning-launches", "8"),
            ("--study-allocated-secs", "180000"),
        ]
        for mask in range(1, 7):
            with self.subTest(mask=mask):
                camp = self.root / f"partial-{mask}"
                extra = [
                    value
                    for i, pair in enumerate(flags)
                    if mask & (1 << i)
                    for value in pair
                ]
                with (
                    mock.patch.object(sys, "argv", [*self.args(camp), *extra]),
                    mock.patch.object(study, "freeze") as freeze,
                    mock.patch.object(budget, "initialize") as initialize,
                    mock.patch.object(
                        rsi.subprocess,
                        "run",
                        side_effect=AssertionError("external call"),
                    ),
                    self.assertRaisesRegex(SystemExit, "study limits require"),
                ):
                    rsi.main()
                freeze.assert_not_called()
                initialize.assert_not_called()
                self.assertFalse((camp / "campaign.json").exists())

    def test_existing_campaign_cannot_be_retrofitted_and_legacy_does_not_provision(
        self,
    ):
        with (
            mock.patch.object(study, "verify") as verify,
            mock.patch.object(budget, "initialize") as initialize,
        ):
            rsi.Host(self.legacy.camp)
        verify.assert_not_called()
        initialize.assert_not_called()
        self.assertFalse((self.legacy.camp / "study-budget.sqlite").exists())
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    *self.args(self.legacy.camp),
                    "--study-task-launches",
                    "6",
                    "--study-learning-launches",
                    "8",
                    "--study-allocated-secs",
                    "180000",
                ],
            ),
            mock.patch.object(study, "freeze") as freeze,
            self.assertRaisesRegex(SystemExit, "already holds a campaign"),
        ):
            rsi.main()
        freeze.assert_not_called()

    def test_constructor_rejects_drift_before_canonical_factory_or_store_access(self):
        host = self.initialize_study()
        self.sealed_source.write_text("# changed runtime source\n")
        with (
            mock.patch.object(canonical, "CanonicalProgramBench") as factory,
            mock.patch.object(store, "contract") as contract,
            self.assertRaisesRegex(ValueError, "inventory changed"),
        ):
            rsi.Host(host.camp)
        factory.assert_not_called()
        contract.assert_not_called()

    def test_removed_declaration_cannot_bypass_a_remaining_study_marker(self):
        host = self.initialize_study()
        terms = {key: value for key, value in host.terms.items() if key != "study"}
        (host.camp / "campaign.json").write_text(json.dumps(terms))
        with mock.patch.object(canonical, "CanonicalProgramBench") as factory:
            with self.assertRaisesRegex(ValueError, "study descriptor"):
                rsi.Host(host.camp)
        factory.assert_not_called()

    def test_cached_task_learning_and_supported_adoption_reverify_real_source_seal(
        self,
    ):
        host = self.initialize_study()
        result = self.cached(self.parent, self.task, "stream")
        self.assertEqual(host.measure(self.parent, self.task, "stream"), result)
        candidate = self.candidate()
        for task in host.terms["pools"]["confirm"]:
            self.cached(self.parent, task, "confirm", resolved=1)
            self.cached(candidate, task, "confirm", resolved=2)
        self.assertEqual(
            host.confirm(candidate, self.parent),
            "confirmed; awaiting the principal's adoption",
        )
        adoption = f"adoption.{candidate[:16]}"
        before = (host.incumbent(), host.contract(adoption), store.events(host.store))
        self.sealed_source.write_text(
            "# source drift after valid task and confirmation receipts\n"
        )
        with mock.patch.object(host.adapter, "run_and_label") as paid:
            for operation in (
                lambda: host.measure(self.parent, self.task, "stream"),
                lambda: host.run_agent(
                    self.root / "learning", "research", self.parent, "research.md", 3600
                ),
                lambda: host.adopt(candidate),
            ):
                with self.assertRaisesRegex(ValueError, "inventory changed"):
                    operation()
            paid.assert_not_called()
        self.assertEqual(
            (host.incumbent(), host.contract(adoption), store.events(host.store)),
            before,
        )

    def test_learning_carries_study_only_into_prepare_and_does_not_charge_budget(self):
        host = self.initialize_study()
        root = host.stage_research(self.parent, 1)
        calls = []
        environments = []
        before_bytecode = rsi.os.environ.get("PYTHONDONTWRITEBYTECODE")
        real_run = rsi.subprocess.run

        def runner(command, **kwargs):
            if command[: len(host.runner)] != host.runner:
                return real_run(command, **kwargs)
            calls.append(command)
            environments.append(kwargs["env"])
            run_dir = Path(command[command.index("--run-dir") + 1])
            run_dir.mkdir(exist_ok=True)
            if command[len(host.runner)] == "prepare":
                (run_dir / "workspace").mkdir()
                (run_dir / "manifest.json").write_text(
                    json.dumps({"instructions": "research.md"})
                )
            else:
                (run_dir / "run.json").write_text(
                    json.dumps({"turn_statuses": ["completed"]})
                )
            return rsi.subprocess.CompletedProcess(command, 0)

        with mock.patch.object(rsi.subprocess, "run", side_effect=runner):
            host.run_agent(root, "research-1", self.parent, "research.md", 3600)
        prepare, run = calls
        descriptor = host.terms["study"]
        self.assertEqual(
            (
                prepare[prepare.index("--study-manifest") + 1],
                prepare[prepare.index("--study-sha256") + 1],
            ),
            (descriptor["manifest_path"], descriptor["manifest_sha256"]),
        )
        self.assertNotIn("--study-manifest", run)
        self.assertNotIn("--study-sha256", run)
        self.assertEqual(
            [env["PYTHONDONTWRITEBYTECODE"] for env in environments], ["1", "1"]
        )
        self.assertFalse(any(env is rsi.os.environ for env in environments))
        self.assertEqual(rsi.os.environ.get("PYTHONDONTWRITEBYTECODE"), before_bytecode)
        self.assertEqual(
            budget.status(
                host.camp / "study-budget.sqlite",
                descriptor["manifest_sha256"],
                self.limits,
            )["reserved"],
            {"task_launches": 0, "learning_launches": 0, "allocated_seconds": 0},
        )


if __name__ == "__main__":
    unittest.main()
