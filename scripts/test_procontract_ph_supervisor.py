"""Synthetic transport with real Host/kernel state; this is not benchmark RSI evidence."""

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import procontract_ph_audit as audits
import procontract_ph_supervisor as supervisor
import procontract_rsi as rsi
import procontract_store as store
import procontract_study as study
import procontract_study_budget as budget
import test_procontract_guarded_stream as guarded_fixtures


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def plan_terms(camp):
    plan = camp.parent / "plan.json"
    write(
        plan,
        {
            "schema": 1,
            "protocol": supervisor.PROTOCOL,
            "campaign": str(camp),
            "source_sha256": supervisor.digest(Path(supervisor.__file__)),
            "max_phases": 3,
        },
    )
    return {
        "ph_supervisor": {
            "plan_path": str(plan),
            "plan_sha256": supervisor.digest(plan),
        },
        "model": "gpt-5.6-luna",
        "effort": "max",
        "submission_policy": "rust-preinstalled-v1",
        "proposal_kind": "all",
        "adoption": "presumed",
        "task_deadline_secs": 18000,
        "analysis_deadline_secs": 3600,
        "research_deadline_secs": 3600,
        "confirmation_exposure_scope": "prospective_lineage",
        "mutable": sorted(supervisor.PH),
        "checkpoint": {"fixture": True},
        "canonical": {"fixture": True},
        "budgets": {"task_attempts": 1},
        "stream": {
            "mode": "guarded",
            "method_confirmation": "defer",
            "batch": 1,
            "release_every": 1,
            "order": list("abcd"),
        },
        "pools": {"confirm": list("efgh")},
        "gates": {
            "confirm_tasks": 4,
            "confirm_min_wins": 3,
            "confirm_min_delta": 0.000001,
        },
    }


class PlanTest(unittest.TestCase):
    def test_plan_source_and_fixed_scope_are_checked_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            camp = Path(directory) / "campaign"
            terms = plan_terms(camp)
            self.assertEqual(supervisor.validate_plan(camp, terms)["max_phases"], 3)
            for key, value in (
                ("model", "gpt-6-astra"),
                ("mutable", ["analyst.md"]),
                ("submission_policy", None),
            ):
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    supervisor.validate_plan(camp, {**terms, key: value})
            changed = copy.deepcopy(terms)
            changed["stream"]["order"] = list("abc")
            with self.assertRaises(RuntimeError):
                supervisor.validate_plan(camp, changed)
            changed = copy.deepcopy(terms)
            changed["gates"]["confirm_min_delta"] = 0
            with self.assertRaises(RuntimeError):
                supervisor.validate_plan(camp, changed)
            path = Path(terms["ph_supervisor"]["plan_path"])
            document = supervisor.document(path)
            document["source_sha256"] = "0" * 64
            write(path, document)
            terms["ph_supervisor"]["plan_sha256"] = supervisor.digest(path)
            with self.assertRaisesRegex(RuntimeError, "source"):
                supervisor.validate_plan(camp, terms)


class RoutingTest(unittest.TestCase):
    make_host = guarded_fixtures.GuardedStreamTest.make_host

    def episode(self, *, quality="behavior", no_change=None, after_phase=None):
        host = self.make_host(quality=quality, mutable=sorted(supervisor.PH))
        host.terms["pools"]["confirm"] = host.terms["pools"]["confirm"][:4]
        host.terms["gates"].update(
            confirm_tasks=4, confirm_min_wins=3, confirm_min_delta=0.000001
        )
        verifier = Path(study.__file__).resolve()
        seal = {
            "limits": {
                "task_launches": 12,
                "learning_launches": 21,
                "allocated_seconds": 291600,
            },
            "files": {
                str(verifier): {"sha256": supervisor.digest(verifier)},
                str(Path(supervisor.__file__).resolve()): {},
            },
        }
        plan = host.camp.parent / "plan.json"
        write(plan, {"synthetic_transport_fixture": True})
        seal["files"][str(plan)] = {}
        write(host.camp / "study.json", seal)
        host.terms.update(
            study={
                "manifest_path": str(host.camp / "study.json"),
                "manifest_sha256": supervisor.digest(host.camp / "study.json"),
            },
            ph_supervisor={
                "plan_path": str(plan),
                "plan_sha256": supervisor.digest(plan),
            },
        )
        write(host.camp / "campaign.json", host.terms)
        args = argparse.Namespace(
            camp=host.camp,
            plan=plan,
            plan_sha256=supervisor.digest(plan),
            study_sha256=host.terms["study"]["manifest_sha256"],
        )
        controller, calls = supervisor.Supervisor(args), []
        real_research = host.research

        def research(parent, phase):
            delivery = real_research(parent, phase)
            if phase == no_change:
                shutil.rmtree(delivery / "policy")
                shutil.copytree(
                    host.version_dir(parent) / "bundle", delivery / "policy"
                )
            return delivery

        def command(phase):
            calls.append(phase)
            host.stream_step()
            if after_phase:
                after_phase(host, phase)

        real_task = audits.Audit.task

        def toy_task(audit, version, task, purpose):
            path = (
                host.camp
                / "runs"
                / f"{purpose}-{version[:12]}-{task}"
                / "attempt-1/manifest.json"
            )
            manifest = supervisor.document(path)
            manifest["instance"] = task
            write(path, manifest)
            result = real_task(audit, version, task, purpose)
            result["label"]["outcome"].update(
                passed=round(result["pass_rate"] * 100), counted=100
            )
            return result

        # The toy peer lacks native/study launch receipts. Their audits are covered below;
        # keep real phase routing, research claims, qualification and kernel adoption here.
        with (
            mock.patch.object(supervisor, "validate_plan"),
            mock.patch.object(study, "verify", return_value=seal),
            mock.patch.object(rsi, "Host", return_value=host),
            mock.patch.object(
                audits.Audit,
                "paid",
                return_value={"reserved": dict.fromkeys(seal["limits"], 0)},
            ),
            mock.patch.object(
                audits.Audit, "runtime", return_value={"synthetic": True}
            ),
            mock.patch.object(audits.Audit, "task", new=toy_task),
            mock.patch.object(host, "research", side_effect=research),
            mock.patch.object(controller, "command", side_effect=command),
        ):
            terminal = controller.run()
        return host, controller, terminal, calls

    def test_three_phases_close_with_changed_successor_and_never_run_buffer(self):
        host, controller, result, calls = self.episode()
        self.assertEqual(
            (result["outcome"], calls),
            ("adopted_continuation_qualified_successor", [1, 2, 3]),
        )
        adopted = result["adopted_candidate"]
        child = result["phases"][-1]["research"]["candidate"]
        self.assertEqual(
            host.versions()[child]["lineage"],
            {"parent": adopted, "proposed_by": adopted},
        )
        self.assertEqual(len(host.batches()), 3)
        self.assertIsNone(host.contract(f"adoption.{child[:16]}"))
        with self.assertRaises(FileExistsError):
            controller.run()

    def test_initial_unchanged_delivery_stops_without_fishing(self):
        host, _, result, calls = self.episode(no_change=1)
        self.assertEqual(
            (result["outcome"], calls), ("initial_no_candidate_or_unqualified", [1])
        )
        self.assertEqual(len(host.versions()), 1)

    def test_rejected_confirmation_stops_without_next_serve(self):
        host, _, result, calls = self.episode(quality="tie")
        self.assertEqual(
            (result["outcome"], calls), ("probe_rejected_or_inconclusive", [1, 2])
        )
        self.assertEqual(len(host.batches()), 2)

    def test_altered_confirmation_cannot_authorize_continuation_after_kernel_adoption(
        self,
    ):
        def change(host, phase):
            if phase == 2:
                candidate = host.batches()[1]["version"]
                task = host.terms["pools"]["confirm"][0]
                path = (
                    host.camp
                    / "runs"
                    / f"confirm-{candidate[:12]}-{task}"
                    / "result.json"
                )
                result = supervisor.document(path)
                result["pass_rate"] = 0.9
                write(path, result)

        _, _, result, calls = self.episode(after_phase=change)
        self.assertEqual(
            (result["outcome"], calls), ("stopped_invalid_or_unknown", [1, 2])
        )
        self.assertIn("bind recomputed confirmation", result["error"]["message"])

    def test_unexpected_assignment_stops_after_first_call(self):
        def change(host, phase):
            if phase == 1:
                host.record("assignment", {"batch": 99, "phase": "method_probe"})

        _, _, result, calls = self.episode(after_phase=change)
        self.assertEqual(
            (result["outcome"], calls), ("stopped_invalid_or_unknown", [1])
        )

    def test_discharged_unchanged_continuation_is_not_a_successor(self):
        _, _, result, calls = self.episode(no_change=3)
        self.assertEqual(
            (result["outcome"], calls),
            ("adopted_research_qualified_no_change", [1, 2, 3]),
        )
        self.assertIsNone(result["phases"][-1]["research"]["candidate"])

    def test_wrong_continuation_research_parent_stops_as_unqualified(self):
        def change(host, phase):
            if phase == 3:
                path = host.camp / "research/step-3/launch-claim.json"
                claim = supervisor.document(path)
                claim["identity"]["parent"] = host.batches()[0]["version"]
                write(path, claim)

        _, _, result, calls = self.episode(after_phase=change)
        self.assertEqual(
            (result["outcome"], calls),
            ("adopted_continuation_research_failed_or_unqualified", [1, 2, 3]),
        )
        self.assertIn("error", result)


class PaidReceiptTest(unittest.TestCase):
    @unittest.skipUnless(supervisor.sys.platform == "linux", "Linux group containment")
    def test_live_child_is_always_one_phase_and_nonzero_exit_is_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(camp=Path(directory), study_sha256="a" * 64)
            controller = supervisor.Supervisor(args)
            controller.root.mkdir()
            process = mock.Mock(pid=999999)
            process.wait.return_value = 7
            with (
                mock.patch.object(
                    supervisor.subprocess, "Popen", return_value=process
                ) as launch,
                mock.patch.object(supervisor.os, "getpgid", return_value=process.pid),
                mock.patch.object(supervisor.os, "getsid", return_value=process.pid),
                mock.patch.object(
                    supervisor.os,
                    "waitid",
                    return_value=argparse.Namespace(si_code=os.CLD_EXITED, si_status=7),
                ),
                mock.patch.object(supervisor.os, "killpg"),
                mock.patch.object(supervisor.time, "sleep"),
            ):
                with self.assertRaisesRegex(RuntimeError, "no retry"):
                    controller.command(1)
            command = launch.call_args.args[0]
            self.assertEqual(
                command[1:],
                [
                    str(Path(supervisor.__file__).with_name("procontract_live.py")),
                    "stream",
                    "--camp",
                    str(args.camp),
                    "--study-sha256",
                    args.study_sha256,
                    "--count",
                    "1",
                ],
            )
            self.assertEqual(launch.call_count, 1)
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
            self.assertEqual(
                supervisor.document(controller.root / "phase-1/exit.json")[
                    "returncode"
                ],
                7,
            )

    def test_real_budget_unknown_claim_or_configuration_drift_is_never_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            camp = Path(directory)
            limits = {
                "task_launches": 12,
                "learning_launches": 21,
                "allocated_seconds": 291600,
            }
            terms = {"study": {"manifest_sha256": "a" * 64}}
            host = mock.Mock(camp=camp, terms=terms)
            audit = audits.Audit(host, {"limits": limits})
            database = camp / "study-budget.sqlite"
            budget.initialize(database, "a" * 64, limits)
            run = camp / "runs/task/attempt-1"
            manifest = {
                "study_version": "v",
                "instructions": "executor.md",
                "instance": "t",
            }
            write(run / "manifest.json", manifest)
            configuration = {}
            for name in (
                "codex-home/config.toml",
                "codex-home/environments.toml",
                "codex-home/pro_contract/settings.json",
            ):
                path = run / name
                write(path, {"fixture": name})
                configuration[name] = supervisor.digest(path)
            identity = {
                "version": "v",
                "role": "executor.md",
                "instance": "t",
                "manifest_sha256": supervisor.digest(run / "manifest.json"),
                "configuration": configuration,
            }
            receipt = budget.reserve(
                database,
                "a" * 64,
                str(run.relative_to(camp)),
                "task",
                18000,
                limits,
                identity,
            )
            with self.assertRaisesRegex(RuntimeError, "missing"):
                audit.paid()
            write(run / "study-launch.json", receipt)
            write(
                run / "run.json",
                {"study_launch": receipt, "turn_statuses": ["completed"]},
            )
            self.assertEqual(
                audit.paid()["reserved"],
                {
                    "task_launches": 1,
                    "learning_launches": 0,
                    "allocated_seconds": 18000,
                },
            )
            deadline = {
                "study_launch": receipt,
                "turn_statuses": [],
                "deadline_hit": True,
                "native_process_exit": {
                    "status": "exited",
                    "returncode": -15,
                    "shutdown": "terminate",
                },
            }
            write(run / "run.json", deadline)
            self.assertEqual(audit.paid()["reserved"]["task_launches"], 1)
            write(
                run / "run.json",
                {
                    **deadline,
                    "native_process_exit": {
                        "status": "unknown",
                        "returncode": None,
                        "shutdown": "kill",
                    },
                },
            )
            with self.assertRaisesRegex(RuntimeError, "exit remains unknown"):
                audit.paid()
            write(run / "run.json", {**deadline, "deadline_hit": False})
            with self.assertRaisesRegex(RuntimeError, "unknown paid launch"):
                audit.paid()
            write(run / "run.json", deadline)
            failed = camp / "insight/1/analyst-1/run"
            write(failed / "manifest.json", {**manifest, "instructions": "analyst.md"})
            for name in configuration:
                (failed / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / name, failed / name)
            failed_identity = {
                **identity,
                "role": "analyst.md",
                "manifest_sha256": supervisor.digest(failed / "manifest.json"),
            }
            failed_receipt = budget.reserve(
                database,
                "a" * 64,
                str(failed.relative_to(camp)),
                "learning",
                3600,
                limits,
                failed_identity,
            )
            write(failed / "study-launch.json", failed_receipt)
            write(
                failed / "run.json",
                {
                    "study_launch": failed_receipt,
                    "runner_error": "known failed native attempt",
                },
            )
            claim = {
                "schema": 1,
                "identity": {"parent": "v", "instructions": "analyst.md"},
            }
            write(failed.parent / "launch-claim.json", claim)
            write(
                failed.parent / "launch-exit.json",
                {"claim": store.digest("learning_launch", claim), "returncode": 1},
            )
            self.assertEqual(
                audit.paid()["reserved"],
                {
                    "task_launches": 1,
                    "learning_launches": 1,
                    "allocated_seconds": 21600,
                },
            )
            write(
                failed / "run.json",
                {"study_launch": failed_receipt, "turn_statuses": []},
            )
            with self.assertRaisesRegex(RuntimeError, "unknown paid launch"):
                audit.paid()
            write(
                failed / "run.json",
                {
                    "study_launch": failed_receipt,
                    "runner_error": "known failed native attempt",
                },
            )
            write(run / "codex-home/config.toml", {"changed": True})
            with self.assertRaisesRegex(RuntimeError, "configuration"):
                audit.paid()
            self.assertEqual(
                budget.status(database, "a" * 64, limits)["reserved"]["task_launches"],
                1,
            )

    def test_child_exception_never_retries_and_partial_claim_blocks_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                camp=Path(directory), study_sha256="a" * 64, plan_sha256="b" * 64
            )
            controller = supervisor.Supervisor(args)
            with mock.patch.object(
                controller, "execute", side_effect=RuntimeError("unknown child")
            ) as execute:
                result = controller.run()
                execute.assert_called_once()
            self.assertEqual(result["outcome"], "stopped_invalid_or_unknown")
            with self.assertRaises(FileExistsError):
                supervisor.Supervisor(args).run()


if __name__ == "__main__":
    unittest.main()
