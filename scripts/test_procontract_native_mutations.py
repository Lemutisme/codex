"""Synthetic native mutation notifications only; no model, Docker or filesystem actions."""

import copy
import json
import unittest
from unittest.mock import patch

import procontract_compliance_adapter as adapter
import procontract_native_mutations as mutations
import test_procontract_compliance_adapter as adapter_fixtures
import test_procontract_compliance_evidence as evidence_fixtures
from test_procontract_compliance_adapter import capture, native_events


def change(path="/reference/executable", *, kind=None, diff="PRIVATE DIFF CONTENT"):
    return dict(
        path=path, kind=kind or {"type": "update", "move_path": None}, diff=diff
    )


def notification(
    phase, changes, *, status=None, item_id="patch", turn="turn", thread="thread"
):
    params = dict(threadId=thread, turnId=turn)
    if phase == "patch_updated":
        params.update(itemId=item_id, changes=changes)
        return False, dict(method="item/fileChange/patchUpdated", params=params)
    params["item"] = dict(type="fileChange", id=item_id, changes=changes, status=status)
    return False, dict(method=f"item/{phase}", params=params)


def events(phases):
    base = native_events()
    return base[:-1] + phases + base[-1:]


def project(phases):
    commands, receipt = adapter.native_commands(
        capture(events(phases)), compressed=False, thread_id="thread"
    )
    return commands, receipt


class NativeMutationTests(unittest.TestCase):
    def phases(self, status="completed"):
        return [
            notification("started", [change()], status="inProgress"),
            notification("completed", [change()], status=status),
        ]

    def test_every_phase_preserves_reference_and_rename_paths_not_diff_body(self):
        phases = [
            notification(
                "patch_updated",
                [change("../reference/executable", kind={"type": "delete"})],
            ),
            notification("patch_updated", [change("temporary", kind={"type": "add"})]),
            notification(
                "started",
                [change(kind={"type": "update", "move_path": "/workspace/renamed"})],
                status="inProgress",
            ),
            notification(
                "patch_updated", [change("later-preview", kind={"type": "add"})]
            ),
            notification(
                "completed",
                [change("/workspace/output", kind={"type": "add"})],
                status="failed",
            ),
        ]
        commands, receipt = project(phases)
        self.assertEqual(commands, [dict(command="rustc main.rs", exit_code=0)])
        expected = [
            dict(
                turn_id="turn",
                item_id="patch",
                phase=phase,
                status=status,
                changes=[{key: value for key, value in raw.items() if key != "diff"}],
            )
            for phase, status, raw in (
                (
                    "patch_updated",
                    None,
                    change("../reference/executable", kind={"type": "delete"}),
                ),
                ("patch_updated", None, change("temporary", kind={"type": "add"})),
                (
                    "started",
                    "inProgress",
                    change(kind={"type": "update", "move_path": "/workspace/renamed"}),
                ),
                ("patch_updated", None, change("later-preview", kind={"type": "add"})),
                (
                    "completed",
                    "failed",
                    change("/workspace/output", kind={"type": "add"}),
                ),
            )
        ]
        self.assertEqual(receipt["typed_mutations"], expected)
        self.assertEqual(json.loads(mutations.encode(expected)), expected)
        self.assertNotIn("PRIVATE DIFF CONTENT", json.dumps(expected))
        altered = copy.deepcopy(phases)
        altered[-1][1]["params"]["item"]["changes"][0]["diff"] = (
            "DIFFERENT PRIVATE DIFF"
        )
        _, replay = project(altered)
        self.assertEqual(replay["typed_mutations"], expected)
        self.assertNotEqual(replay["protocol_sha256"], receipt["protocol_sha256"])

    def test_preview_only_and_failed_declined_are_observations_not_no_effects(self):
        _, receipt = project([notification("patch_updated", [change()])])
        self.assertEqual(
            receipt["typed_mutations"],
            [
                dict(
                    turn_id="turn",
                    item_id="patch",
                    phase="patch_updated",
                    status=None,
                    changes=[
                        dict(
                            path="/reference/executable",
                            kind={"type": "update", "move_path": None},
                        )
                    ],
                )
            ],
        )
        for status in ("completed", "failed", "declined"):
            with self.subTest(status=status):
                _, receipt = project(self.phases(status))
                self.assertEqual(
                    [row["status"] for row in receipt["typed_mutations"]],
                    ["inProgress", status],
                )
                self.assertEqual(len(receipt["typed_mutations"]), 2)

    def test_missing_duplicate_late_or_wrong_turn_lifecycle_is_unknown(self):
        phases = self.phases()
        invalid = [
            phases[:1],
            phases[1:],
            [phases[0], phases[0], phases[1]],
            [*phases, phases[1]],
            [*phases, notification("patch_updated", [change()])],
            [
                phases[0],
                notification(
                    "completed", [change()], status="completed", turn="foreign"
                ),
            ],
        ]
        for value in invalid:
            with (
                self.subTest(value=value),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                project(value)
        outside = events([]) + [notification("patch_updated", [change()])]
        with self.assertRaises(adapter.EvidenceUnavailable):
            adapter.native_commands(
                capture(outside), compressed=False, thread_id="thread"
            )
        for phase in (
            notification("patch_updated", [change()], thread=None),
            notification("started", [change()], status="inProgress", thread=""),
        ):
            with (
                self.subTest(phase=phase),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                project([phase])

    def test_mutation_notifications_cannot_hide_behind_rpc_ids(self):
        for rows in ([notification("patch_updated", [change()])], self.phases()):
            for identity in (None, 1, "foreign"):
                altered = copy.deepcopy(rows)
                for _, value in altered:
                    value["id"] = identity
                with (
                    self.subTest(rows=rows, identity=identity),
                    self.assertRaises(adapter.EvidenceUnavailable),
                ):
                    project(altered)

    def test_snake_case_rename_schema_missing_diff_and_unknown_fields_fail_closed(self):
        variants = [
            dict(
                path="/reference/executable",
                kind={"type": "update", "movePath": "/moved"},
                diff="",
            ),
            dict(path="/reference/executable", kind={"type": "update"}, diff=""),
            dict(path="/reference/executable", kind={"type": "future"}, diff=""),
            dict(path="/reference/executable", kind={"type": "delete"}),
            dict(path="/reference/executable", kind={"type": "add"}, diff=1),
            {**change(), "unknown": True},
            change("x" * 4097),
            change(kind={"type": "update", "move_path": "x" * 4097}),
        ]
        for row in variants:
            with self.subTest(row=row), self.assertRaises(adapter.EvidenceUnavailable):
                project([notification("patch_updated", [row])])
        value = notification("patch_updated", [change()])
        value[1]["params"]["status"] = "inProgress"
        with self.assertRaises(adapter.EvidenceUnavailable):
            project([value])
        with self.assertRaises(adapter.EvidenceUnavailable):
            project([notification("patch_updated", [change(), change()])])

    def test_status_mismatch_and_byte_count_caps_fail_closed(self):
        for status in (None, "running", "completed"):
            with (
                self.subTest(status=status),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                project(
                    [
                        notification("started", [change()], status=status),
                        self.phases()[1],
                    ]
                )
        for name, maximum in (("MAX_BYTES", 80), ("MAX_PHASES", 1), ("MAX_CHANGES", 0)):
            with (
                patch.object(mutations, name, maximum),
                self.assertRaises(adapter.EvidenceUnavailable),
            ):
                project(self.phases())
        _, receipt = project([notification("patch_updated", [change("\\" * 100)])])
        with patch.object(mutations, "MAX_BYTES", 100), self.assertRaises(ValueError):
            mutations.encode(receipt["typed_mutations"])

    def test_foreign_thread_is_out_of_scope_and_id_reuse_is_scoped_by_turn(self):
        _, receipt = project(
            [notification("patch_updated", [change()], thread="other")]
        )
        self.assertEqual(receipt["typed_mutations"], [])
        raw = events(self.phases())
        repair = native_events()
        for outgoing, value in repair:
            if outgoing or "id" in value:
                continue
            params = value["params"]
            if "turn" in params:
                params["turn"]["id"] = "repair"
            if "turnId" in params:
                params["turnId"] = "repair"
        repair = [row for row in repair if not row[0] and "id" not in row[1]]
        repairs = [
            notification("started", [change()], status="inProgress", turn="repair"),
            notification("completed", [change()], status="declined", turn="repair"),
        ]
        _, receipt = adapter.native_commands(
            capture(raw + repair[:-1] + repairs + repair[-1:]),
            compressed=False,
            thread_id="thread",
        )
        self.assertEqual(
            [row["turn_id"] for row in receipt["typed_mutations"]],
            ["turn", "turn", "repair", "repair"],
        )

    def test_future_adapter_supplies_separate_mutation_pack_and_binds_protocol(self):
        fixture = adapter_fixtures.AssemblyTests(
            methodName="test_delegated_authentication_projection_and_private_receipt_binding"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.run / "app-server.jsonl").write_bytes(
            capture(events(self.phases("declined")))
        )
        pack, receipt = fixture.assemble()
        source = next(
            raw
            for meta, raw in pack._sources.values()
            if meta["kind"] == "typed_mutations"
        )
        self.assertEqual(json.loads(source), receipt["capture"]["typed_mutations"])
        self.assertNotIn(b"PRIVATE DIFF CONTENT", source)
        self.assertEqual(
            [row["status"] for row in json.loads(source)], ["inProgress", "declined"]
        )
        baseline = evidence_fixtures.EvidenceTests(
            methodName="test_all_five_requirements_have_exact_coverage"
        )
        baseline.setUp()
        self.addCleanup(baseline.doCleanups)
        self.addCleanup(baseline.directory.cleanup)
        bound = baseline.pack(typed_mutations=json.loads(source))
        self.assertNotEqual(bound.digest, baseline.pack(typed_mutations=[]).digest)
        malformed = json.loads(source)
        malformed[1]["phase"] = "patch_updated"
        with self.assertRaises(ValueError):
            baseline.pack(typed_mutations=malformed)


if __name__ == "__main__":
    unittest.main()
