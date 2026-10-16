import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / "src/terminal.py"


class TerminalTests(unittest.TestCase):
    def invoke(self, code, *, stdin=None, terminal_input="", timeout=2, args=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, out = root / "input", root / "output"
            source.mkdir(); out.mkdir()
            (source / "stdin").write_text(stdin or "")
            (source / "terminal.json").write_text(json.dumps({
                "terminal": {"rows": 31, "cols": 97, "input": terminal_input},
                "piped_stdin": stdin is not None,
            }))
            script = root / "program with ' quotes.py"
            script.write_text(code)
            result = subprocess.run([sys.executable, str(RUNNER), str(source), str(out),
                                     str(timeout), sys.executable, str(script), *args],
                                    capture_output=True, timeout=timeout + 5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            return int((out / "rc").read_text()), (out / "out").read_bytes(), (out / "err").read_bytes()

    def test_controlling_terminal_and_piped_stdin_are_independent(self):
        rc, output, err = self.invoke('''import os, sys
with open('/dev/tty', 'rb', buffering=0) as terminal:
    key = terminal.read(1).decode()
print(os.isatty(0), os.isatty(1), os.isatty(2), tuple(os.get_terminal_size(1)), sys.stdin.read(), key)
''', stdin="piped", terminal_input="q")
        self.assertEqual((rc, output, err), (0, b"False True True (97, 31) piped q\n", b""))

    def test_terminal_stdin_and_binary_output_are_not_normalized(self):
        rc, output, _ = self.invoke('''import os, sys
assert os.isatty(0)
assert sys.stdin.readline() == 'hello\\n'
os.write(1, b'\\x00\\xff\\x1b[2J\\r\\n')
os.write(2, b'error')
''', terminal_input="hello\n")
        self.assertEqual((rc, output), (0, b"\x00\xff\x1b[2J\r\nerror"))

    def test_argument_vector_is_not_shell_code(self):
        args = ("a ' quoted $HOME `value`", "尾部")
        rc, output, _ = self.invoke("import json,sys;print(json.dumps(sys.argv[1:],ensure_ascii=False))", args=args)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(output), list(args))

    def test_closed_terminal_does_not_kill_a_still_running_leader(self):
        rc, _, _ = self.invoke("import os,time;[os.close(fd) for fd in (0,1,2)];time.sleep(.2);os._exit(7)")
        self.assertEqual(rc, 7)

    def test_timeout_kills_the_entire_process_group(self):
        rc, output, _ = self.invoke('''import subprocess,time
p = subprocess.Popen(['sleep','30'])
print(p.pid, flush=True)
time.sleep(30)
''', timeout=.3)
        self.assertEqual(rc, 124)
        pid = int(output)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            # An adopted zombie may await the container init; it must not be running.
            self.assertEqual(stat.read_text().split(") ", 1)[1].split()[0], "Z")


if __name__ == "__main__":
    unittest.main()
