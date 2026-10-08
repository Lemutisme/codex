import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import procontract_harness_program as program


class HarnessProgramTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bundle = Path(directory.name)
        self.path = self.bundle / program.PROGRAM_FILE
        self.facts = {
            "deadline_secs": 100,
            "remaining_secs": 30,
            "turns_completed": 0,
            "repairs_used": 0,
        }

    def load(self, predicate):
        self.path.write_text(
            json.dumps({"schema": 1, "when": predicate}), encoding="utf-8"
        )
        return program.load(self.bundle)

    def test_one_program_changes_decision_with_time_and_turn_facts(self):
        loaded = self.load(
            {
                "all": [
                    {"remaining_fraction_lte": [1, 4]},
                    {"any": [{"completed_turns_lte": 0}, {"repairs_used_gte": 1}]},
                    {"not": {"always": False}},
                ]
            }
        )
        decisions = [loaded.evaluate(self.facts)]
        for remaining, completed, repairs in [(25, 0, 0), (24, 1, 0), (24, 1, 1)]:
            self.facts.update(
                remaining_secs=remaining,
                turns_completed=completed,
                repairs_used=repairs,
            )
            decisions.append(loaded.evaluate(self.facts))
        self.assertEqual(decisions, [False, True, False, True])

    def test_fraction_uses_exact_integer_comparison(self):
        loaded = self.load({"remaining_fraction_lte": [1, 3]})
        self.assertEqual(
            [
                loaded.evaluate({**self.facts, "remaining_secs": value})
                for value in (33, 34)
            ],
            [True, False],
        )

    def test_identity_is_exact_source_bytes_not_normalized_json(self):
        self.load({"always": True})
        raw = self.path.read_bytes() + b"\n"
        self.path.write_bytes(raw)
        self.assertEqual(
            program.load(self.bundle).digest, hashlib.sha256(raw).hexdigest()
        )

    def test_loaded_program_keeps_the_validated_bytes_after_the_file_changes(self):
        loaded = self.load({"remaining_fraction_lte": [1, 4]})
        original = self.path.read_bytes()
        self.load({"always": True})
        self.assertEqual(
            (loaded.source, loaded.digest, loaded.evaluate(self.facts)),
            (original, hashlib.sha256(original).hexdigest(), False),
        )

    def test_missing_is_optional_but_link_and_nonregular_are_rejected(self):
        self.assertIsNone(program.load(None))
        self.assertIsNone(program.load(self.bundle))
        self.path.mkdir()
        with self.assertRaises(ValueError):
            program.load(self.bundle)
        self.path.rmdir()
        target = self.bundle / "other.json"
        target.write_text('{"schema":1,"when":{"always":true}}')
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        with self.assertRaises(ValueError):
            program.load(self.bundle)
        target.unlink()
        with self.assertRaises(ValueError):
            program.load(self.bundle)

    def test_shared_reader_returns_only_a_bounded_regular_file_snapshot(self):
        self.assertIsNone(program.read_regular(self.path, 5))
        self.path.write_bytes(b"source")
        self.assertEqual(program.read_regular(self.path, 6), b"source")
        with self.assertRaises(ValueError):
            program.read_regular(self.path, 5)

    def test_bundle_root_cannot_be_a_file_or_link(self):
        self.assertIsNone(program.load(self.bundle / "missing"))
        self.load({"always": True})
        with self.assertRaises(ValueError):
            program.load(self.path)
        alias = self.bundle / "alias"
        try:
            alias.symlink_to(self.bundle, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        with self.assertRaises(ValueError):
            program.load(alias)

    def test_all_branches_are_validated_before_execution(self):
        invalid = [
            {"unknown": 1},
            {"always": 1},
            {"completed_turns_lte": True},
            {"repairs_used_gte": -1},
            {"remaining_fraction_lte": [1, 0]},
            {"remaining_fraction_lte": [False, 2]},
            {"all": {}},
            {"always": True, "not": {"always": False}},
            {"completed_turns_lte": program.MAX_INTEGER + 1},
        ]
        for node in invalid:
            with self.subTest(node=node), self.assertRaises(ValueError):
                self.load({"any": [{"always": True}, node]})

    def test_json_is_strict_at_every_level(self):
        for raw in [
            b'{"schema":1,"schema":1,"when":{"always":true}}',
            b'{"schema":1,"when":{"always":true,"always":false}}',
            b'{"schema":true,"when":{"always":true}}',
            b'{"schema":1,"when":{"completed_turns_lte":1.0}}',
            b'{"schema":1,"when":{"completed_turns_lte":NaN}}',
            b'{"schema":1,"when":{"completed_turns_lte":Infinity}}',
            b'{"schema":1,"when":{"always":true},"extra":0}',
            b"\xff",
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.path.write_bytes(raw)
                program.load(self.bundle)

    def test_byte_depth_and_node_limits_apply_at_the_boundary(self):
        self.load({"always": True})
        self.path.write_bytes(self.path.read_bytes().ljust(program.MAX_BYTES, b" "))
        self.assertTrue(program.load(self.bundle).evaluate(self.facts))
        self.path.write_bytes(self.path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            program.load(self.bundle)
        node = {"always": True}
        for _ in range(program.MAX_DEPTH - 1):
            node = {"not": node}
        self.load(node)
        with self.assertRaises(ValueError):
            self.load({"not": node})
        self.load({"all": [{"always": True}] * (program.MAX_NODES - 1)})
        with self.assertRaises(ValueError):
            self.load({"all": [{"always": True}] * program.MAX_NODES})

    def test_facts_are_exact_and_validated_even_for_an_always_program(self):
        loaded = self.load({"always": True})
        invalid = [{}, {**self.facts, "extra": 0}, {**self.facts, "deadline_secs": 0}]
        invalid += [
            {**self.facts, key: value}
            for key in self.facts
            for value in (True, -1, 1.0, program.MAX_INTEGER + 1)
        ]
        for facts in invalid:
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                loaded.evaluate(facts)
