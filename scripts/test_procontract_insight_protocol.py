"""Host/store integration for fixed insight schemas and the existing second attempt."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_insight_protocol as protocol
import procontract_rsi as rsi
import test_procontract_rsi as fixtures


class InsightProtocolTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tasks = fixtures.FakeTasks()
        self.host = fixtures.host(fixtures.campaign(temporary.name), self.tasks)
        self.parent = self.host.incumbent()
        self.host.dev(self.parent)
        self.prepared = []
        self.launched = []
        self.repair = True
        self.malformed_role = "analyst.md"
        original = rsi.subprocess.run

        def transport(args, **kwargs):
            result = original(args, **kwargs)
            if args[: len(fixtures.FAKE_RUNNER)] != fixtures.FAKE_RUNNER:
                return result
            phase = args[len(fixtures.FAKE_RUNNER)]
            run = Path(args[args.index("--run-dir") + 1])
            if phase == "prepare":
                role = args[args.index("--instructions") + 1]
                prompt = Path(args[args.index("--prompt") + 1]).read_text()
                workspace = run / "workspace"
                inputs = {
                    path.relative_to(workspace).as_posix(): path.read_bytes()
                    for path in workspace.rglob("*")
                    if path.is_file()
                }
                self.prepared.append((role, prompt, inputs))
                return result
            self.launched.append(run)
            role, prompt, _ = self.prepared[-1]
            if role == self.malformed_role and (
                not self.repair or "hindsight cluster 1 was never sent" not in prompt
            ):
                table = run / "workspace" / "hindsight.json"
                data = json.loads(table.read_text())
                data["clusters"][0]["source"] = "artifact (README explains it)"
                table.write_text(json.dumps(data))
                (run / "workspace" / "knowledge" / "rejected.md").write_text(
                    "REJECTED_PRIVATE_KNOWLEDGE"
                )
            return result

        patch = mock.patch.object(rsi.subprocess, "run", side_effect=transport)
        patch.start()
        self.addCleanup(patch.stop)

    def test_second_attempt_gets_exact_diagnostic_but_not_rejected_knowledge(self):
        k = self.host.analyze(self.parent)
        first, second, challenge = self.prepared
        self.assertEqual(
            (self.host.insight(k)["status"], [entry[0] for entry in self.prepared]),
            ("qualified", ["analyst.md", "analyst.md", "challenger.md"]),
        )
        self.assertEqual(first[2], second[2])
        self.assertNotIn("previous authorized attempt", first[1])
        self.assertIn(
            "hindsight cluster 1 was never sent but has no source of artifact, convention, prior, unobservable",
            second[1],
        )
        self.assertNotIn("REJECTED_PRIVATE_KNOWLEDGE", second[1])
        for role, prompt, inputs in self.prepared:
            with self.subTest(role=role):
                self.assertIn(
                    '"source" must be exactly one of: artifact, convention, prior, unobservable',
                    prompt,
                )
                self.assertIn(
                    '"class" must be exactly one of: never_sent, never_compared, left_unfixed, too_shallow',
                    prompt,
                )
                visible = prompt + b"\n".join(inputs.values()).decode("utf-8")
                for heldout in [*fixtures.SEALED, "never__used.0000009"]:
                    self.assertNotIn(heldout, visible)
        self.assertNotIn("previous authorized attempt", challenge[1])
        self.assertNotIn("knowledge/rejected.md", challenge[2])
        rejected = self.launched[0] / "workspace" / "hindsight.json"
        self.assertEqual(
            json.loads(rejected.read_text())["clusters"][0]["source"],
            "artifact (README explains it)",
        )
        self.assertFalse((self.host.current_knowledge() / "rejected.md").exists())
        before = list(self.launched)
        reopened = fixtures.host(self.host.camp, self.tasks)
        self.assertEqual(reopened.analyze(self.parent), k)
        self.assertEqual(self.launched, before)

    def test_challenger_retry_receives_diagnostic_with_original_analyst_delivery(self):
        self.malformed_role = "challenger.md"
        k = self.host.analyze(self.parent)
        self.assertEqual(
            (self.host.insight(k)["status"], [entry[0] for entry in self.prepared]),
            ("qualified", ["analyst.md", "challenger.md", "challenger.md"]),
        )
        first, second = self.prepared[1:]
        self.assertEqual(first[2], second[2])
        self.assertIn("hindsight cluster 1 was never sent", second[1])
        self.assertFalse((self.host.current_knowledge() / "rejected.md").exists())

    def test_second_failure_exhausts_the_existing_two_attempts(self):
        self.repair = False
        k = self.host.analyze(self.parent)
        self.assertEqual(
            (
                self.host.insight(k)["status"],
                [run.parent.name for run in self.launched],
                self.host.current_knowledge(),
                self.host.used_confirmation_tasks(),
            ),
            ("failed", ["analyst-1", "analyst-2"], None, []),
        )
        self.assertIn("hindsight cluster 1 was never sent", self.prepared[1][1])

    def test_resume_preserves_second_prompt_and_does_not_repurchase_first_attempt(self):
        original = self.host.run_agent

        def interrupt(root, *args):
            if root.name == "analyst-2":
                raise InterruptedError("stop before the second authorized launch")
            return original(root, *args)

        with mock.patch.object(self.host, "run_agent", side_effect=interrupt):
            with self.assertRaises(InterruptedError):
                self.host.analyze(self.parent)
        prompt_path = self.host.camp / "insight" / "1" / "analyst-2" / "prompt.md"
        before = prompt_path.read_bytes()
        reopened = fixtures.host(self.host.camp, self.tasks)
        k = reopened.analyze(self.parent)
        self.assertEqual(
            (reopened.insight(k)["status"], [run.parent.name for run in self.launched]),
            ("qualified", ["analyst-1", "analyst-2", "challenger-1"]),
        )
        self.assertEqual(prompt_path.read_bytes(), before)

    def test_feedback_quotes_and_bounds_path_like_diagnostics(self):
        reason = ('"\\\n\x00文' * 2000) + "UNBOUNDED_TAIL"
        rendered = protocol.retry_prompt("initial prompt\n", reason)
        diagnostic = rendered.splitlines()[3]
        decoded = json.loads(diagnostic)
        self.assertLessEqual(len(decoded.encode("utf-8")), 512)
        self.assertLess(len(rendered.encode("utf-8")), 1600)
        self.assertNotIn("UNBOUNDED_TAIL", rendered)
        self.assertEqual(rendered, protocol.retry_prompt("initial prompt\n", reason))


if __name__ == "__main__":
    unittest.main()
