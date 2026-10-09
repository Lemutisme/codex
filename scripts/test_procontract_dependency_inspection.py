"""Exercise the subprocess boundary without Docker, downloads, or model calls."""

import io
import subprocess
import unittest
from unittest import mock

import procontract_dependency_inspection as inspection

IMAGE, HASH = "sha256:" + "a" * 64, "b" * 64


class InspectionTest(unittest.TestCase):
    def setUp(self):
        self.policy = mock.Mock(images=(IMAGE,))
        self.policy.items.return_value = {
            "tool:rustc": {"path": "/usr/bin/rustc", "sha256": HASH},
            "library:z": {"path": "/lib/libz.so", "sha256": HASH},
        }
        self.output = f"/usr/lib/libz.so.1\t{HASH}\n/usr/bin/rustc\t{HASH}\n".encode()

    def process(self, output, code=0):
        return mock.Mock(
            stdout=io.BytesIO(output),
            wait=mock.Mock(return_value=code),
            poll=mock.Mock(return_value=code),
        )

    def test_hardened_positional_command_and_deterministic_result(self):
        with mock.patch.object(
            inspection.subprocess,
            "Popen",
            side_effect=[
                self.process((IMAGE + "\n").encode()),
                self.process(self.output),
            ],
        ) as popen:
            result = inspection.verify_image(self.policy, IMAGE)
        self.assertEqual(
            result,
            {
                "schema": "preinstalled-artifact-verification-v1",
                "image_id": IMAGE,
                "artifacts": {
                    "library:z": {
                        "path": "/lib/libz.so",
                        "resolved_path": "/usr/lib/libz.so.1",
                        "sha256": HASH,
                    },
                    "tool:rustc": {
                        "path": "/usr/bin/rustc",
                        "resolved_path": "/usr/bin/rustc",
                        "sha256": HASH,
                    },
                },
            },
        )
        self.assertEqual(
            popen.call_args_list[0].args[0],
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                IMAGE,
            ],
        )
        command = popen.call_args_list[1].args[0]
        self.assertEqual(
            command,
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "1000:1000",
                "--memory",
                "64m",
                "--cpus",
                "0.5",
                "--pids-limit",
                "16",
                "--ulimit",
                "fsize=1048576:1048576",
                "--ulimit",
                "nofile=32:32",
                "--workdir",
                "/",
                "--entrypoint",
                "/usr/bin/timeout",
                IMAGE,
                "--signal=KILL",
                "20",
                "/bin/sh",
                "-c",
                inspection.INSPECT,
                "dependency-inspector",
                "/lib/libz.so",
                "/usr/bin/rustc",
            ],
        )
        for call in popen.call_args_list:
            self.assertEqual(
                call.kwargs,
                {
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.STDOUT,
                },
            )

    def test_unavailable_or_wrong_identity_never_runs_inspection_or_fallback(self):
        for failure in (PermissionError("socket denied"), FileNotFoundError("docker")):
            with (
                self.subTest(failure=failure),
                mock.patch.object(
                    inspection.subprocess,
                    "Popen",
                    side_effect=failure,
                ) as popen,
            ):
                with self.assertRaises(ValueError):
                    inspection.verify_image(self.policy, IMAGE)
                self.assertEqual(popen.call_count, 1)
        for output, code in ((b"sha256:wrong\n", 0), (b"missing local image", 1)):
            with mock.patch.object(
                inspection.subprocess, "Popen", return_value=self.process(output, code)
            ) as popen:
                with self.assertRaises(ValueError):
                    inspection.verify_image(self.policy, IMAGE)
                self.assertEqual(popen.call_count, 1)

    def test_missing_prerequisite_bad_output_and_hash_fail_without_retry(self):
        for output, code in (
            (b"missing /usr/bin/timeout", 127),
            (b"", 0),
            (self.output * 2, 0),
            (self.output.replace(b"/usr/lib", b"/workspace"), 0),
            (self.output.replace(b"/usr/lib", b"/usr/../lib"), 0),
            (self.output.replace(b"/usr/lib", b"/proc"), 0),
            (self.output.replace(HASH.encode(), b"c" * 64), 0),
            (self.output.replace(b"\t", b"\t\t"), 0),
            (b"x" * (inspection.MAX_OUTPUT + 1), 0),
            (b"\xff", 0),
        ):
            with (
                self.subTest(code=code, prefix=output[:40]),
                mock.patch.object(
                    inspection.subprocess,
                    "Popen",
                    side_effect=[
                        self.process((IMAGE + "\n").encode()),
                        self.process(output, code),
                    ],
                ) as popen,
            ):
                with self.assertRaises(ValueError):
                    inspection.verify_image(self.policy, IMAGE)
                self.assertEqual(popen.call_count, 2)

    def test_invalid_input_does_not_spawn(self):
        with mock.patch.object(inspection.subprocess, "Popen") as popen:
            for image in ("ubuntu:latest", "sha256:" + "c" * 64, IMAGE + ";x"):
                with self.assertRaises(ValueError):
                    inspection.verify_image(self.policy, image)
            for path in (
                "/workspace/reference",
                "/usr/../proc/version",
                "/usr/a\nfile",
                "/usr/$(cmd)",
            ):
                self.policy.items.return_value["tool:rustc"]["path"] = path
                with self.assertRaises(ValueError):
                    inspection.verify_image(self.policy, IMAGE)
            popen.assert_not_called()

    def test_pipe_timeout_and_process_timeout_kill_without_unbounded_read(self):
        process = self.process(b"")
        process.stdout = mock.Mock()
        process.stdout.read.return_value = b"x" * (inspection.MAX_OUTPUT + 1)
        process.poll.return_value = None
        with mock.patch.object(inspection.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "output bound"):
                inspection._run(["docker"])
            process.stdout.read.assert_called_once_with(inspection.MAX_OUTPUT + 1)
            process.kill.assert_called_once()
            process.stdout.close.assert_called_once()
        process = self.process(b"")
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("docker", 1)
        with (
            mock.patch.object(inspection.subprocess, "Popen", return_value=process),
            mock.patch.object(inspection.threading, "Thread") as thread,
        ):
            thread.return_value.is_alive.return_value = True
            with self.assertRaisesRegex(ValueError, "timed out"):
                inspection._run(["docker"])
            process.kill.assert_called_once()
            self.assertEqual(
                thread.return_value.join.call_args_list,
                [mock.call(inspection.TIMEOUT), mock.call(2)],
            )
        process = self.process(b"ok")
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("docker", 1)
        with mock.patch.object(inspection.subprocess, "Popen", return_value=process):
            with self.assertRaises(ValueError):
                inspection._run(["docker"])
            process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
