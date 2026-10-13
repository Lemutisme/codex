"""Native failure → fresh executor → independent support; localhost scripted provider only."""

import os
import unittest

import test_procodex_native as fixture


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
    "requires native package and existing Docker image, no paid model",
)
class NativeSuccessionTests(unittest.TestCase):
    def test_failed_handoff_gets_a_new_session_not_a_new_responsibility(self):
        case = fixture.NativeEvidenceTest(
            "test_real_executor_and_reviewer_use_frozen_handles"
        )
        case.succession_fixture = True
        case.debug()


if __name__ == "__main__":
    unittest.main()
