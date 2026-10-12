"""Operator pin and fresh-authorization boundaries, without inference or Docker."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import procontract_online_plan as plans


class PlanTests(unittest.TestCase):
    def test_parent_digest_alone_cannot_silently_prepare_a_fresh_study(self):
        with self.assertRaisesRegex(ValueError, "both parent"):
            plans.prepare(None, None, None, None, parent_sha256="a" * 64)

    def test_cli_does_not_silently_drop_paired_comparison(self):
        import procontract_online_pilot as pilot

        with (
            mock.patch("sys.argv", ["pilot", "prepare", "--comparison", "paired"]),
            mock.patch.object(plans, "prepare", return_value={}) as prepare,
            mock.patch("builtins.print"),
        ):
            pilot.main()
        self.assertEqual(
            prepare.call_args.kwargs,
            {"comparison": "paired", "selection_mode": "deployment"},
        )

    def test_control_cannot_request_rsi_coverage(self):
        for comparison in ("vanilla", "contract"):
            with (
                self.subTest(comparison=comparison),
                self.assertRaisesRegex(ValueError, "non-learning controls"),
            ):
                plans.prepare(
                    None,
                    None,
                    None,
                    None,
                    comparison=comparison,
                    selection_mode="coverage",
                )

    def test_task_order_is_independent_of_input_order_and_scores(self):
        tasks = {"c": {"score": 100}, "a": {"score": 0}, "d": {}, "b": {}}
        selected = plans.select_tasks(tasks)
        self.assertEqual(
            plans.select_tasks(dict(reversed(list(tasks.items())))), selected
        )
        self.assertEqual(
            plans.select_tasks({key: {"score": -9} for key in tasks}), selected
        )
        self.assertEqual(len(set(selected)), 3)
        with self.assertRaises(ValueError):
            plans.select_tasks(["a"])

    def test_plan_drift_and_input_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_text("original")
            plan = {
                "root": str(root),
                "protocol": plans.PROTOCOL,
                "selection_mode": "deployment",
                "selection_profile": plans.selection_profile("deployment"),
                "files": {str(source): plans.sha(source)},
            }
            path = root / "online-plan.json"
            plans.publish(path, plan)
            digest = plans.sha(path)
            self.assertEqual(plans.verify(path, digest), plan)
            wrong_mode = {**plan, "selection_mode": "coverage"}
            other = root / "wrong-mode.json"
            plans.publish(other, wrong_mode)
            with self.assertRaisesRegex(ValueError, "invalid pilot identity"):
                plans.verify(other, plans.sha(other))
            source.write_text("changed")
            with self.assertRaisesRegex(ValueError, "input drift"):
                plans.verify(path, digest)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "operator pin"):
                plans.verify(path, digest)

    def test_authorization_cannot_reuse_another_plan_or_change_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "authorization.json"
            limits = {
                "task_launches": 6,
                "learning_launches": 3,
                "allocated_seconds": 108000,
            }
            body = {
                "plan_sha256": "a" * 64,
                "authorized": True,
                "user_message": "fixture only",
                "limits": limits,
            }
            path.write_text(json.dumps(body))
            self.assertEqual(
                plans.authorize({"limits": limits}, "a" * 64, path),
                {"path": str(path), "sha256": plans.sha(path)},
            )
            for wrong in (
                {**body, "authorized": False},
                {**body, "plan_sha256": "b" * 64},
                {**body, "user_message": ""},
                {**body, "limits": {**limits, "task_launches": 7}},
            ):
                path.write_text(json.dumps(wrong))
                with self.assertRaises(ValueError):
                    plans.authorize({"limits": limits}, "a" * 64, path)

    def test_preparation_subsets_dependency_inventory_without_changing_rules(self):
        self.prepare_comparison("paired", ["frozen", "adaptive"], 3)

    def test_vanilla_and_contract_controls_have_no_research_budget(self):
        for mode, arms in (
            ("vanilla", ["vanilla"]),
            ("contract", ["vanilla", "frozen"]),
        ):
            with self.subTest(mode=mode):
                self.prepare_comparison(mode, arms, 0)

    def prepare_comparison(self, comparison, arms, research):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "source/scripts"
            scripts.mkdir(parents=True)
            for name in (
                "procontract_online_pilot.py",
                "procontract_canonical.py",
                "procodex_config.py",
            ):
                (scripts / name).write_text("fixture")
            package = root / "package"
            (package / "bin").mkdir(parents=True)
            for name in ("codex", "codex-code-mode-host", "pro-contract-store"):
                (package / "bin" / name).write_text(name)
            release = {
                "source_commit": "native",
                "binaries": {p.name: plans.sha(p) for p in (package / "bin").iterdir()},
            }
            (package / "procodex-release.json").write_text(json.dumps(release))
            tasks = {name: {"image": f"image-{name}"} for name in ("a", "b", "c", "d")}
            policy = {
                "tasks": {t: v["image"] for t, v in tasks.items()},
                "images": {v["image"]: [] for v in tasks.values()},
                "allowed": ["unchanged"],
            }
            policy_path = root / "original-policy.json"
            policy_path.write_text(json.dumps(policy))
            before = policy_path.read_bytes()
            registry_path = root / "registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "tasks": tasks,
                        "dependency_policy": {
                            "path": str(policy_path),
                            "sha256": plans.sha(policy_path),
                        },
                    }
                )
            )
            prompt = root / "prompt"
            prompt.write_text("fixture")
            destination = root / "pilot"

            def freeze(*_args, **_kwargs):
                (destination / "inputs/canonical-pins.json").write_text("{}")

            def git(args, **_kwargs):
                return "" if "status" in args else "controller"

            with (
                mock.patch.object(plans, "SCRIPTS", scripts),
                mock.patch.object(plans.canonical, "configure"),
                mock.patch.object(plans.canonical, "evaluator_env", return_value={}),
                mock.patch.object(plans.subprocess, "run", side_effect=freeze),
                mock.patch.object(plans.subprocess, "check_output", side_effect=git),
            ):
                result = plans.prepare(
                    destination,
                    registry_path,
                    package / "bin/codex",
                    prompt,
                    comparison=comparison,
                )
            subset = json.loads(
                (destination / "inputs/dependency-policy.json").read_text()
            )
            self.assertEqual(set(subset["tasks"]), set(result["tasks"]))
            self.assertEqual(set(subset["images"]), set(subset["tasks"].values()))
            self.assertEqual(subset["allowed"], policy["allowed"])
            self.assertEqual(policy_path.read_bytes(), before)
            sealed = plans.verify(Path(result["plan"]), result["sha256"])
            self.assertTrue(Path(sealed["entrypoint"]).is_relative_to(destination))
            self.assertEqual(
                (sealed["arms"], sealed["limits"]),
                (
                    arms,
                    {
                        "task_launches": 3 * len(arms),
                        "learning_launches": research,
                        "allocated_seconds": 54000 * len(arms),
                    },
                ),
            )

    def test_receipt_publication_is_non_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receipt.json"
            plans.publish(path, {"state": "unknown"})
            with self.assertRaises(FileExistsError):
                plans.publish(path, {"state": "success"})
            self.assertEqual(json.loads(path.read_text()), {"state": "unknown"})


if __name__ == "__main__":
    unittest.main()
