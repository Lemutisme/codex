import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

from procontract_submission_transport import EXTRACT


def archive(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as stream:
        for name, kind, value, mode in entries:
            member = tarfile.TarInfo(name)
            member.type, member.mode, member.mtime = kind, mode, 1234567890
            if kind == tarfile.REGTYPE:
                member.size = len(value)
                stream.addfile(member, io.BytesIO(value))
            else:
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    member.linkname = value
                stream.addfile(member)
    return data.getvalue()


class TransportTests(unittest.TestCase):
    def run_extract(self, root, entries):
        return subprocess.run([sys.executable, '-I', '-S', '-c', EXTRACT, str(root)],
                              input=archive(entries), capture_output=True, timeout=20)

    def test_fifo_permissions_hardlinks_and_escape_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = [('locked', tarfile.DIRTYPE, '', 0o555),
                       ('locked/file', tarfile.REGTYPE, b'exact bytes\n', 0o444),
                       ('locked/pipe', tarfile.FIFOTYPE, '', 0o640),
                       ('alias', tarfile.LNKTYPE, 'locked/file', 0o444),
                       ('outside', tarfile.SYMTYPE, '/does/not/exist', 0o777)]
            result = self.run_extract(root, entries)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['members'], 5)
            self.assertEqual((root/'locked/file').read_bytes(), b'exact bytes\n')
            self.assertTrue(stat.S_ISFIFO((root/'locked/pipe').stat().st_mode))
            self.assertEqual(stat.S_IMODE((root/'locked').stat().st_mode), 0o555)
            self.assertEqual(stat.S_IMODE((root/'locked/pipe').stat().st_mode), 0o640)
            self.assertEqual((root/'alias').stat().st_ino, (root/'locked/file').stat().st_ino)
            self.assertEqual(os.readlink(root/'outside'), '/does/not/exist')
            (root/'locked').chmod(0o755)

    def test_full_path_longer_than_path_max_is_materialized_via_directory_descriptors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = ['segment' + str(i).zfill(3) + 'x'*90 for i in range(45)]
            relative = '/'.join(names) + '/payload'
            result = self.run_extract(root, [(relative, tarfile.REGTYPE, b'deep', 0o600)])
            self.assertEqual(result.returncode, 0, result.stderr)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for name in names:
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
                    os.close(fd);fd = child
                target = os.open('payload', os.O_RDONLY, dir_fd=fd)
                with os.fdopen(target, 'rb') as source:
                    self.assertEqual(source.read(), b'deep')
            finally:
                os.close(fd)

    def test_archive_cannot_write_through_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary);root = parent/'root';root.mkdir()
            external = parent/'external';external.mkdir()
            entries = [('alias', tarfile.SYMTYPE, str(external), 0o777),
                       ('alias/payload', tarfile.REGTYPE, b'escape', 0o600)]
            result = self.run_extract(root, entries)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((external/'payload').exists())

    def test_forward_hardlink_and_directory_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.run_extract(root, [('alias', tarfile.LNKTYPE, 'target', 0o644),
                ('target', tarfile.REGTYPE, b'data', 0o644)])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root/'alias').stat().st_ino, (root/'target').stat().st_ino)


if __name__ == '__main__':
    unittest.main()
