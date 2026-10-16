"""Real native work/evidence continuations; scripted local provider, no paid inference."""
import os
import unittest
import test_procodex_native as fixture


@unittest.skipUnless(os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
                     "requires a native package and an existing isolated image")
class ContinuousNativeTests(unittest.TestCase):
    def run_case(self, **flags):
        case=fixture.NativeEvidenceTest("test_real_executor_and_reviewer_use_frozen_handles")
        for name,value in flags.items():setattr(case,name,value)
        case.debug()

    def test_binary_computation_uses_the_frozen_subject_and_real_citation(self):
        self.run_case(computation_fixture=True)

    def test_partial_review_repairs_an_independent_failure_without_false_support(self):
        self.run_case(partial_review_fixture=True,
            task_text="Make answer.txt contain ready. Check the supplied numerical attachment without assuming its correctness.")

    def test_reactive_dialogue_survives_observation_handoff_and_successor_execution(self):
        self.run_case(dialogue_probe_fixture=True,probe_fixture=True,succession_fixture=True)

    def test_interrupted_check_keeps_counterexample_and_complete_replay_in_same_contract(self):
        self.run_case(dialogue_probe_fixture=True,probe_fixture=True,succession_fixture=True,partial_checks_fixture=True)


if __name__=='__main__':unittest.main()
