"""Pinned image preparation stays offline; fake Docker transport only."""

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import procontract_benchmark_runner as runner


class PinnedPrepareTest(unittest.TestCase):
    def test_pinned_task_does_not_fetch_legacy_tags_or_fall_back_on_inspect_failure(
        self,
    ):
        for available in (True, False):
            with (
                self.subTest(available=available),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                codex, prompt = root / "codex", root / "prompt"
                codex.write_text("fixture binary")
                prompt.write_text("fixture task")
                args = argparse.Namespace(
                    run_dir=root / "run",
                    codex_bin=codex,
                    workspace_from=None,
                    instance="fresh__task.1234567",
                    image="sha256:" + "a" * 64,
                    policy=None,
                    instructions="executor.md",
                    no_reference=False,
                    prompt=prompt,
                    arm="on",
                    model="gpt-5.6-luna",
                    effort="max",
                )
                calls = []

                def transport(command, **_kwargs):
                    calls.append(command)
                    if command[:3] == ["docker", "image", "inspect"] and not available:
                        raise subprocess.CalledProcessError(1, command)
                    return subprocess.CompletedProcess(command, 0)

                with (
                    mock.patch.object(runner, "harness_ready", return_value=None),
                    mock.patch.object(
                        runner,
                        "ensure_images",
                        side_effect=AssertionError("legacy tags"),
                    ),
                    mock.patch.object(runner.subprocess, "run", side_effect=transport),
                    mock.patch("sys.stdout"),
                ):
                    if available:
                        runner.prepare(args)
                    else:
                        with self.assertRaises(subprocess.CalledProcessError):
                            runner.prepare(args)
                self.assertEqual(calls[0], ["docker", "image", "inspect", args.image])
                if available:
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[1][0:2], ["docker", "run"])
                    self.assertIn(args.image, calls[1])
                    manifest = json.loads((args.run_dir / "manifest.json").read_text())
                    self.assertEqual(manifest["image"], args.image)
                else:
                    self.assertEqual(len(calls), 1)
                    self.assertFalse((args.run_dir / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
