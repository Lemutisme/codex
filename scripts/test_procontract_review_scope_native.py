"""Actual bounded repair with a persistent independent scope dispute, no paid model."""
import os
import unittest
import test_procodex_native as fixture


@unittest.skipUnless(os.environ.get("PROCODEX_NATIVE_PACKAGE"), "requires qualified native package")
class NativeReviewScopeTests(unittest.TestCase):
    def test_unaffected_failure_is_repaired_without_accepting_disputed_terms(self):
        case=fixture.NativeEvidenceTest("test_real_executor_and_reviewer_use_frozen_handles")
        case.scoped_review_fixture=True
        case.debug()


if __name__ == "__main__": unittest.main()
