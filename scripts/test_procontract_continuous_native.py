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

    def test_same_turn_publication_feedback_repair_and_final_acceptance(self):
        self.run_case(progress_fixture=True)

    def test_selected_strategy_and_requested_diagnosis_with_readonly_inputs(self):
        self.run_case(progress_fixture=True,diagnostic_review_fixture=True,input_strategy_fixture=True)

    def test_readonly_inputs_and_strategy_survive_a_successor(self):
        self.run_case(succession_fixture=True,input_strategy_fixture=True)

    def test_native_feedback_access_is_available_as_scoped_process_evidence(self):
        self.run_case(progress_fixture=True, observation_fixture=True,
            task_text="Make answer.txt contain ready. Obtain the retained feedback bytes before repairing the artifact.")

    def test_missing_access_is_a_real_gap_without_false_support(self):
        self.run_case(progress_fixture=True, observation_fixture=True, missing_access_fixture=True,
            task_text="Make answer.txt contain ready. Obtain the retained feedback bytes before repairing the artifact.")

    def test_successor_access_is_observed_under_the_original_responsibility(self):
        self.run_case(succession_fixture=True, observation_fixture=True,
            task_text="Make answer.txt contain ready. Obtain the retained feedback bytes before repairing the artifact.")

    def test_one_protocol_correction_preserves_the_review_session_and_evidence(self):
        self.run_case(protocol_correction_fixture=True)

    def test_protocol_correction_exhaustion_remains_unknown_without_more_attempts(self):
        self.run_case(correction_exhausted_fixture=True)

    def test_final_response_and_successful_check_are_native_review_evidence(self):
        self.run_case(delivery_evidence_fixture=True)

    def test_host_checker_execution_can_support_an_execution_obligation(self):
        self.run_case(check_execution_fixture=True,
            task_text="Make answer.txt contain ready. Run the configured check.")

    def test_successor_delivers_actual_response_beyond_its_continuation_summary(self):
        self.run_case(delivery_evidence_fixture=True, succession_fixture=True)

    def test_output_limit_keeps_protocol_and_same_turn_progress_usable(self):
        self.run_case(progress_fixture=True, resource_limit_fixture=True)

    def test_progress_review_retains_a_required_unknown_without_false_acceptance(self):
        self.run_case(progress_fixture=True, partial_review_fixture=True,
            task_text="Make answer.txt contain ready. Check the supplied numerical attachment without assuming its correctness.")

    def test_successor_can_publish_under_the_original_task_grant(self):
        self.run_case(succession_fixture=True, successor_progress_fixture=True)

    def test_original_deadline_stops_the_first_turn_and_its_background_effects(self):
        self.run_case(deadline_fixture=True)

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
