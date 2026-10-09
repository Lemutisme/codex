"""Synthetic bound native logs only: no model, Docker, mount or task contents."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import procontract_compliance_adapter as adapter
import procontract_compliance_evidence as evidence
import procontract_native_image_reads as reads
import procontract_native_notice_receipt as native
import procontract_native_trace_binding as binding
from test_procontract_compliance_adapter import capture, native_events
from testing.native_notice_fixture import STORAGE, TRACE

IMAGE = "data:application/octet-stream;base64,c3ludGhldGljLWltYWdlLWJ5dGVz"


class ImageReadsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.run = Path(directory.name)
        self.manifest = dict(
            study={
                "manifest_path": str(self.run / "study.json"),
                "manifest_sha256": "a" * 64,
            },
            study_version="b" * 64,
            codex_sha256="c" * 64,
            model="gpt-5.6-luna",
            effort="max",
            instructions="executor.md",
            instance="synthetic",
        )
        with patch.object(
            binding.protocol,
            "campaign_profile",
            return_value=SimpleNamespace(protocol=binding.protocol.H_PROTOCOL),
        ):
            binding.prepare(
                self.run,
                self.manifest,
                dict(study=self.manifest["study"], native_notice_trace=binding.PROFILE),
            )
        self.summary = dict(
            thread_id="thread",
            native_notice_trace=dict(
                schema=1,
                descriptor_sha256=self.manifest["native_notice_trace"]["sha256"],
                retained_private_root=str(self.run / binding.ROOT),
                storage=copy.deepcopy(STORAGE),
                evidence={"status": "unknown", "reason": "no_steer_observed"},
            ),
        )
        self.storage_patch = patch.object(
            binding, "storage", return_value=copy.deepcopy(STORAGE)
        )
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.bundle = self.run / binding.ROOT / f"trace-{TRACE}-thread"
        (self.bundle / "payloads").mkdir(parents=True)
        self.put(
            "manifest.json",
            dict(
                schema_version=1,
                trace_id=TRACE,
                rollout_id="thread",
                root_thread_id="thread",
                started_at_unix_ms=1000,
                raw_event_log="trace.jsonl",
                payloads_dir="payloads",
            ),
        )
        self.events = []
        self.add("rollout_started", trace_id=TRACE, root_thread_id="thread")
        self.add("thread_started", thread_id="thread", agent_path="/root")
        self.add("codex_turn_started", thread_id="thread", codex_turn_id="turn")
        self.start = self.add(
            "tool_call_started",
            tool_call_id="v1",
            model_visible_call_id="v1",
            code_mode_runtime_tool_id=None,
            requester={"type": "model"},
            kind={"type": "other", "name": "view_image"},
            invocation_payload=self.ref(1, "tool_invocation"),
        )
        self.put(
            "payloads/1.json",
            dict(
                tool_name="view_image",
                tool_namespace=None,
                payload=dict(
                    type="function", arguments=json.dumps({"path": "picture.png"})
                ),
            ),
        )
        self.end = self.add(
            "tool_call_ended",
            tool_call_id="v1",
            status="completed",
            result_payload=self.ref(2, "tool_result"),
        )
        self.put(
            "payloads/2.json",
            dict(
                type="direct_response",
                response_item=dict(
                    type="function_call_output",
                    call_id="v1",
                    output=[dict(type="input_image", image_url=IMAGE, detail="high")],
                ),
            ),
        )
        self.add("codex_turn_ended", codex_turn_id="turn", status="completed")
        self.add("thread_ended", thread_id="thread", status="completed")
        self.add("rollout_ended", status="completed")
        self.app = native_events()
        image = dict(type="imageView", id="v1", path="/workspace/picture.png")
        self.app[-1:-1] = [
            (
                False,
                dict(
                    method=method,
                    params=dict(
                        threadId="thread", turnId="turn", item=copy.deepcopy(image)
                    ),
                ),
            )
            for method in ("item/started", "item/completed")
        ]

    def put(self, path, value):
        (self.bundle / path).write_text(json.dumps(value))

    def get(self, path):
        return json.loads((self.bundle / path).read_text())

    def add(self, event_type, **payload):
        event = dict(
            schema_version=1,
            seq=len(self.events) + 1,
            wall_time_unix_ms=1000,
            rollout_id="thread",
            thread_id="thread",
            codex_turn_id="turn",
            payload={"type": event_type, **payload},
        )
        self.events.append(event)
        return event

    @staticmethod
    def ref(number, kind):
        return dict(
            raw_payload_id=f"raw_payload:{number}",
            kind={"type": kind},
            path=f"payloads/{number}.json",
        )

    def collect(self):
        for index, event in enumerate(self.events, 1):
            event["seq"] = index
        (self.bundle / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events)
        )
        commands, receipt = adapter.native_commands(
            capture(self.app), compressed=False, thread_id="thread"
        )
        self.assertEqual(commands, [dict(command="rustc main.rs", exit_code=0)])
        return reads.collect(self.run, self.manifest, self.summary, receipt)

    def expected(self):
        return dict(
            tool="view_image",
            path="picture.png",
            environment_id=None,
            detail=None,
            observed_path="/workspace/picture.png",
            outcome="completed",
            error=None,
        )

    def test_success_projects_separate_typed_read_without_image_bytes_or_notice(self):
        rows, receipt = self.collect()
        self.assertEqual(rows, [self.expected()])
        self.assertEqual(self.collect(), (rows, receipt))
        self.assertEqual(
            set(receipt["files"]),
            {"manifest.json", "trace.jsonl", "payloads/1.json", "payloads/2.json"},
        )
        self.assertNotIn(IMAGE, json.dumps((rows, receipt)))
        self.assertEqual(
            receipt["reads_sha256"], evidence._digest(evidence._typed_reads(rows))
        )

    def test_resolved_code_mode_invocation_is_not_reconstructed_from_javascript(self):
        self.start["payload"].update(
            model_visible_call_id=None,
            code_mode_runtime_tool_id="runtime-4",
            requester={"type": "code_cell", "runtime_cell_id": "cell-7"},
        )
        self.put(
            "payloads/2.json",
            dict(type="code_mode_response", value=dict(image_url=IMAGE)),
        )
        invocation = self.get("payloads/1.json")
        invocation["payload"]["arguments"] = json.dumps(
            dict(
                path="/reference/executable",
                detail="original",
                environment_id="container",
            )
        )
        self.put("payloads/1.json", invocation)
        for _, event in self.app[-3:-1]:
            event["params"]["item"]["path"] = "/reference/executable"
        rows, _ = self.collect()
        expected = self.expected()
        expected.update(
            path="/reference/executable",
            observed_path="/reference/executable",
            detail="original",
            environment_id="container",
        )
        self.assertEqual(rows, [expected])

    def test_failed_decode_retains_reference_attempt_without_claiming_no_read(self):
        invocation = self.get("payloads/1.json")
        invocation["payload"]["arguments"] = json.dumps(dict(path="/reference/program"))
        self.put("payloads/1.json", invocation)
        self.end["payload"]["status"] = "failed"
        self.put(
            "payloads/2.json",
            dict(
                type="error",
                error="unable to process image: invalid or unsupported image data",
            ),
        )
        del self.app[-3:-1]
        rows, _ = self.collect()
        expected = self.expected()
        expected.update(
            path="/reference/program",
            observed_path=None,
            outcome="error",
            error="unable to process image: invalid or unsupported image data",
        )
        self.assertEqual(rows, [expected])
        self.assertNotIn("unread", json.dumps(rows))

    def test_empty_image_projection_scans_unrelated_real_dispatch_without_reclassifying_it(
        self,
    ):
        value = self.get("payloads/1.json")
        value["tool_name"] = "exec_command"
        self.start["payload"]["kind"] = {"type": "exec_command"}
        self.put("payloads/1.json", value)
        del self.app[-3:-1]
        empty, receipt = self.collect()
        self.assertEqual(empty, [])
        self.assertEqual(set(receipt["files"]), {"manifest.json", "trace.jsonl"})
        (self.bundle / "payloads/1.json").unlink()
        self.assertEqual(self.collect(), (empty, receipt))

    def test_notification_missing_duplicate_foreign_or_changed_path_is_unknown(self):
        original = copy.deepcopy(self.app)
        variants = []
        for index in (-3, -2):
            value = copy.deepcopy(original)
            del value[index]
            variants.append(value)
        value = copy.deepcopy(original)
        value.insert(-1, copy.deepcopy(value[-2]))
        variants.append(value)
        for field, different in (
            ("id", "foreign"),
            ("path", "/different"),
            ("type", "mcpToolCall"),
        ):
            value = copy.deepcopy(original)
            value[-2][1]["params"]["item"][field] = different
            variants.append(value)
        value = copy.deepcopy(original)
        value[-2][1]["params"]["threadId"] = "foreign"
        variants.append(value)
        for value in variants:
            self.app = value
            with (
                self.subTest(value=value),
                self.assertRaises((ValueError, adapter.EvidenceUnavailable)),
            ):
                self.collect()

    def test_trace_missing_duplicate_foreign_or_unknown_result_is_unknown(self):
        original = copy.deepcopy(self.events)
        variants = []
        for index in (2, 3, 4, 5, 6, 7):
            value = copy.deepcopy(original)
            del value[index]
            variants.append(value)
        for index in (3, 4):
            value = copy.deepcopy(original)
            value.insert(index, copy.deepcopy(value[index]))
            variants.append(value)
        for field in ("thread_id", "codex_turn_id"):
            value = copy.deepcopy(original)
            value[4][field] = "foreign"
            variants.append(value)
        value = copy.deepcopy(original)
        value[4]["payload"]["tool_call_id"] = "foreign"
        variants.append(value)
        for value in variants:
            self.events = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.collect()
        self.events = original
        self.put("payloads/2.json", dict(type="future_result", value={}))
        with self.assertRaises(ValueError):
            self.collect()

    def test_unknown_invocation_payload_paths_and_arguments_fail_closed(self):
        original = self.get("payloads/1.json")
        for args in (
            {"path": "x" * 4097},
            {"path": "\0"},
            {"path": "/ref", "read": True},
            {"path": []},
            {"path": "x", "detail": "future"},
        ):
            value = copy.deepcopy(original)
            value["payload"]["arguments"] = json.dumps(args)
            self.put("payloads/1.json", value)
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.collect()
        self.put("payloads/1.json", original)
        self.start["payload"]["invocation_payload"]["path"] = "../escape"
        with self.assertRaises(ValueError):
            self.collect()

    def test_failed_reads_cannot_disappear_through_missing_kind_or_dispatch_scope(self):
        self.end["payload"]["status"] = "failed"
        self.put(
            "payloads/2.json", dict(type="error", error="decode failed after reading")
        )
        del self.app[-3:-1]
        original = copy.deepcopy(self.events)
        variants = []
        for kind in (
            None,
            {},
            {"type": "future"},
            {"type": "other"},
            {"type": "other", "name": ""},
        ):
            value = copy.deepcopy(original)
            value[3]["payload"]["kind"] = kind
            variants.append(value)
        for field in ("thread_id", "codex_turn_id"):
            for missing in (None, "", "foreign"):
                value = copy.deepcopy(original)
                value[3][field] = value[4][field] = missing
                variants.append(value)
        for value in variants:
            self.events = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.collect()

    def test_malformed_requester_namespace_and_outcome_are_unknown(self):
        start = copy.deepcopy(self.start["payload"])
        for field, value in (
            ("requester", {"type": "foreign"}),
            ("model_visible_call_id", "foreign"),
            ("code_mode_runtime_tool_id", "unexpected"),
            ("kind", {"type": "future"}),
        ):
            self.start["payload"] = {**start, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.collect()
        self.start["payload"] = start
        result = self.get("payloads/2.json")
        for value in (
            {"type": "code_mode_response", "value": {"image_url": IMAGE}},
            {
                "type": "direct_response",
                "response_item": {**result["response_item"], "call_id": "foreign"},
            },
            {"type": "error", "error": "failed"},
        ):
            self.put("payloads/2.json", value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.collect()
        self.put("payloads/2.json", result)
        invocation = self.get("payloads/1.json")
        invocation["tool_namespace"] = "untrusted_mcp"
        self.put("payloads/1.json", invocation)
        with self.assertRaises(ValueError):
            self.collect()

    def test_failed_error_text_and_projection_caps_are_hard_bounds(self):
        self.end["payload"]["status"] = "failed"
        del self.app[-3:-1]
        self.put("payloads/2.json", dict(type="error", error="x" * 4097))
        with self.assertRaises(ValueError):
            self.collect()
        self.put("payloads/2.json", dict(type="error", error="decode failed"))
        with (
            patch.object(evidence, "MAX_TYPED_READS", 1),
            self.assertRaises(ValueError),
        ):
            self.collect()

    def test_descriptor_storage_source_mutation_and_symlinks_are_not_accepted(self):
        rows, before = self.collect()
        path = self.bundle / "payloads/2.json"
        path.write_bytes(path.read_bytes() + b"\n")
        after_rows, after = self.collect()
        self.assertEqual(rows, after_rows)
        self.assertNotEqual(before, after)
        original_read = native._Scan.read
        count = 0

        def changed(scan, source, cap):
            nonlocal count
            raw = original_read(scan, source, cap)
            if source == path:
                count += 1
                if count == 1:
                    source.write_bytes(raw + b"\n")
            return raw

        with patch.object(native._Scan, "read", changed), self.assertRaises(ValueError):
            self.collect()
        with (
            patch.object(
                binding, "storage", return_value={**STORAGE, "exhausted": True}
            ),
            self.assertRaises(ValueError),
        ):
            self.collect()
        old = self.summary["native_notice_trace"]["descriptor_sha256"]
        self.summary["native_notice_trace"]["descriptor_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.collect()
        self.summary["native_notice_trace"]["descriptor_sha256"] = old
        source = self.run / "different-reader.py"
        source.write_text("# changed reader")
        with (
            patch.object(native, "__file__", str(source)),
            self.assertRaises(RuntimeError),
        ):
            self.collect()
        target = self.run / "payload-copy.json"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.collect()


if __name__ == "__main__":
    unittest.main()
