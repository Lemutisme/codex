import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from procontract_native_notice_receipt import Baseline, Limits, Reader

THREAD = "01a11fcd-b1fa-72a0-846a-7d772486c736"
TURN = "01a11fcd-b20c-7a90-ab7c-9893331ec5aa"
NOTICE = "Synthetic evidence notice; continue this same task."
CALLS = ("0a66763f-006c-44d6-991c-45cfa9204d32", "b5596971-5d97-45a4-923e-142c3244b9f3")
SMOKE = Path("/tmp/procontract-native-steer-trace-smoke-20261009/output/trace")


def message(text, role="user", kind="input_text"):
    return {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}


class NativeNoticeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (
            Path(self.temp.name)
            / "trace"
            / f"trace-e3ecbbf6-e106-4a10-958d-fba819f53287-{THREAD}"
        )
        (self.root / "payloads").mkdir(parents=True)
        self.manifest = {
            "schema_version": 1,
            "trace_id": "e3ecbbf6-e106-4a10-958d-fba819f53287",
            "rollout_id": THREAD,
            "root_thread_id": THREAD,
            "started_at_unix_ms": 1000,
            "raw_event_log": "trace.jsonl",
            "payloads_dir": "payloads",
        }
        self.put("manifest.json", self.manifest)
        self.events = []
        self.add(
            "rollout_started", root_thread_id=THREAD, trace_id=self.manifest["trace_id"]
        )
        self.add("thread_started", thread_id=THREAD, agent_path="/root")
        self.add("codex_turn_started", thread_id=THREAD, codex_turn_id=TURN)
        for index, call in enumerate(CALLS):
            request = {
                "model": "gpt-5.6-luna",
                "stream": True,
                "input": [{"id": "native-user-initial", **message("Synthetic task")}],
                "client_metadata": {"thread_id": THREAD, "turn_id": TURN},
                "reasoning": {"effort": "max"},
            }
            if index:
                request["input"].extend(
                    [
                        message("Synthetic prior answer", "assistant", "output_text"),
                        message(NOTICE),
                    ]
                )
            self.put(f"payloads/{index * 2 + 1}.json", request)
            self.put(
                f"payloads/{index * 2 + 2}.json",
                {
                    "response_id": f"response-{index}",
                    "output_items": [],
                    "token_usage": {},
                },
            )
            self.add(
                "inference_started",
                inference_call_id=call,
                thread_id=THREAD,
                codex_turn_id=TURN,
                model="gpt-5.6-luna",
                provider_name="synthetic",
                request_payload=self.ref(index * 2 + 1, "inference_request"),
            )
            self.add(
                "inference_completed",
                inference_call_id=call,
                response_id=f"response-{index}",
                response_payload=self.ref(index * 2 + 2, "inference_response"),
            )
        self.add("codex_turn_ended", codex_turn_id=TURN, status="completed")
        self.write_events(self.events[:4])
        self.reader = Reader(self.root.parent, thread_id=THREAD, turn_id=TURN)

    def test_long_opaque_provider_ids_need_an_explicit_compatible_profile(self):
        response_id = "resp_" + "x" * 500
        self.put(
            "payloads/4.json",
            {"response_id": response_id, "output_items": [], "token_usage": {}},
        )
        for event in self.events:
            payload = event["payload"]
            if (
                payload["type"] == "inference_completed"
                and payload["inference_call_id"] == CALLS[1]
            ):
                payload["response_id"] = response_id
        baseline = self.reader.before_steer(NOTICE)
        self.write_events(self.events)
        self.assertEqual(
            self.reader.after_run(baseline, notice=NOTICE, accepted_turn_id=TURN),
            {"status": "unknown", "reason": "invalid_identifier"},
        )
        compatible = Reader(
            self.root.parent,
            thread_id=THREAD,
            turn_id=TURN,
            limits=dataclasses.replace(Limits(), max_response_id_chars=1024),
        )
        result = compatible.after_run(baseline, notice=NOTICE, accepted_turn_id=TURN)
        self.assertEqual(
            (result["status"], result["response_id"]), ("observed", response_id)
        )

    def put(self, relative, value):
        (self.root / relative).write_text(json.dumps(value), encoding="utf-8")

    def get(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    @staticmethod
    def ref(number, kind):
        return {
            "raw_payload_id": f"raw_payload:{number}",
            "kind": {"type": kind},
            "path": f"payloads/{number}.json",
        }

    def add(self, kind, **payload):
        scoped = kind.startswith("inference_") or kind.startswith("codex_turn_")
        self.events.append(
            {
                "schema_version": 1,
                "seq": len(self.events) + 1,
                "wall_time_unix_ms": 1000 + len(self.events),
                "rollout_id": THREAD,
                "thread_id": THREAD if scoped else None,
                "codex_turn_id": TURN if scoped else None,
                "payload": {"type": kind, **payload},
            }
        )

    def write_events(self, events):
        (self.root / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )

    def sibling_bundle(self, thread_id, trace_id):
        bundle = self.root.parent / f"trace-{trace_id}-{thread_id}"
        shutil.copytree(self.root, bundle)
        for path in bundle.rglob("*"):
            if path.is_file():
                content = (
                    path.read_text()
                    .replace(THREAD, thread_id)
                    .replace(self.manifest["trace_id"], trace_id)
                )
                path.write_text(content)
        return bundle

    def baseline(self):
        baseline = self.reader.before_steer(NOTICE)
        self.assertIsInstance(baseline, Baseline)
        self.assertNotIn(NOTICE, repr(baseline))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(baseline, dataclasses.fields(baseline)[0].name, None)
        return baseline

    def finish(self, baseline, *, accepted_turn_id=TURN):
        self.write_events(self.events)
        return self.reader.after_run(
            baseline, notice=NOTICE, accepted_turn_id=accepted_turn_id
        )

    def unknown(self, result):
        self.assertEqual(result.get("status"), "unknown")
        self.assertEqual(set(result), {"status", "reason"})
        self.assertRegex(result["reason"], r"^[a-z][a-z0-9_]{0,63}$")
        self.assertLess(len(json.dumps(result)), 8192)
        self.assertNotIn(NOTICE, json.dumps(result))

    def test_observes_new_same_turn_pair_without_exposing_content(self):
        result = self.finish(self.baseline())

        def digest(path):
            return hashlib.sha256((self.root / path).read_bytes()).hexdigest()

        expected = {
            "status": "observed",
            "scope": "request_contains_notice_and_response_completed",
            "notice_sha256": hashlib.sha256(NOTICE.encode()).hexdigest(),
            "thread_id": THREAD,
            "turn_id": TURN,
            "inference_call_id": CALLS[1],
            "started_seq": 6,
            "completed_seq": 7,
            "response_id": "response-1",
            "fence_seq": 4,
            "baseline_request_sha256": digest("payloads/1.json"),
            "manifest_sha256": digest("manifest.json"),
            "request": {
                **self.ref(3, "inference_request"),
                "sha256": digest("payloads/3.json"),
            },
            "response": {
                **self.ref(4, "inference_response"),
                "sha256": digest("payloads/4.json"),
            },
        }
        self.assertEqual(result, expected)
        self.assertNotIn(NOTICE, json.dumps(result))
        self.assertNotIn("Synthetic prior answer", json.dumps(result))
        self.assertLess(len(json.dumps(result)), 8192)

    def test_missing_or_wrong_ack_cannot_observe(self):
        baseline = self.baseline()
        for ack in (None, "different-turn"):
            with self.subTest(ack=ack):
                self.unknown(self.finish(baseline, accepted_turn_id=ack))

    def test_old_completion_after_dispatch_does_not_count(self):
        baseline = self.baseline()
        self.events = self.events[:5]
        self.unknown(self.finish(baseline))

    def test_only_complete_exact_user_input_text_matches(self):
        baseline = self.baseline()
        for item in (
            message(NOTICE, "assistant"),
            message(NOTICE, "developer"),
            message(NOTICE, kind="output_text"),
            message(NOTICE + " extra"),
        ):
            with self.subTest(item=item):
                request = self.get("payloads/3.json")
                request["input"][-1] = item
                self.put("payloads/3.json", request)
                self.unknown(self.finish(baseline))

    def test_notice_already_in_baseline_is_unknown(self):
        request = self.get("payloads/1.json")
        request["input"].append(message(NOTICE))
        self.put("payloads/1.json", request)
        self.unknown(self.reader.before_steer(NOTICE))

    def test_other_thread_or_turn_cannot_supply_receipt(self):
        baseline = self.baseline()
        original = copy.deepcopy(self.events)
        for key in ("thread_id", "codex_turn_id"):
            with self.subTest(key=key):
                self.events = copy.deepcopy(original)
                self.events[5][key] = self.events[5]["payload"][key] = "other"
                self.events[6][key] = "other"
                self.unknown(self.finish(baseline))

    def test_root_identity_and_request_metadata_are_required(self):
        self.events[1]["payload"]["agent_path"] = "/root/worker"
        self.write_events(self.events[:4])
        self.unknown(self.reader.before_steer(NOTICE))
        self.events[1]["payload"]["agent_path"] = "/root"
        self.write_events(self.events[:4])
        baseline = self.baseline()
        request = self.get("payloads/3.json")
        request["client_metadata"]["turn_id"] = "other"
        self.put("payloads/3.json", request)
        self.unknown(self.finish(baseline))

    def test_prefix_rewrite_gap_or_partial_line_is_unknown(self):
        baseline = self.baseline()
        original = copy.deepcopy(self.events)
        self.events[0]["wall_time_unix_ms"] += 1
        self.unknown(self.finish(baseline))
        self.events = copy.deepcopy(original)
        self.events[5]["seq"] += 1
        self.unknown(self.finish(baseline))
        self.events = original
        self.write_events(self.events)
        with (self.root / "trace.jsonl").open("a") as stream:
            stream.write('{"seq":9')
        self.unknown(
            self.reader.after_run(baseline, notice=NOTICE, accepted_turn_id=TURN)
        )

    def test_request_history_replacement_is_unknown(self):
        baseline = self.baseline()
        request = self.get("payloads/3.json")
        for previous in ("response-0", False, 0, [], ""):
            with self.subTest(previous_response_id=previous):
                request["previous_response_id"] = previous
                self.put("payloads/3.json", request)
                self.unknown(self.finish(baseline))

    def test_payload_path_traversal_and_wrong_ref_kind_are_unknown(self):
        baseline = self.baseline()
        ref = self.events[5]["payload"]["request_payload"]
        for path in (
            "../outside.json",
            "/tmp/payload.json",
            "payloads/0.json",
            "payloads/03.json",
        ):
            with self.subTest(path=path):
                ref["path"] = path
                self.unknown(self.finish(baseline))
        ref["path"] = "payloads/3.json"
        ref["kind"]["type"] = "inference_response"
        self.unknown(self.finish(baseline))

    def test_missing_malformed_or_symlink_payload_is_unknown(self):
        baseline = self.baseline()
        path = self.root / "payloads/3.json"
        path.unlink()
        self.unknown(self.finish(baseline))
        path.write_text("{broken", encoding="utf-8")
        self.unknown(self.finish(baseline))
        path.unlink()
        path.symlink_to(self.root / "payloads/1.json")
        self.unknown(self.finish(baseline))

    def test_duplicate_completion_and_response_id_mismatch_are_unknown(self):
        baseline = self.baseline()
        original = copy.deepcopy(self.events)
        self.events.insert(7, copy.deepcopy(self.events[6]))
        for seq, event in enumerate(self.events, 1):
            event["seq"] = seq
        self.unknown(self.finish(baseline))
        self.events = original
        response = self.get("payloads/4.json")
        response["response_id"] = "mismatch"
        self.put("payloads/4.json", response)
        self.unknown(self.finish(baseline))

    def test_parser_caps_fail_closed(self):
        for key, value in (
            ("max_manifest_bytes", 10),
            ("max_log_bytes", 10),
            ("max_line_bytes", 10),
            ("max_events", 3),
            ("max_payload_bytes", 10),
            ("max_total_bytes", 50),
            ("max_seconds", 1e-9),
            ("max_notice_bytes", 1),
        ):
            with self.subTest(limit=key):
                reader = Reader(
                    self.root.parent,
                    thread_id=THREAD,
                    turn_id=TURN,
                    limits=dataclasses.replace(Limits(), **{key: value}),
                )
                self.unknown(reader.before_steer(NOTICE))

    def test_baseline_payload_mutation_and_compaction_fail_closed(self):
        baseline = self.baseline()
        request = self.get("payloads/1.json")
        request["input"][0]["content"][0]["text"] = "Replacement task"
        self.put("payloads/1.json", request)
        self.unknown(self.finish(baseline))
        request["input"][0]["content"][0]["text"] = "Synthetic task"
        self.put("payloads/1.json", request)
        for event_type in (
            "context_compacted",
            "thread_rolled_back",
            "history_reset",
            "rollback",
            "thread_reset",
        ):
            with self.subTest(event_type=event_type):
                self.events[4]["payload"] = {"type": event_type}
                self.unknown(self.finish(baseline))

    def test_user_history_rewrite_without_named_event_is_unknown(self):
        baseline = self.baseline()
        original = self.get("payloads/3.json")
        for replacement in (
            {"id": "native-user-initial", **message("Replacement task")},
            {"id": "changed-native-id", **message("Synthetic task")},
        ):
            with self.subTest(replacement=replacement):
                request = copy.deepcopy(original)
                request["input"][0] = replacement
                self.put("payloads/3.json", request)
                self.unknown(self.finish(baseline))

    @unittest.skipUnless(
        hasattr(os, "mkfifo"), "FIFO files unavailable on this platform"
    )
    def test_fifo_payload_fails_closed_without_blocking(self):
        path = self.root / "payloads/1.json"
        path.unlink()
        os.mkfifo(path)
        code = (
            "import json,sys; from procontract_native_notice_receipt import Reader; "
            "reader=Reader(sys.argv[1],thread_id=sys.argv[2],turn_id=sys.argv[3]); "
            "print(json.dumps(reader.before_steer(sys.argv[4])))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root.parent), THREAD, TURN, NOTICE],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        self.unknown(json.loads(result.stdout))

    def test_late_ordinary_requests_and_compaction_preserve_early_witness(self):
        baseline = self.baseline()
        expected = self.finish(baseline)
        self.assertEqual(expected["status"], "observed")
        self.events.pop()  # Continue the same turn instead of ending after its first receipt.
        for index in range(11):
            call = f"00000000-0000-0000-0000-{100 + index:012d}"
            request_number, response_number = index * 2 + 5, index * 2 + 6
            self.put(f"payloads/{request_number}.json", self.get("payloads/3.json"))
            self.put(
                f"payloads/{response_number}.json",
                {"response_id": f"later-{index}", "output_items": []},
            )
            self.add(
                "inference_started",
                inference_call_id=call,
                thread_id=THREAD,
                codex_turn_id=TURN,
                model="gpt-5.6-luna",
                provider_name="synthetic",
                request_payload=self.ref(request_number, "inference_request"),
            )
            self.add(
                "inference_completed",
                inference_call_id=call,
                response_id=f"later-{index}",
                response_payload=self.ref(response_number, "inference_response"),
            )
        self.add("context_compacted")
        self.add("codex_turn_ended", codex_turn_id=TURN, status="completed")
        self.assertEqual(self.finish(baseline), expected)

    def test_independent_procontract_worker_root_bundle_is_ignored(self):
        # Independent native worker sessions also legitimately report agent_path=/root.
        self.sibling_bundle(
            "01a11fcd-b1fa-72a0-846a-7d772486c737",
            "e3ecbbf6-e106-4a10-958d-fba819f53288",
        )
        result = self.finish(self.baseline())
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["thread_id"], THREAD)

    def test_duplicate_executor_root_bundle_is_ambiguous(self):
        self.sibling_bundle(THREAD, "e3ecbbf6-e106-4a10-958d-fba819f53288")
        self.unknown(self.reader.before_steer(NOTICE))

    def test_bundle_scan_limit_fails_closed(self):
        self.sibling_bundle(
            "01a11fcd-b1fa-72a0-846a-7d772486c737",
            "e3ecbbf6-e106-4a10-958d-fba819f53288",
        )
        reader = Reader(
            self.root.parent,
            thread_id=THREAD,
            turn_id=TURN,
            limits=dataclasses.replace(Limits(), max_bundles=1),
        )
        self.unknown(reader.before_steer(NOTICE))

    @unittest.skipUnless(
        SMOKE.is_dir(), "optional recorded localhost native trace fixture absent"
    )
    def test_actual_native_smoke_trace_replay(self):
        shutil.rmtree(self.root)
        shutil.copytree(next(SMOKE.iterdir()), self.root)
        events = [
            json.loads(line)
            for line in (self.root / "trace.jsonl").read_text().splitlines()
        ]
        notice = self.get("payloads/6.json")["input"][-1]["content"][0]["text"]
        self.write_events(events[:6])
        baseline = self.reader.before_steer(notice)
        self.assertIsInstance(baseline, Baseline)
        self.write_events(events)
        result = self.reader.after_run(baseline, notice=notice, accepted_turn_id=TURN)
        self.assertEqual(result.get("status"), "observed")
        self.assertNotIn(notice, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
