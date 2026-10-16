"""Delivery rejects changed admission and preserves the submitted snapshot after live edits."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

import procontract_delivery as delivery
import procontract_store as store


class DeliveryTests(unittest.TestCase):
    def records(self):
        intake = {"seq": 1, "hash": "a" * 64, "event": {"kind": "intake", "body": {
            "thread_id": "task", "text": "original", "capture_policy": "p"}}}
        capture = {"seq": 2, "hash": "b" * 64, "event": {"kind": "capture", "body": {
            "phase": "task_delivery", "thread_id": "task", "intake": "a" * 64,
            "turn_id": "turn", "execution_epoch": 1, "subject_hash": "c" * 64, "capture_policy": "p"}}}
        return [intake, capture]

    def test_no_delivery_is_invented_for_old_or_foreign_records(self):
        self.assertIsNone(delivery.select(self.records()[:1], "task", "original"))
        self.assertIsNone(delivery.select(self.records(), "different", "original"))

    def test_wrong_prompt_duplicate_turn_or_changed_binding_is_rejected(self):
        for field, value in [("intake", "wrong"), ("capture_policy", "changed"), ("turn_id", ""), ("subject_hash", "bad")]:
            rows = self.records(); rows[1]["event"]["body"][field] = value
            with self.assertRaises(ValueError): delivery.select(rows, "task", "original")
        rows = self.records(); rows.append(copy.deepcopy(rows[1]))
        with self.assertRaises(ValueError): delivery.select(rows, "task", "original")
        with self.assertRaises(ValueError): delivery.select(self.records(), "task", "different request")

    def test_late_old_append_cannot_replace_a_newer_execution(self):
        rows = self.records()
        old = copy.deepcopy(rows[1]); old["seq"] = 3
        old["event"]["body"].update(turn_id="late-old-turn", execution_epoch=0, subject_hash="d" * 64)
        rows.append(old)
        self.assertEqual(delivery.select(rows, "task", "original")["subject_hash"], "c" * 64)

    @unittest.skipUnless(os.environ.get("PRO_CONTRACT_STORE_BIN"), "requires real store binary")
    def test_materialization_uses_committed_bytes_after_live_workspace_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp); database = run / "codex-home/pro_contract"
            workspace = run / "workspace"; workspace.mkdir()
            (workspace / "answer.txt").write_text("delivered")
            (run / "prompt.txt").write_text("original")
            subject = store.capture(database, workspace, [])
            intake = store.append(database, "intake", store.identities(), {
                "thread_id": "task", "text": "original", "base_subject": subject["subject_hash"],
                "capture_policy": subject["capture_policy"],
            })
            store.append(database, "capture", store.identities(), {
                "phase": "task_delivery", "thread_id": "task", "intake": intake["hash"],
                "turn_id": "turn", "execution_epoch": 1, "subject_hash": subject["subject_hash"],
                "capture_policy": subject["capture_policy"],
            })
            (workspace / "answer.txt").write_text("later unsubmitted edit")
            receipt = delivery.snapshot(run, "task")
            target = delivery.materialize(run, receipt)
            self.assertEqual((target / "answer.txt").read_text(), "delivered")
            self.assertEqual((workspace / "answer.txt").read_text(), "later unsubmitted edit")


if __name__ == "__main__": unittest.main()
