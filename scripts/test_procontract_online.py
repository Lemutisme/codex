"""Learning authority and two-generation lineage tests, without any inference."""

import copy
import json
import unittest

import procontract_online as online


def candidate(program, suffix):
    result = copy.deepcopy(program)
    result["execution"] += f" Check {suffix}."
    result["research"] += (
        f" Test the {suffix} explanation before adding another change."
    )
    result["harness"]["when"] = {"completed_turns_lte": 2}
    return result, online.encoded(
        {
            "execution": result["execution"],
            "research": result["research"],
            "harness_json": json.dumps(result["harness"]),
            "mechanism": f"Observed failure {suffix} motivates a discriminating check.",
            "prediction": "The next executor action runs a discriminating check.",
        }
    )


class ProgramTests(unittest.TestCase):
    def test_harness_is_executable_but_cannot_acquire_capabilities(self):
        value = online.seed()
        loaded = online.parse(online.encoded(value))
        program = online.harness.parse(online.encoded(loaded["harness"]))
        facts = {
            "deadline_secs": 100,
            "remaining_secs": 80,
            "turns_completed": 1,
            "repairs_used": 0,
            "executor_command_completions_observed": 3,
        }
        self.assertFalse(program.evaluate(facts))
        self.assertTrue(program.evaluate({**facts, "remaining_secs": 70}))
        for replacement in (
            {"schema": 3, "action": "exec", "when": {"always": True}},
            {"schema": 3, "action": "checkpoint", "when": {"import": "os"}},
            {"schema": 1, "when": {"always": True}},
        ):
            with self.assertRaises(ValueError):
                online.parse(online.encoded({**value, "harness": replacement}))

    def test_duplicate_keys_unknown_fields_oversize_and_nonfinite_are_rejected(self):
        _, good = candidate(online.seed(), "one")
        value = json.loads(good)
        for raw in (
            b'{"schema":1,"schema":1}',
            online.encoded({**value, "reward": 1}),
            online.encoded({**value, "research": "x" * 1601}),
            b"NaN",
            b"x" * 7001,
        ):
            with self.subTest(raw=raw[:60]):
                with self.assertRaises((ValueError, TypeError)):
                    online.proposal(raw)


if __name__ == "__main__":
    unittest.main()
