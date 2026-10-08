"""Real runner dispatch, seal and SQLite budget; fake AppServer/container transport only.

Inventory enumeration is the StudyHost fixture's real scripts plus explicitly added runtime
files. Verification, registered versions, generated configuration and reservations are real.
"""

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
from types import SimpleNamespace
import unittest
from unittest import mock
from pathlib import Path

import procontract_benchmark_runner as runner
import procontract_harness_program as harness
import procontract_study as study
import procontract_study_budget as budget
import procontract_store as store
import test_procontract_study_host as fixtures


class StudyLaunchTest(unittest.TestCase):
    args = fixtures.StudyHostTest.args
    make_host = fixtures.StudyHostTest.make_host
    cached = fixtures.StudyHostTest.cached
    initialize_study = fixtures.StudyHostTest.initialize_study

    def setUp(self):
        fixtures.StudyHostTest.setUp(self)
        sidecar = self.root / "codex-code-mode-host"
        sidecar.write_text("fixture tool host, never executed")
        sidecar.chmod(0o755)
        study.mandatory_paths.return_value.update(
            {
                self.root / "codex",
                sidecar,
                Path(store.store_bin()).resolve(),
                self.root / "prompt.txt",
                self.registry_path,
                self.pins_path,
            }
        )
        self.initialize_study()
        source = self.root / "producer"
        shutil.copytree(self.host.version_dir(self.parent) / "bundle", source)
        (source / harness.PROGRAM_FILE).write_text(
            json.dumps({"schema": 1, "when": {"always": False}})
        )
        self.producer = self.host.register(
            source, self.parent, self.parent, "Launch-boundary fixture."
        )
        self.database = self.host.camp / "study-budget.sqlite"

    def balance(self):
        return budget.status(
            self.database, self.host.terms["study"]["manifest_sha256"], self.limits
        )

    def preparation(self, role="executor.md", name="task", run_dir=None):
        task = role == "executor.md"
        source = self.host.camp / "inputs" / name
        source.mkdir(parents=True)
        prompt = Path(self.host.terms["task_prompt"])
        if not task:
            prompt = source / "prompt.md"
            prompt.write_text("A learning-role transport fixture.")
        return argparse.Namespace(
            run_dir=run_dir or self.host.camp / "launches" / name,
            codex_bin=Path(self.host.terms["codex_bin"]),
            arm="on",
            instance=self.task if task else name,
            image=self.data["tasks"][self.task]["image"]
            if task
            else self.host.terms["research_image"],
            policy=self.host.version_dir(self.producer) / "bundle",
            instructions=role,
            prompt=prompt,
            workspace_from=None if task else source,
            no_reference=not task,
            model=self.host.terms["model"],
            effort=self.host.terms["effort"],
            study_manifest=Path(self.host.terms["study"]["manifest_path"]),
            study_sha256=self.host.terms["study"]["manifest_sha256"],
            deadline_secs=self.host.terms["task_deadline_secs"]
            if task
            else self.host.terms[
                "research_deadline_secs"
                if role == "research.md"
                else "analysis_deadline_secs"
            ],
            delivery_reserve_secs=0,
            stop_after_issue=False,
        )

    @contextlib.contextmanager
    def transport(self, *, fail_start=False):
        real_run = runner.subprocess.run
        clock, opened = [0.0], []

        def process(command, **kwargs):
            if command[0] == "docker":
                if command[1:3] == ["image", "inspect"]:
                    return runner.subprocess.CompletedProcess(command, 0)
                if command[1] != "run" or "sh" not in command:
                    raise AssertionError(f"unexpected container transport: {command}")
                mounts = [
                    command[i + 1] for i, value in enumerate(command) if value == "-v"
                ]
                destination = Path(
                    next(value[:-5] for value in mounts if value.endswith(":/out"))
                )
                incoming = next(
                    (value[:-7] for value in mounts if value.endswith(":/in:ro")), None
                )
                if incoming is not None:
                    shutil.copytree(incoming, destination, dirs_exist_ok=True)
                return runner.subprocess.CompletedProcess(command, 0)
            if command[0] != store.store_bin():
                raise AssertionError(f"unexpected external process: {command}")
            return real_run(command, **kwargs)

        def event(method, status):
            return {
                "method": method,
                "params": {
                    "threadId": "fixture-thread",
                    "turn": {"id": "turn", "status": status},
                },
            }

        def app_server(*args, **kwargs):
            directory = kwargs["cwd"]
            receipt = json.loads((directory / "study-launch.json").read_text())
            opened.append((directory, receipt, self.balance()))
            if fail_start:
                raise RuntimeError("fixture AppServer failed after authorization")
            server = mock.Mock()
            clock[0] = 0.0

            def respond(method, params, handle, timeout=None):
                if method == "thread/start":
                    return {"thread": {"id": "fixture-thread"}}
                if method == "turn/start":
                    handle(event("turn/started", "inProgress"))
                return {}

            def message(timeout):
                clock[0] = 6.0
                return event("turn/completed", "completed")

            server.request.side_effect = respond
            server.messages.get.side_effect = message
            return server

        safe_os = SimpleNamespace(
            **{**vars(os), "environ": {**os.environ, "OPENAI_API_KEY": "fixture"}}
        )
        with (
            mock.patch.object(runner.subprocess, "run", side_effect=process),
            mock.patch.object(runner, "AppServer", side_effect=app_server),
            mock.patch.object(runner, "os", safe_os),
            mock.patch.object(runner, "current_key", return_value="fixture"),
            mock.patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(
                runner,
                "read_status",
                return_value={"phase": "supported", "resting": True},
            ),
            mock.patch.object(runner, "rollout_costs", return_value={}),
            mock.patch.object(runner, "readable"),
            mock.patch("sys.stdout"),
        ):
            yield opened

    def test_task_and_three_learning_roles_reserve_before_app_server(self):
        with self.transport() as opened:
            for role in ("executor.md", "analyst.md", "challenger.md", "research.md"):
                args = self.preparation(role, role[:-3])
                runner.prepare(args)
                manifest = json.loads((args.run_dir / "manifest.json").read_text())
                self.assertEqual(
                    (manifest["study"], manifest["study_version"]),
                    (self.host.terms["study"], self.producer),
                )
                runner.run(args)
                summary = json.loads((args.run_dir / "run.json").read_text())
                self.assertEqual(summary["study_launch"], opened[-1][1])
                self.assertEqual(
                    (
                        summary["study_launch"]["kind"],
                        summary["study_launch"]["deadline_secs"],
                    ),
                    (
                        "task" if role == "executor.md" else "learning",
                        args.deadline_secs,
                    ),
                )
        self.assertEqual(len(opened), 4)
        self.assertEqual(
            self.balance()["reserved"],
            {"task_launches": 1, "learning_launches": 3, "allocated_seconds": 28800},
        )

    def test_unknown_app_server_start_consumes_one_claim_and_cannot_reauthorize(self):
        args = self.preparation()
        with self.transport(fail_start=True) as opened:
            runner.prepare(args)
            with self.assertRaisesRegex(RuntimeError, "failed after authorization"):
                runner.run(args)
            before = self.balance()
            with self.assertRaises(budget.AlreadyClaimed):
                runner.run(args)
        self.assertEqual((len(opened), self.balance()), (1, before))

    def test_runtime_and_prepared_policy_drift_refuse_before_reservation_or_server(
        self,
    ):
        cases = (
            "model",
            "image",
            "deadline",
            "config",
            "settings",
            "environments",
            "prepared_role",
            "prepared_harness",
            "source_role",
            "source",
            "missing_study",
        )
        with self.transport() as opened:
            before = self.balance()
            for name in cases:
                with self.subTest(name=name):
                    args = self.preparation(name=name)
                    runner.prepare(args)
                    path, original = None, None
                    if name in ("model", "image", "missing_study"):
                        path = args.run_dir / "manifest.json"
                        original = path.read_bytes()
                        manifest = json.loads(original)
                        if name == "missing_study":
                            manifest.pop("study")
                        else:
                            manifest[name] = (
                                "gpt-6-astra"
                                if name == "model"
                                else "sha256:" + "0" * 64
                            )
                        path.write_text(json.dumps(manifest))
                    elif name == "deadline":
                        args.deadline_secs += 1
                    else:
                        path = {
                            "config": args.run_dir / "codex-home/config.toml",
                            "settings": args.run_dir
                            / "codex-home/pro_contract/settings.json",
                            "environments": args.run_dir
                            / "codex-home/environments.toml",
                            "prepared_role": args.run_dir / "policy/executor.md",
                            "prepared_harness": args.run_dir / "policy/harness.json",
                            "source_role": args.policy / "analyst.md",
                            "source": self.sealed_source,
                        }[name]
                        original = path.read_bytes()
                        path.write_bytes(original + b"\nchanged")
                    try:
                        with self.assertRaises((RuntimeError, ValueError)):
                            runner.run(args)
                        self.assertEqual((opened, self.balance()), ([], before))
                    finally:
                        if path is not None:
                            path.write_bytes(original)

    def test_sealed_bundle_cannot_escape_gate_by_omitting_flags_or_changing_output_root(
        self,
    ):
        for declared in (False, True):
            with self.subTest(declared=declared):
                args = self.preparation(
                    name=f"outside-{declared}",
                    run_dir=self.root / f"outside-{declared}",
                )
                if not declared:
                    args.study_manifest = args.study_sha256 = None
                with (
                    mock.patch.object(
                        runner,
                        "harness_ready",
                        side_effect=AssertionError("gate ran too late"),
                    ),
                    mock.patch.object(
                        runner.subprocess,
                        "run",
                        side_effect=AssertionError("container preparation"),
                    ),
                    self.assertRaises((RuntimeError, ValueError)),
                ):
                    runner.prepare(args)
                self.assertFalse(args.run_dir.exists())

    def test_host_completed_cache_does_not_recharge_the_runner_budget(self):
        run_dir = (
            self.host.camp
            / "runs"
            / f"stream-{self.producer[:12]}-{self.task}"
            / "attempt-1"
        )
        args = self.preparation(run_dir=run_dir)
        with self.transport() as opened:
            runner.prepare(args)
            runner.run(args)
            actual = {
                name: (run_dir / name).read_bytes()
                for name in ("manifest.json", "run.json")
            }
            result = self.cached(self.producer, self.task, "stream")
            for name, raw in actual.items():
                (run_dir / name).write_bytes(raw)
            before = self.balance()
            with mock.patch.object(
                self.host.adapter,
                "run_and_label",
                side_effect=AssertionError("cached inference rerun"),
            ):
                self.assertEqual(
                    self.host.measure(self.producer, self.task, "stream"), result
                )
                self.assertEqual(
                    self.host.measure(self.producer, self.task, "stream"), result
                )
            self.assertEqual((len(opened), self.balance()), (1, before))

    def test_crlf_generated_configuration_is_accepted_and_bound_by_actual_bytes(self):
        args = self.preparation("research.md", "crlf-research")
        paths = [
            args.run_dir / "codex-home" / name
            for name in (
                "config.toml",
                "environments.toml",
                "pro_contract/settings.json",
            )
        ]
        with self.transport() as opened:
            runner.prepare(args)
            expected = {}
            for path in paths:
                raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                actual = raw.replace(b"\n", b"\r\n")
                path.write_bytes(actual)
                expected[str(path.relative_to(args.run_dir))] = hashlib.sha256(
                    actual
                ).hexdigest()
            runner.run(args)
            self.assertEqual((len(opened), opened[0][1]["kind"]), (1, "learning"))
        with contextlib.closing(
            sqlite3.connect(self.database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as database:
            row = database.execute(
                "SELECT identity_json FROM reservations WHERE key = ?",
                (str(args.run_dir.relative_to(self.host.camp)),),
            ).fetchone()
        self.assertEqual(json.loads(row[0])["configuration"], expected)


if __name__ == "__main__":
    unittest.main()
