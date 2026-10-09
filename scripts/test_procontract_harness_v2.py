import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import procontract_harness_program as program


class HarnessV2Test(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bundle = Path(directory.name)
        self.path = self.bundle / program.PROGRAM_FILE
        self.facts = dict(
            deadline_secs=100, remaining_secs=25, turns_completed=0, repairs_used=1
        )
        self.v2_facts = {**self.facts, "executor_command_completions_observed": 2}

    def load(self, predicate, **fields):
        document = {"schema": 2, "action": "checkpoint", "when": predicate, **fields}
        self.path.write_text(json.dumps(document), encoding="utf-8")
        return program.load(self.bundle)

    def test_versions_actions_and_exact_source_identity(self):
        default = program.Program("digest", ("always", True), b"source")
        self.assertEqual(
            (default.schema, default.action, default.interpreter),
            (1, "converge", "convergence-v1"),
        )
        for action in ("checkpoint", "converge"):
            with self.subTest(action=action):
                self.load({"always": True}, action=action)
                raw = self.path.read_bytes() + b"\n"
                self.path.write_bytes(raw)
                loaded = program.load(self.bundle)
                self.path.write_bytes(b"changed after validation")
                self.assertEqual(
                    (
                        loaded.schema,
                        loaded.action,
                        loaded.interpreter,
                        loaded.source,
                        loaded.digest,
                        loaded.evaluate(self.v2_facts),
                    ),
                    (
                        2,
                        action,
                        "bounded-steering-v2",
                        raw,
                        hashlib.sha256(raw).hexdigest(),
                        True,
                    ),
                )

    def test_v2_command_completion_threshold_combines_with_existing_ast(self):
        loaded = self.load(
            {
                "all": [
                    {"command_completions_observed_gte": 2},
                    {"remaining_fraction_lte": [1, 4]},
                    {"any": [{"completed_turns_lte": 0}, {"repairs_used_gte": 1}]},
                    {"not": {"always": False}},
                ]
            }
        )
        self.assertEqual(
            [
                loaded.evaluate(
                    {**self.v2_facts, "executor_command_completions_observed": n}
                )
                for n in (0, 1, 2, program.MAX_INTEGER)
            ],
            [False, False, True, True],
        )
        for value in (True, -1, 1.0, program.MAX_INTEGER + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(
                    {
                        "any": [
                            {"always": True},
                            {"command_completions_observed_gte": value},
                        ]
                    }
                )

    def test_closed_schema_action_and_operation_spaces(self):
        valid = {"schema": 2, "action": "checkpoint", "when": {"always": True}}
        invalid = [
            {key: value for key, value in valid.items() if key != missing}
            for missing in valid
        ] + [
            {**valid, "extra": 0},
            {"schema": 1, "when": {"command_completions_observed_gte": 0}},
            {**valid, "schema": 1},
            {**valid, "when": {"unknown": 0}},
        ]
        invalid += [{**valid, "schema": value} for value in (0, 4, True, "2", [], {})]
        invalid += [
            {**valid, "action": value}
            for value in ("", "unknown", ["checkpoint"], {}, None, True, 2)
        ]
        for document in invalid:
            with self.subTest(document=document), self.assertRaises(ValueError):
                self.path.write_text(json.dumps(document), encoding="utf-8")
                program.load(self.bundle)

    def test_exact_fact_sets_and_bounded_integer_completion_fact(self):
        v2 = self.load({"always": True})
        self.path.write_text('{"schema":1,"when":{"always":true}}', encoding="utf-8")
        v1 = program.load(self.bundle)
        self.assertEqual(
            (v1.evaluate(self.facts), v2.evaluate(self.v2_facts)), (True, True)
        )
        invalid = [
            self.facts,
            {**self.v2_facts, "extra": 0},
            {**self.v2_facts, "deadline_secs": 0},
        ]
        invalid += [
            {**self.v2_facts, key: value}
            for key in self.v2_facts
            for value in (True, -1, 1.0, program.MAX_INTEGER + 1)
        ]
        for facts in invalid:
            with self.subTest(facts=facts), self.assertRaises(ValueError):
                v2.evaluate(facts)
        with self.assertRaises(ValueError):
            v1.evaluate(self.v2_facts)

    def test_v2_strict_json_rejects_duplicate_keys_and_noninteger_numbers(self):
        for suffix in (
            '"always":true,"always":false',
            '"command_completions_observed_gte":1.0',
            '"command_completions_observed_gte":NaN',
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.path.write_text(
                    '{"schema":2,"action":"checkpoint","when":{' + suffix + "}}"
                )
                program.load(self.bundle)
        with self.assertRaises(ValueError):
            self.path.write_text(
                '{"schema":2,"action":"checkpoint","action":"converge","when":{"always":true}}'
            )
            program.load(self.bundle)

    def test_v2_retains_byte_depth_and_node_boundaries(self):
        self.load({"always": True})
        self.path.write_bytes(self.path.read_bytes().ljust(program.MAX_BYTES, b" "))
        self.assertTrue(program.load(self.bundle).evaluate(self.v2_facts))
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
