"""Fixture-only assembly tests; canonical validation is delegated, no live evaluators."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import procontract_compliance_adapter as adapter
import procontract_compliance_evidence as evidence
from test_procontract_compliance_evidence import archive
import tarfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def native_events():
    command = dict(
        type="commandExecution", id="c1", command="rustc main.rs", status="inProgress"
    )
    return [
        (True, dict(id=4, method="turn/start", params=dict(threadId="thread"))),
        (
            False,
            dict(
                method="turn/started",
                params=dict(
                    threadId="thread", turn=dict(id="turn", status="inProgress")
                ),
            ),
        ),
        (False, dict(id=4, result=dict(turn=dict(id="turn")))),
        (
            False,
            dict(
                method="item/started",
                params=dict(threadId="thread", turnId="turn", item=command),
            ),
        ),
        (
            False,
            dict(
                method="item/completed",
                params=dict(
                    threadId="thread",
                    turnId="turn",
                    item={
                        **command,
                        "status": "completed",
                        "exitCode": 0,
                        "aggregatedOutput": "HIDDEN OUTPUT",
                    },
                ),
            ),
        ),
        (
            False,
            dict(
                method="turn/completed",
                params=dict(
                    threadId="thread", turn=dict(id="turn", status="completed")
                ),
            ),
        ),
    ]


def capture(events):
    return b"".join(
        (b"> " if outgoing else b"") + json.dumps(value).encode() + b"\n"
        for outgoing, value in events
    )


class NativeCommandsTests(unittest.TestCase):
    def test_complete_root_commands_only_and_no_outputs(self):
        events = native_events()
        events.insert(
            4,
            (
                False,
                dict(
                    method="item/completed",
                    params=dict(
                        threadId="other",
                        turnId="other",
                        item=dict(type="commandExecution", command="NOT EXPORTED"),
                    ),
                ),
            ),
        )
        raw = capture(events)
        for encoded, compressed in ((raw, False), (gzip.compress(raw), True)):
            commands, receipt = adapter.native_commands(
                encoded, compressed=compressed, thread_id="thread"
            )
            self.assertEqual(commands, [dict(command="rustc main.rs", exit_code=0)])
            self.assertEqual(
                receipt,
                dict(
                    scope="observed root command notifications; not complete process/syscall or file-tool capture",
                    thread_id="thread",
                    turn_id="turn",
                    image_views=[],
                    typed_mutations=[],
                    commands=1,
                    pending=0,
                    terminal_status="completed",
                    turns=[dict(id="turn", status="completed")],
                    protocol_sha256=digest(encoded),
                ),
            )

    def test_known_pending_start_is_preserved_not_assumed_success(self):
        events = native_events()
        del events[4]
        commands, receipt = adapter.native_commands(
            capture(events), compressed=False, thread_id="thread"
        )
        self.assertEqual(commands, [dict(command="rustc main.rs", exit_code=None)])
        self.assertEqual(receipt["pending"], 1)

    def test_one_internal_repair_turn_is_scoped_and_retained(self):
        first, repair = native_events(), native_events()
        repair = [repair[index] for index in (1, 3, 4, 5)]
        for _, value in repair:
            params = value["params"]
            if "turn" in params:
                params["turn"]["id"] = "repair"
            if "turnId" in params:
                params["turnId"] = "repair"
        commands, receipt = adapter.native_commands(
            capture(first + repair), compressed=False, thread_id="thread"
        )
        self.assertEqual(commands, [dict(command="rustc main.rs", exit_code=0)] * 2)
        self.assertEqual(
            receipt["turns"],
            [
                dict(id="turn", status="completed"),
                dict(id="repair", status="completed"),
            ],
        )
        # Reused tool IDs are distinct across turns, never overwritten.
        self.assertEqual((receipt["commands"], receipt["pending"]), (2, 0))
        repair_missing_end = first + repair[:-1]
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(
                capture(repair_missing_end), compressed=False, thread_id="thread"
            )
        for extra in (native_events(), repair):
            with self.assertRaises(adapter.EvidenceUnavailable):
                adapter.native_commands(
                    capture(first + repair + extra),
                    compressed=False,
                    thread_id="thread",
                )
        extra_rpc = (
            True,
            dict(id=5, method="turn/start", params=dict(threadId="thread")),
        )
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(
                capture(first + [extra_rpc] + repair),
                compressed=False,
                thread_id="thread",
            )
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(
                capture(first[:-1] + repair), compressed=False, thread_id="thread"
            )

    def test_missing_or_ambiguous_lifecycle_never_passes(self):
        events = native_events()
        for index in (0, 1, 2, 3, 5):
            altered = copy.deepcopy(events)
            del altered[index]
            with (
                self.subTest(index=index),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                adapter.native_commands(
                    capture(altered), compressed=False, thread_id="thread"
                )
        for index in (0, 1, 2, 3, 4, 5):
            altered = copy.deepcopy(events)
            altered.insert(index, altered[index])
            with (
                self.subTest(duplicate=index),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                adapter.native_commands(
                    capture(altered), compressed=False, thread_id="thread"
                )

    def test_unsupported_mechanisms_bad_identity_or_completion_fail_closed(self):
        for key, value in (
            ("command", "different"),
            ("status", "inProgress"),
            ("exitCode", True),
            ("id", "other"),
        ):
            events = native_events()
            events[4][1]["params"]["item"][key] = value
            with self.subTest(key=key), self.assertRaises(adapter.EvidenceUnavailable):
                adapter.native_commands(
                    capture(events), compressed=False, thread_id="thread"
                )
        events = native_events()
        events[3][1]["params"]["item"]["type"] = "mcpToolCall"
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(
                capture(events), compressed=False, thread_id="thread"
            )

    def test_bounds_and_nonjson_logs_fail_closed(self):
        for name, size in (("MAX_PROTOCOL", 1), ("MAX_RECORD", 1)):
            with (
                patch.object(adapter, name, size),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                adapter.native_commands(
                    capture(native_events()), compressed=False, thread_id="thread"
                )
        with (
            patch.object(evidence, "MAX_COMMANDS", 1),
            self.assertRaises(adapter.EvidenceUnavailable),
        ):
            adapter.native_commands(
                capture(native_events()), compressed=False, thread_id="thread"
            )
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(b"not-json\n", compressed=False, thread_id="thread")


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.camp = Path(directory.name)
        self.version, self.task = "a" * 64, "fake__program.123abcd"
        self.run = (
            self.camp / "runs" / f"stream-{self.version[:12]}-{self.task}" / "attempt-1"
        )
        self.run.mkdir(parents=True)
        self.host = SimpleNamespace(
            camp=self.camp,
            terms={"submission_policy": "rust-preinstalled-build-runtime-v1"},
            validate_evaluator=Mock(),
            validate_harness=Mock(),
            versions=Mock(return_value={self.version: {"harness": None}}),
        )
        self.result = dict(
            version=self.version,
            task=self.task,
            purpose="stream",
            run_dir=str(self.run),
            validity="valid",
            score="SECRET SCORE",
        )
        self.write(self.run.parent / "result.json", self.result)
        self.image = "sha256:" + "b" * 64
        self.write(
            self.run / "manifest.json",
            dict(
                instance=self.task,
                study_version=self.version,
                instructions="executor.md",
                image=self.image,
            ),
        )
        self.write(
            self.run / "run.json",
            dict(thread_id="thread", native_process_exit="fixture"),
        )
        (self.run / "app-server.jsonl").write_bytes(capture(native_events()))
        raw = archive(
            [
                ("compile.sh", b"rustc main.rs -o executable", tarfile.REGTYPE),
                ("main.rs", b"fn main() {}", tarfile.REGTYPE),
            ]
        )
        (self.run / "submission.tar.gz").write_bytes(raw)
        self.write(self.run / "submission-receipt.json", {"sha256": digest(raw)})
        self.eval_dir = self.run / "eval/attempt-1" / self.task
        self.eval_dir.mkdir(parents=True)
        self.write(
            self.run / "eval/canonical-result.json",
            dict(attempts=1, score="SECRET SCORE"),
        )
        eval_path = self.eval_dir / f"{self.task}.eval.json"
        self.write(
            eval_path,
            dict(
                test_results=["SECRET TEST"],
                log=[
                    dict(
                        step="compile",
                        command="chmod +x ./compile.sh && ./compile.sh",
                        returncode=0,
                        output="",
                    )
                ],
            ),
        )
        self.write(self.eval_dir / "evaluation-receipt.json", {"host": "receipt"})
        self.write(self.eval_dir / "evaluation-claim.json", {"host": "claim"})
        allowed = [dict(name="rustc", kind="tool", uses=["build"])]
        policy_path = self.camp / "policy.json"
        self.write(policy_path, dict(allowed=allowed))
        self.policy = SimpleNamespace(
            path=policy_path,
            digest=digest(policy_path.read_bytes()),
            name="rust-preinstalled-build-runtime-v1",
            items=lambda image: {
                "tool:rustc": dict(path="/usr/bin/rustc", sha256="c" * 64)
            },
        )
        self.pins_path = self.camp / "pins.json"
        image_receipt = {"verification": "fixture"}
        pins = {"dependency_policy": {"images": {self.image: image_receipt}}}
        self.write(self.pins_path, pins)
        self.canonical = SimpleNamespace(
            TASKS={self.task: {"image": self.image}},
            PINS_FILE=self.pins_path,
            registry=lambda: SimpleNamespace(dependency_policy=self.policy),
            checked_pins=Mock(return_value=pins),
            validate_receipt=Mock(
                return_value=dict(
                    exit_code=0,
                    submission_sha256=digest(raw),
                    raw_eval_sha256=digest(eval_path.read_bytes()),
                )
            ),
        )
        self.inspection = SimpleNamespace(validate_receipt=Mock())
        self.image_reader = Mock(return_value=([], {"schema": 1, "fixture": "bound"}))
        self.image_patch = patch.object(
            adapter.image_reads, "collect", self.image_reader
        )
        self.image_patch.start()
        self.addCleanup(self.image_patch.stop)
        self.modules = {
            "procontract_canonical": self.canonical,
            "procontract_dependency_inspection": self.inspection,
            "procontract_dependency_policy": SimpleNamespace(
                BUILD_RUNTIME_POLICY="rust-preinstalled-build-runtime-v1"
            ),
            "procontract_ph_audit": SimpleNamespace(
                native_exited=lambda summary: (
                    summary.get("native_process_exit") == "fixture"
                )
            ),
            "procontract_rsi": SimpleNamespace(runner_problem=lambda summary: ""),
        }

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def assemble(self):
        with patch.dict("sys.modules", self.modules):
            return adapter.build_run_pack(self.host, self.run)

    def test_delegated_authentication_projection_and_private_receipt_binding(self):
        pack, receipt = self.assemble()
        self.host.validate_evaluator.assert_called_once_with(self.result)
        self.host.validate_harness.assert_called_once_with(self.version)
        self.canonical.validate_receipt.assert_called_once_with(
            self.task, self.run / "submission.tar.gz", self.eval_dir
        )
        self.inspection.validate_receipt.assert_called_once()
        self.assertEqual(receipt["pack_sha256"], pack.digest)
        self.assertEqual(receipt["submission_sha256"], pack.submission_sha256)
        for _, raw in pack._sources.values():
            self.assertNotIn(b"SECRET", raw)
            self.assertNotIn(b"HIDDEN OUTPUT", raw)
        replay, replay_receipt = self.assemble()
        self.assertEqual(replay.digest, pack.digest)
        self.assertEqual(replay_receipt, receipt)

    def test_typed_reads_are_independent_and_mandatory_in_future_assembly(self):
        row = dict(
            tool="view_image",
            path="/reference/program",
            environment_id=None,
            detail=None,
            observed_path=None,
            outcome="error",
            error="decode failed after reading",
        )
        self.image_reader.return_value = ([row], {"schema": 1, "fixture": "bound"})
        pack, receipt = self.assemble()
        self.image_reader.assert_called_once()
        self.assertEqual(self.image_reader.call_args.args[0], self.run)
        projected = {meta["kind"]: raw for meta, raw in pack._sources.values()}
        self.assertEqual(json.loads(projected["typed_reads"]), [row])
        self.assertEqual(
            json.loads(projected["commands"]),
            [dict(command="rustc main.rs", exit_code=0)],
        )
        self.assertEqual(receipt["typed_reads"], {"schema": 1, "fixture": "bound"})
        self.image_reader.side_effect = ValueError("missing trace")
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()

    def test_authenticated_valid_zero_compile_failure_is_not_reclassified(self):
        # The trusted canonical caller supplies validity/score. This fixture does not
        # claim the historical canonical scorer already admits real compile failures.
        self.result.update(validity="valid", pass_rate=0.0, score="0")
        self.write(self.run.parent / "result.json", self.result)
        raw = archive([("main.rs", b"fn main() {}", tarfile.REGTYPE)])
        (self.run / "submission.tar.gz").write_bytes(raw)
        self.write(self.run / "submission-receipt.json", {"sha256": digest(raw)})
        path = self.eval_dir / f"{self.task}.eval.json"
        self.write(
            path,
            dict(
                log=[
                    dict(
                        step="compile",
                        command="chmod +x ./compile.sh && ./compile.sh",
                        returncode=1,
                        output="chmod: compile.sh: No such file or directory",
                    )
                ]
            ),
        )
        self.canonical.validate_receipt.return_value.update(
            submission_sha256=digest(raw),
            raw_eval_sha256=digest(path.read_bytes()),
        )
        result_before = (self.run.parent / "result.json").read_bytes()
        pack, _ = self.assemble()
        self.host.validate_evaluator.assert_called_once_with(self.result)
        self.assertEqual(pack.unknown, ())
        self.assertEqual((self.run.parent / "result.json").read_bytes(), result_before)
        self.assertEqual(
            [
                meta["path"]
                for meta, _ in pack._sources.values()
                if meta["kind"] == "submission"
            ],
            ["main.rs"],
        )
        projected = next(
            raw for meta, raw in pack._sources.values() if meta["kind"] == "clean_build"
        )
        self.assertEqual(json.loads(projected)["returncode"], 1)

    def test_infrastructure_invalid_is_not_given_a_zero_score(self):
        self.result.update(validity="invalid", pass_rate=None, score=None)
        self.write(self.run.parent / "result.json", self.result)
        before = (self.run.parent / "result.json").read_bytes()
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()
        self.assertEqual((self.run.parent / "result.json").read_bytes(), before)
        self.host.validate_evaluator.assert_not_called()
        self.result.update(validity="valid", pass_rate=0.0)
        self.write(self.run.parent / "result.json", self.result)
        self.canonical.validate_receipt.return_value["exit_code"] = -15
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()

    def test_even_ignored_native_bytes_change_private_replay_identity(self):
        pack, receipt = self.assemble()
        with (self.run / "app-server.jsonl").open("ab") as stream:
            stream.write(b'{"method":"heartbeat"}\n')
        replay, replay_receipt = self.assemble()
        self.assertEqual(pack.digest, replay.digest)
        self.assertNotEqual(receipt, replay_receipt)

    def test_future_policy_rejected_before_reading_or_validating_run(self):
        self.host.terms["submission_policy"] = "rust-preinstalled-v1"
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()
        self.host.validate_evaluator.assert_not_called()
        self.host.validate_harness.assert_not_called()

    def test_absolute_purpose_cannot_escape_campaign(self):
        with tempfile.TemporaryDirectory() as outside:
            purpose = str(Path(outside) / "external")
            external = Path(f"{purpose}-{self.version[:12]}-{self.task}") / "attempt-1"
            external.mkdir(parents=True)
            self.write(
                external.parent / "result.json",
                {**self.result, "purpose": purpose, "run_dir": str(external)},
            )
            with (
                patch.dict("sys.modules", self.modules),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                adapter.build_run_pack(self.host, external)
        self.host.validate_evaluator.assert_not_called()

    def test_activation_mismatch_is_read_only_and_preserves_no_stop_marker(self):
        self.host.versions.return_value[self.version]["harness"] = {
            "sha256": "d" * 64,
            "interpreter": "v2",
        }
        before = sorted(str(path) for path in self.camp.rglob("*"))
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()
        self.assertEqual(sorted(str(path) for path in self.camp.rglob("*")), before)
        self.assertFalse((self.run / "harness-identity-failure.txt").exists())
        self.host.validate_harness.assert_called_once_with(self.version)

    def test_canonical_validation_failure_cannot_fall_back(self):
        self.host.validate_evaluator.side_effect = RuntimeError("identity mismatch")
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()

    def test_missing_capture_compile_and_wrong_policy_are_unknown(self):
        original = (self.run / "app-server.jsonl").read_bytes()
        (self.run / "app-server.jsonl").unlink()
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()
        (self.run / "app-server.jsonl").write_bytes(original)
        self.host.terms["submission_policy"] = "rust-preinstalled-v1"
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()
        self.host.terms["submission_policy"] = "rust-preinstalled-build-runtime-v1"
        path = self.eval_dir / f"{self.task}.eval.json"
        self.write(path, {"log": []})
        self.canonical.validate_receipt.return_value["raw_eval_sha256"] = digest(
            path.read_bytes()
        )
        with self.assertRaises(adapter.EvidenceUnavailable):
            self.assemble()


if __name__ == "__main__":
    unittest.main()
