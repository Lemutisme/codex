"""Real kernel revocations invalidate guarded work even without a new selection event."""

import unittest
from unittest import mock

import procontract_store as store
import procontract_succession as succession
import test_procontract_guarded_stream as fixtures


class GuardedRevocationTest(unittest.TestCase):
    make_host = fixtures.GuardedStreamTest.make_host
    reopen = fixtures.GuardedStreamTest.reopen

    def revoke(self, host, adopted, original, operation):
        contract_id = f"adoption.{adopted[:16]}"
        state = host.contract(contract_id)
        selection = succession.incumbent_record(host)
        command = {
            "type": operation,
            "target": {
                "type": "settlement",
                "coordinate": state["settlement"]["coordinate"],
            },
            "defeater" if operation == "challenge" else "cause": store.digest(
                "revocation", operation
            ),
        }
        host.apply(
            contract_id,
            "settler" if operation == "challenge" else "verifier",
            "human",
            command,
            f"revoke:{operation}:{adopted}",
        )
        self.assertEqual(
            (
                host.contract(contract_id)["standing"],
                host.incumbent(),
                succession.incumbent_record(host),
            ),
            ("outstanding", original, selection),
        )

    def assert_no_work(self, host, error):
        before = (
            host.batches(),
            host.insights(),
            list(host.adapter.runs),
            host.used_confirmation_tasks(),
        )
        host = self.reopen(host)
        with (
            mock.patch.object(host, "measure_all") as tasks,
            mock.patch.object(host, "run_agent") as learning,
        ):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, error):
                    host.stream_step()
            tasks.assert_not_called()
            learning.assert_not_called()
        self.assertEqual(
            (
                host.batches(),
                host.insights(),
                host.adapter.runs,
                host.used_confirmation_tasks(),
            ),
            before,
        )

    def test_revoked_producer_cannot_resume_frozen_serve_or_probe_assignment(self):
        for phase in ("serve", "probe"):
            for operation in ("challenge", "withdraw"):
                with self.subTest(phase=phase, operation=operation):
                    host = self.make_host()
                    original = host.incumbent()
                    host.stream_step()
                    host.stream_step()
                    adopted = host.incumbent()
                    if phase == "probe":
                        host.stream_step()
                    record = host.record

                    def assigned(kind, body, epoch=None):
                        result = record(kind, body, epoch)
                        if kind == "assignment" and body.get("phase") == phase:
                            raise InterruptedError(
                                "assignment persisted before execution"
                            )
                        return result

                    with mock.patch.object(host, "record", side_effect=assigned):
                        with self.assertRaises(InterruptedError):
                            host.stream_step()
                    batch = host.batches()[-1]
                    self.assertEqual(
                        (batch["phase"], batch["expected_incumbent"]), (phase, adopted)
                    )
                    self.revoke(host, adopted, original, operation)
                    self.assert_no_work(host, "batch incumbent changed")

    def test_revoked_proposal_producer_cannot_assign_a_new_probe(self):
        host = self.make_host()
        original = host.incumbent()
        for _ in range(3):
            host.stream_step()
        adopted = host.incumbent()
        self.assertNotEqual(host.stream_policy(), adopted)
        self.assertEqual(
            (host.batches()[-1]["phase"], host.batches()[-1]["version"]),
            ("serve", adopted),
        )
        self.revoke(host, adopted, original, "withdraw")
        self.assert_no_work(host, "proposal producer changed")


if __name__ == "__main__":
    unittest.main()
