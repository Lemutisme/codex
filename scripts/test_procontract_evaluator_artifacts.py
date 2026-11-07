import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

from procontract_evaluator_artifacts import container_file_digest, owned_keepalive_args


class ArtifactReadTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.docker = self.root / "docker"
        self.docker.write_text(
            "#!" + sys.executable + "\n"
            "from pathlib import Path\nimport json,sys\n"
            "root=Path(__file__).parent\n"
            "(root/'argv.json').write_text(json.dumps(sys.argv[1:]))\n"
            "with (root/'export.tar').open('rb') as f:\n"
            " while b:=f.read(65536):sys.stdout.buffer.write(b)\n"
        )
        self.docker.chmod(0o755)
        self.env = SimpleNamespace(executable=str(self.docker), container_id="owned-container", cwd="/workspace")

    def archive(self, members):
        with tarfile.open(self.root / "export.tar", "w") as stream:
            for name, data, mode, kind in members:
                member = tarfile.TarInfo(name)
                member.mode = mode
                member.type = kind
                member.size = len(data) if kind == tarfile.REGTYPE else 0
                stream.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)

    def test_execute_only_binary_is_hashed_without_chmod_or_extraction(self):
        data = b"\x00binary\xff" * 300000
        self.archive([("executable", data, 0o111, tarfile.REGTYPE)])
        result = container_file_digest(self.env, "./executable", timeout=5)
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(result["mode"], 0o111)
        self.assertEqual(result["bytes"], len(data))
        self.assertEqual(json.loads((self.root / "argv.json").read_text()),
                         ["cp", "-L", "owned-container:/workspace/executable", "-"])
        self.assertFalse((self.root / "executable").exists())

    def test_export_is_one_regular_object(self):
        for members in [[], [("fifo", b"", 0o111, tarfile.FIFOTYPE)],
                        [("a", b"a", 0o111, tarfile.REGTYPE), ("b", b"b", 0o111, tarfile.REGTYPE)]]:
            self.archive(members)
            with self.assertRaises(RuntimeError):
                container_file_digest(self.env, "/opt/stashed", timeout=5)

    def test_blocked_export_obeys_existing_action_allowance(self):
        self.docker.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(30)\n")
        with self.assertRaises(TimeoutError):
            container_file_digest(self.env, "/opt/stashed", timeout=.1)


class KeepaliveTest(unittest.TestCase):
    def test_keeper_uses_remaining_owner_grant_without_renewal(self):
        args = ["run", "-d", "--init", "image", "sleep", "2h"]
        self.assertEqual(owned_keepalive_args(args, deadline=10000, now=1000)[-1], "9060s")
        self.assertEqual(owned_keepalive_args(args, deadline=10000, now=5000)[-1], "5060s")
        self.assertEqual(owned_keepalive_args(args, deadline=None)[-1], "infinity")
        self.assertEqual(args[-1], "2h")

    def test_expired_grant_cannot_create_a_keeper(self):
        args = ["run", "-d", "--init", "image", "sleep", "2h"]
        for deadline in [999, 1000, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                owned_keepalive_args(args, deadline=deadline, now=1000)

    def test_only_the_detached_grader_keeper_is_changed(self):
        for args in [["exec", "container", "sleep", "2h"],
                     ["run", "-i", "--init", "image", "sleep", "2h"],
                     ["run", "-d", "--init", "image", "bash", "-c", "sleep 2h"],
                     ["run", "-d", "--init", "image", "sleep", "30"]]:
            self.assertEqual(owned_keepalive_args(args, deadline=None), args)


if __name__ == "__main__":
    unittest.main()
