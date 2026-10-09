"""Synthetic RPC transport: verifies admission semantics, not online H/RSI benefit."""

import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_delivery_budget as delivery
import procontract_h_action_evidence as evidence
import procontract_harness_program as harness


class ActionEvidenceTest(unittest.TestCase):
    def make_probe(
        self,
        *,
        schema=2,
        action="checkpoint",
        remaining=17600,
        predicate=True,
        failure=None,
    ):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        run = Path(temp.name)
        document = {"schema": schema, "when": {"always": predicate}}
        if schema == 2:
            document["action"] = action
        (run / "harness.json").write_text(json.dumps(document))
        program = harness.load(run)
        controller = delivery.DeliveryBudget(
            deadline_secs=18000, reserve_secs=3600, program=program
        )
        records = [
            json.dumps(
                {
                    "method": "turn/started",
                    "params": {"threadId": "thread", "turn": {"id": "turn"}},
                }
            )
        ]

        def request(method, params, handle, timeout):
            records.append(
                "> " + json.dumps({"id": 1, "method": method, "params": params})
            )
            if failure:
                raise failure("synthetic transport outcome")
            records.append(json.dumps({"id": 1, "result": {"turnId": "turn"}}))
            return {"turnId": "turn"}

        controller.maybe_steer(
            SimpleNamespace(request=request),
            SimpleNamespace(
                active=True, thread_id="thread", turn_id="turn", completed=0
            ),
            {"phase": "working", "repairs_used": 0},
            lambda message: None,
            elapsed_secs=18000 - remaining,
            executor_command_completions_observed=1,
        )
        summary = {
            "thread_id": "thread",
            "harness_program": controller.activation,
            "delivery_budget": controller.summary(),
        }
        (run / "run.json").write_text(json.dumps(summary))
        with gzip.open(run / "app-server.jsonl.gz", "wb") as stream:
            stream.write(("\n".join(records) + "\n").encode())
        return run, program, summary, records

    def test_real_controller_acceptance_and_no_action_have_different_receipts(self):
        for predicate in (True, False):
            with self.subTest(predicate=predicate):
                run, program, _, _ = self.make_probe(predicate=predicate)
                result = evidence.probe(run, program, 18000)
                self.assertEqual(
                    result["outcome"], "accepted" if predicate else "no_action"
                )
                self.assertEqual(
                    result["protocol_log"]["coordinate"],
                    {"request_id": 1, "thread_id": "thread", "turn_id": "turn"}
                    if predicate
                    else None,
                )

    def test_timeout_and_error_are_not_accepted_actions(self):
        for failure, expected in ((TimeoutError, "timeout"), (RuntimeError, "error")):
            run, program, _, _ = self.make_probe(failure=failure)
            self.assertEqual(evidence.probe(run, program, 18000)["outcome"], expected)

    def test_v1_floor_before_millisecond_rounding_preserves_legitimate_payload(self):
        run, program, summary, _ = self.make_probe(schema=1, remaining=3599.9996)
        self.assertEqual(
            summary["delivery_budget"]["attempt"]["remaining_secs"], 3600.0
        )
        self.assertEqual(evidence.probe(run, program, 18000)["outcome"], "accepted")
        self.assertEqual(
            set(summary["delivery_budget"]["attempt"]),
            {"turn_id", "remaining_secs", "outcome"},
        )

    def test_positive_convergence_rounding_to_zero_preserves_real_acknowledgement(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                run, program, summary, records = self.make_probe(
                    schema=schema,
                    action="converge",
                    remaining=0.0001,
                )
                self.assertEqual(
                    (
                        summary["delivery_budget"]["attempt"]["remaining_secs"],
                        summary["harness_program"]["last_input"]["remaining_secs"],
                    ),
                    (0.0, 1),
                )
                self.assertIn("approximately 0 seconds", records[1])
                self.assertEqual(
                    evidence.probe(run, program, 18000)["outcome"], "accepted"
                )
                summary["harness_program"]["last_input"]["remaining_secs"] = 0
                (run / "run.json").write_text(json.dumps(summary))
                with self.assertRaisesRegex(RuntimeError, "valid true predicate facts"):
                    evidence.probe(run, program, 18000)
                summary["harness_program"]["last_input"].update(
                    deadline_secs=3, remaining_secs=1
                )
                summary["delivery_budget"]["reserve_secs"] = 0
                (run / "run.json").write_text(json.dumps(summary))
                with self.assertRaisesRegex(RuntimeError, "valid true predicate facts"):
                    evidence.probe(run, program, 3)

    def test_zero_rounded_or_submargin_checkpoint_receipt_stays_invalid(self):
        for remaining, ceiling in ((0.0, 1), (59.999, 60)):
            with self.subTest(remaining=remaining):
                run, program, summary, _ = self.make_probe()
                summary["delivery_budget"]["attempt"]["remaining_secs"] = remaining
                summary["harness_program"]["last_input"]["remaining_secs"] = ceiling
                (run / "run.json").write_text(json.dumps(summary))
                with self.assertRaises(RuntimeError):
                    evidence.probe(run, program, 18000)

    def test_rounding_ceil_and_action_window_must_share_possible_actual_time(self):
        for schema in (1, 2):
            for remaining, impossible_ceiling in ((18.999, 20), (3599.9996, 3601)):
                with self.subTest(schema=schema, remaining=remaining):
                    run, program, summary, _ = self.make_probe(
                        schema=schema,
                        action="converge",
                        remaining=remaining,
                    )
                    self.assertEqual(
                        evidence.probe(run, program, 18000)["outcome"], "accepted"
                    )
                    summary["harness_program"]["last_input"]["remaining_secs"] = (
                        impossible_ceiling
                    )
                    (run / "run.json").write_text(json.dumps(summary))
                    with self.assertRaisesRegex(RuntimeError, "rounding/ceil interval"):
                        evidence.probe(run, program, 18000)

    def test_display_floor_must_share_the_ceil_and_rounding_interval(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                run, program, summary, records = self.make_probe(
                    schema=schema,
                    action="converge",
                    remaining=20.0001,
                )
                self.assertEqual(
                    summary["harness_program"]["last_input"]["remaining_secs"], 21
                )
                self.assertEqual(
                    evidence.probe(run, program, 18000)["outcome"], "accepted"
                )
                request = json.loads(records[1][2:])
                request["params"]["input"][0]["text"] = delivery.notice("converge", 19)
                records[1] = "> " + json.dumps(request)
                with gzip.open(run / "app-server.jsonl.gz", "wb") as stream:
                    stream.write(("\n".join(records) + "\n").encode())
                with self.assertRaisesRegex(RuntimeError, "payload"):
                    evidence.probe(run, program, 18000)

    def test_server_requests_cannot_establish_or_replace_the_executor_turn(self):
        for established in (False, True):
            with self.subTest(established=established):
                run, program, _, records = self.make_probe()
                incoming = json.loads(records[0])
                incoming["id"] = 99
                if established:
                    incoming["params"]["turn"]["id"] = "other"
                    records.insert(1, json.dumps(incoming))
                else:
                    records[0] = json.dumps(incoming)
                with gzip.open(run / "app-server.jsonl.gz", "wb") as stream:
                    stream.write(("\n".join(records) + "\n").encode())
                if established:
                    self.assertEqual(
                        evidence.probe(run, program, 18000)["outcome"], "accepted"
                    )
                else:
                    with self.assertRaisesRegex(RuntimeError, "request differs"):
                        evidence.probe(run, program, 18000)

    def test_extra_steering_parameters_are_not_the_exact_host_request(self):
        run, program, _, records = self.make_probe()
        request = json.loads(records[1][2:])
        request["params"]["unexpected"] = True
        records[1] = "> " + json.dumps(request)
        with gzip.open(run / "app-server.jsonl.gz", "wb") as stream:
            stream.write(("\n".join(records) + "\n").encode())
        with self.assertRaisesRegex(RuntimeError, "request differs"):
            evidence.probe(run, program, 18000)

    def test_native_checkpoint_eligibility_keeps_rounded_boundaries_ineligible(self):
        for remaining in (59.9996, 17700.0001):
            with self.subTest(remaining=remaining):
                run, program, _, _ = self.make_probe(remaining=remaining)
                self.assertEqual(
                    evidence.probe(run, program, 18000)["outcome"], "no_action"
                )
        run, program, summary, _ = self.make_probe(remaining=17700)
        self.assertEqual(evidence.probe(run, program, 18000)["outcome"], "accepted")
        summary["harness_program"]["last_input"]["remaining_secs"] = 17701
        (run / "run.json").write_text(json.dumps(summary))
        with self.assertRaisesRegex(RuntimeError, "rounding/ceil interval"):
            evidence.probe(run, program, 18000)

    def test_acknowledged_arbitrary_payload_and_wrong_ack_turn_are_rejected(self):
        for mutation in ("payload", "ack", "duplicate"):
            run, program, _, records = self.make_probe()
            if mutation == "payload":
                request = json.loads(records[1][2:])
                request["params"]["input"][0]["text"] = "NOT THE REGISTERED ACTION"
                records[1] = "> " + json.dumps(request)
            elif mutation == "ack":
                records[2] = json.dumps({"id": 1, "result": {"turnId": "other"}})
            else:
                records.append(records[1])
            with gzip.open(run / "app-server.jsonl.gz", "wb") as stream:
                stream.write(("\n".join(records) + "\n").encode())
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                evidence.probe(run, program, 18000)

    def test_claimed_checkpoint_eligibility_cannot_bypass_trusted_time_windows(self):
        for remaining in (17999, 59):
            run, program, summary, _ = self.make_probe()
            summary["harness_program"]["last_input"]["remaining_secs"] = remaining
            summary["delivery_budget"]["attempt"]["remaining_secs"] = remaining
            (run / "run.json").write_text(json.dumps(summary))
            with (
                self.subTest(remaining=remaining),
                self.assertRaisesRegex(RuntimeError, "eligible window"),
            ):
                evidence.probe(run, program, 18000)

    def test_raw_log_and_compressed_log_cannot_both_authorize_or_follow_links(self):
        run, program, _, _ = self.make_probe()
        path = run / "app-server.jsonl.gz"
        with gzip.open(path, "rb") as stream:
            (run / "app-server.jsonl").write_bytes(stream.read())
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            evidence.probe(run, program, 18000)
        path.unlink()
        self.assertEqual(evidence.probe(run, program, 18000)["outcome"], "accepted")
        path.symlink_to(run / "app-server.jsonl")
        (run / "app-server.jsonl").rename(run / "private-log")
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            evidence.probe(run, program, 18000)

    def test_source_decoded_and_record_bounds_fail_closed(self):
        for limit in ("MAX_COMPRESSED", "MAX_DECODED", "MAX_RECORD"):
            run, program, _, _ = self.make_probe()
            with self.subTest(limit=limit), mock.patch.object(evidence, limit, 8):
                with self.assertRaisesRegex(RuntimeError, "bound"):
                    evidence.probe(run, program, 18000)


if __name__ == "__main__":
    unittest.main()
