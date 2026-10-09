"""No models: exercise operator-pinned DATA imports, not checkpoint truth certification."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import procontract_checkpoint as checkpoint
import procontract_rsi as rsi
import procontract_store as store


def write_json(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def reseal(root):
    cp = json.loads((root / "CHECKPOINT.json").read_text())
    entries = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_file() and name not in ("MANIFEST.json", "SEAL.json"):
            raw = path.read_bytes()
            entries[name] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "export_mode": oct(path.stat().st_mode & 0o777),
                "source_path": "/nonexistent/provenance/not/read",
            }
    total = sum(e["bytes"] for e in entries.values())
    write_json(
        root,
        "MANIFEST.json",
        {
            "schema": 1,
            "artifact_kind": "verified_checkpoint_data_only",
            "entries": entries,
            "payload_bytes": total,
            "payload_file_count": len(entries),
            "source_incumbent": cp["incumbent"]["id"],
            "source_knowledge_digest": cp["knowledge"]["digest"],
        },
    )
    pin = hashlib.sha256((root / "MANIFEST.json").read_bytes()).hexdigest()
    exposure = json.loads(
        (root / "operator-metadata/complete-conservative-exposure.json").read_text()
    )
    write_json(
        root,
        "SEAL.json",
        {
            "schema": 1,
            "manifest_sha256": pin,
            "incumbent": cp["incumbent"]["id"],
            "knowledge_digest": cp["knowledge"]["digest"],
            "payload_file_count": len(entries),
            "payload_bytes": total,
            "confirmation_exclusions": len(
                exposure["confirmation_prohibited_tasks_conservative"]
            ),
            "operator_exposed_task_count": len(exposure["operator_exposed_tasks"]),
        },
    )
    return pin


def make_checkpoint(root, *, native_sha256="a" * 64, model="gpt-5.6-luna", bundle=None):
    """Small internally consistent operator fixture; no historical validity claim."""
    root.mkdir()
    bundle = rsi.V0_BUNDLE if bundle is None else bundle
    target = root / "incumbent/bundle"
    target.mkdir(parents=True)
    texts = {}
    for role in checkpoint.ROLES:
        name = f"{role}.md"
        texts[name] = (bundle / name).read_text()
        (target / name).write_text(texts[name])
    version = {
        "schema": 1,
        "binary": native_sha256,
        "model": {"id": model, "effort": "max"},
        "bundle": {
            name: store.digest("bundle_file", text) for name, text in texts.items()
        },
        "lineage": {"parent": "b" * 64, "proposed_by": "b" * 64},
    }
    vid = store.digest("version", version)
    contract_id = f"adoption.{vid[:16]}"
    write_json(root, "incumbent/manifest.json", version)
    learned = {
        "mechanisms.md": "Qualified synthetic knowledge, not operator metadata.\n"
    }
    for name, value in learned.items():
        path = root / "knowledge" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(value)
    knowledge_digest = store.digest("knowledge", learned)
    evidence = {
        "class": "paired_updater_v1",
        "descendants": {"control": "c" * 64, "candidate": "d" * 64},
        "mean_delta": 0.1,
        "wins": 3,
        "passed": True,
        "pairs": {"fixture__spent.123abcd": [1.0, 0.9]},
    }
    coordinate = {
        "contract_id": contract_id,
        "subject_hash": vid,
        "evidence_hash": store.digest("evidence", evidence),
    }
    settlement = {
        "coordinate": coordinate,
        "attestation": "f" * 64,
        "decision": {"type": "presumed"},
    }
    state = {
        "version": 4,
        "id": contract_id,
        "standing": "discharged",
        "candidate": {"subject_hash": vid},
        "support": {"coordinate": coordinate},
        "settlement": settlement,
    }
    write_json(
        root,
        "evidence/store/contracts.json",
        {contract_id: {"version": 4, "state": state}},
    )
    write_json(
        root,
        "evidence/store/contract-events.json",
        [
            {
                "contract_id": contract_id,
                "command_json": json.dumps(
                    {
                        "contract_id": contract_id,
                        "expected_version": 3,
                        "role": "settler",
                        "provenance": "delegate",
                        "command": {"type": "discharge", **settlement},
                    }
                ),
            }
        ],
    )
    identity = {
        "parent": vid,
        "coverage": ["synthetic-run"],
        "evidence": "1" * 64,
        "protocol": "2" * 64,
        "experiment": None,
    }
    insight = {
        "status": "qualified",
        "analysis_identity": identity,
        "prior_knowledge": "3" * 64,
        "knowledge_digest": knowledge_digest,
    }
    bodies = [
        ("version", {"id": vid, "manifest": version}),
        (
            "assignment",
            {
                "class": "paired_updater_v1",
                "confirmation": vid,
                "incumbent": "b" * 64,
                "input": {"subject": "4" * 64},
            },
        ),
        (
            "selection",
            {
                "role": "method_confirmation_evidence",
                "confirmation": vid,
                "evidence": evidence,
            },
        ),
        ("selection", {"role": "incumbent", "adoption": contract_id, "version": vid}),
        ("insight", insight),
    ]
    identities = {"harness": native_sha256, "model": model, "effort": "max"}
    events = [
        {
            "seq": seq,
            "event_json": json.dumps(
                {"kind": kind, "body": body, "identities": identities}
            ),
        }
        for seq, (kind, body) in enumerate(bodies, 1)
    ]
    write_json(root, "evidence/store/experiment-events.json", events)
    write_json(
        root,
        "evidence/qualified-insight/coverage.json",
        {**identity, "prior_knowledge": insight["prior_knowledge"]},
    )
    feedback = {
        "class": "paired_updater_v1",
        "method": vid,
        "comparator": "b" * 64,
        "common_input": "4" * 64,
        "selection_unit": "one paired updater episode; not independent method replications",
        "adoption_subject": "method only, not a descendant task policy",
        "outcome": "evaluated",
        "tasks": len(evidence["pairs"]),
        **{
            key: evidence[key]
            for key in ("descendants", "mean_delta", "wins", "passed")
        },
    }
    write_json(root, "learned-feedback/method-trial.json", feedback)
    excluded, operator = (
        ["fixture__spent.123abcd"],
        ["fixture__spent.123abcd", "fixture__operator.456abcd"],
    )
    exposure = {
        "confirmation_prohibited_tasks_conservative": excluded,
        "operator_exposed_tasks": operator,
        "confirmation_prohibited_repositories_conservative": ["fixture__spent"],
        "counts": {
            "confirmation_prohibited_tasks_conservative": 1,
            "operator_exposed_tasks": 2,
        },
    }
    for name in (
        "historical_blocked_prior_tasks",
        "all_v1_declared_tasks",
        "all_v2_declared_tasks",
        "cumulative_actual_rollout_tasks",
        "current_v2_learner_consumed_tasks",
    ):
        exposure[name] = excluded
    write_json(root, "operator-metadata/complete-conservative-exposure.json", exposure)
    write_json(root, "operator-metadata/audit.json", {"host_only": True})
    write_json(
        root,
        "provenance/v2/campaign.json",
        {"model": model, "effort": "max", "codex_sha256": native_sha256},
    )
    write_json(root, "provenance/v2/study.json", {"synthetic": True})
    write_json(root, "evidence/unadopted-M2/manifest.json", {"must_not_import": True})
    write_json(
        root,
        "CHECKPOINT.json",
        {
            "schema": 1,
            "artifact_kind": "verified_checkpoint_data_only",
            "new_promotion": False,
            "incumbent": {
                "id": vid,
                "bundle": "incumbent/bundle",
                "manifest": "incumbent/manifest.json",
                "adoption_contract": contract_id,
                "contract_version": 4,
                "standing": "discharged",
                "selection_seq": 4,
            },
            "knowledge": {
                "path": "knowledge",
                "digest": knowledge_digest,
                "files": len(learned),
                "bytes": sum(len(v.encode()) for v in learned.values()),
                "parent": vid,
                "qualified_event_seq": 5,
            },
            "method_feedback": "learned-feedback/method-trial.json",
            "last_event_seq": 5,
            "source_study_sha256": hashlib.sha256(
                (root / "provenance/v2/study.json").read_bytes()
            ).hexdigest(),
        },
    )
    return reseal(root)


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp) / "checkpoint"
        self.pin = make_checkpoint(self.root)

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def changed(self, name, change):
        value = self.read(name)
        change(value)
        write_json(self.root, name, value)
        self.pin = reseal(self.root)

    def load(self):
        return checkpoint.load(self.root, self.pin)

    def terms(self):
        return {
            "model": "gpt-5.6-luna",
            "effort": "max",
            "codex_sha256": "a" * 64,
            "pools": {"confirm": []},
            "checkpoint": {"path": str(self.root), **self.load().descriptor()},
        }

    def test_selects_only_incumbent_qualified_knowledge_and_attributed_feedback(self):
        value = self.load()
        self.assertEqual(
            (
                value.bundle,
                value.knowledge,
                value.feedback_files,
                value.required_paths(),
            ),
            (
                self.root / "incumbent/bundle",
                self.root / "knowledge",
                (self.root / "learned-feedback/method-trial.json",),
                (self.root,),
            ),
        )
        self.assertEqual(value.excluded_tasks, ("fixture__spent.123abcd",))
        self.assertEqual(
            value.operator_exposed_tasks,
            ("fixture__operator.456abcd", "fixture__spent.123abcd"),
        )
        self.assertFalse(value.descriptor()["new_promotion"])
        self.assertNotIn("source_path", json.dumps(value.descriptor()))
        self.assertNotIn("M2", json.dumps(value.descriptor()))

    def test_external_pin_is_required_and_not_taken_from_seal(self):
        for pin in (None, "", "a" * 64):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                checkpoint.load(self.root, pin)

    @unittest.skipUnless(os.name == "posix", "POSIX executable bits")
    def test_pinned_executable_bits_cannot_drift_before_import(self):
        path = self.root / "knowledge/mechanisms.md"
        original = path.stat().st_mode
        path.chmod(original | 0o100)
        with self.assertRaisesRegex(ValueError, "executable mode"):
            self.load()
        path.chmod(original & ~0o222)
        self.load()  # Read-only relocation does not change learned tool semantics.

    def test_unpinned_content_change_and_extra_file_rejected(self):
        for path in (self.root / "knowledge/mechanisms.md", self.root / "extra.txt"):
            original = path.read_bytes() if path.exists() else None
            path.write_text("tampered")
            with self.assertRaises(ValueError):
                self.load()
            if original is None:
                path.unlink()
            else:
                path.write_bytes(original)

    def test_linked_file_directory_and_hardlink_rejected(self):
        path = self.root / "knowledge/mechanisms.md"
        original = path.read_bytes()
        outside = Path(self.temp) / "outside"
        outside.write_bytes(original)
        for link in (lambda: path.symlink_to(outside), lambda: os.link(outside, path)):
            path.unlink()
            link()
            with self.assertRaisesRegex(ValueError, "regular"):
                self.load()
            path.unlink()
            path.write_bytes(original)
        linked = Path(self.temp) / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "linked"):
            checkpoint.load(linked, self.pin)

    def test_file_count_byte_caps(self):
        for name, limit in (
            ("MAX_FILES", 2),
            ("MAX_FILE_BYTES", 32),
            ("MAX_TOTAL_BYTES", 32),
        ):
            with (
                self.subTest(cap=name),
                mock.patch.object(checkpoint, name, limit),
                self.assertRaises(ValueError),
            ):
                self.load()

    def test_tree_depth_traversal_and_special_file_rejected(self):
        deep = self.root.joinpath(*(["nested"] * 21))
        deep.mkdir(parents=True)
        (deep / "extra").write_text("x")
        with self.assertRaisesRegex(ValueError, "deep"):
            self.load()
        shutil.rmtree(self.root / "nested")
        with self.assertRaisesRegex(ValueError, "traversal"):
            checkpoint.load(self.root / ".." / "checkpoint", self.pin)
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.root / "pipe")
            with self.assertRaisesRegex(ValueError, "regular"):
                self.load()

    def test_resealed_inventory_path_and_counts_rejected(self):
        value = self.read("MANIFEST.json")
        value["payload_file_count"] += 1
        write_json(self.root, "MANIFEST.json", value)
        self.pin = hashlib.sha256(
            (self.root / "MANIFEST.json").read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "counts"):
            self.load()
        self.pin = reseal(self.root)
        value = self.read("MANIFEST.json")
        value["entries"]["../escape"] = value["entries"].pop("CHECKPOINT.json")
        write_json(self.root, "MANIFEST.json", value)
        self.pin = hashlib.sha256(
            (self.root / "MANIFEST.json").read_bytes()
        ).hexdigest()
        with self.assertRaises(ValueError):
            self.load()

    def test_duplicate_and_nonfinite_json_rejected(self):
        for raw in ('{"schema":1,"schema":1}', '{"score":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checkpoint._json(raw)

    def test_huge_claimed_event_count_fails_before_allocation(self):
        self.changed(
            "CHECKPOINT.json", lambda value: value.update(last_event_seq=10**100)
        )
        with self.assertRaisesRegex(ValueError, "event count"):
            self.load()

    def test_resealed_wrong_incumbent_and_unqualified_knowledge_rejected(self):
        for field, mutation in (
            ("incumbent", {"id": "9" * 64}),
            ("knowledge", {"qualified_event_seq": 1}),
        ):
            old = self.read("CHECKPOINT.json")
            self.changed("CHECKPOINT.json", lambda value: value[field].update(mutation))
            with self.assertRaises(ValueError):
                self.load()
            write_json(self.root, "CHECKPOINT.json", old)
            self.pin = reseal(self.root)

    def test_resealed_unsettled_contract_rejected(self):
        self.changed(
            "evidence/store/contracts.json",
            lambda value: next(iter(value.values()))["state"].update(
                standing="outstanding"
            ),
        )
        with self.assertRaisesRegex(ValueError, "discharged"):
            self.load()

    def test_resealed_wrong_feedback_attribution_and_score_rejected(self):
        for field, bad in (
            ("method", "9" * 64),
            ("comparator", "9" * 64),
            ("common_input", "9" * 64),
            ("wins", 0),
        ):
            old = self.read("learned-feedback/method-trial.json")
            self.changed(
                "learned-feedback/method-trial.json",
                lambda value: value.update({field: bad}),
            )
            with self.assertRaises(ValueError):
                self.load()
            write_json(self.root, "learned-feedback/method-trial.json", old)
            self.pin = reseal(self.root)

    def test_resealed_exposure_shrink_rejected(self):
        def shrink(value):
            value["confirmation_prohibited_tasks_conservative"] = []
            value["counts"]["confirmation_prohibited_tasks_conservative"] = 0

        self.changed("operator-metadata/complete-conservative-exposure.json", shrink)
        with self.assertRaisesRegex(ValueError, "exposure"):
            self.load()

    def test_new_campaign_descriptor_and_profile_bound(self):
        terms = self.terms()
        self.assertEqual(
            checkpoint.from_terms(terms).descriptor(), self.load().descriptor()
        )
        self.assertIsNone(checkpoint.from_terms({}))
        for field, wrong in (("model", "different"), ("codex_sha256", "b" * 64)):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "profile"),
            ):
                checkpoint.from_terms({**terms, field: wrong})
        terms["checkpoint"]["new_promotion"] = True
        with self.assertRaisesRegex(ValueError, "descriptor"):
            checkpoint.from_terms(terms)

    def test_campaign_excludes_same_repo_and_carries_all_disclosure(self):
        value, terms = self.load(), self.terms()
        terms["pools"]["confirm"] = ["FIXTURE__spent.fffffff"]
        with self.assertRaisesRegex(ValueError, "inherited exposure"):
            value.validate_campaign(terms)
        terms["pools"]["confirm"] = ["fixture__fresh.fffffff"]
        registry = SimpleNamespace(
            exposed_tasks=value.excluded_tasks,
            operator_exposed_tasks=value.operator_exposed_tasks,
            validate_campaign=lambda _: None,
        )
        value.validate_campaign(terms, registry)
        registry.operator_exposed_tasks = ()
        with self.assertRaisesRegex(ValueError, "disclosure"):
            value.validate_campaign(terms, registry)
        registry.operator_exposed_tasks = value.operator_exposed_tasks
        registry.exposed_tasks = ()
        with self.assertRaisesRegex(ValueError, "exclusions"):
            value.validate_campaign(terms, registry)

    def test_relocated_regular_copy_has_same_semantic_descriptor(self):
        moved = Path(self.temp) / "relocated"
        shutil.copytree(self.root, moved)
        self.assertEqual(
            checkpoint.load(moved, self.pin).descriptor(), self.load().descriptor()
        )


if __name__ == "__main__":
    unittest.main()
