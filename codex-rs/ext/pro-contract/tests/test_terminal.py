import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / "src/invocation.py"


class TerminalTests(unittest.TestCase):
    def invoke(self, code, *, stdin=None, terminal_input="", timeout=2, args=(), env=None, terminal=True, dialogue=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, out = root / "input", root / "output"
            source.mkdir(); out.mkdir()
            (source / "stdin").write_text(stdin or "")
            environment={"PATH":"/usr/bin:/bin","LANG":"C.UTF-8",**(env or {})}
            (source / "env").write_bytes("".join(f"{key}={value}\n" for key,value in environment.items()).encode())
            if terminal:
                (source / "terminal.json").write_text(json.dumps({
                    "terminal": {"rows": 31, "cols": 97, "input": terminal_input, "dialogue":list(dialogue)},
                    "piped_stdin": stdin is not None,
                }))
            script = root / "program with ' quotes.py"
            script.write_text(code)
            result = subprocess.run([sys.executable, str(RUNNER), str(source), str(out),
                                     str(timeout), sys.executable, str(script), *args],
                                    capture_output=True, timeout=timeout + 5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.outcome = {name:int((out/name).read_text()) for name in ['timed_out','exec_failed']}
            self.dialogue_complete = int((out/'dialogue_complete').read_text())
            self.dialogue_trace = json.loads((out/'dialogue.json').read_text())
            return int((out / "rc").read_text()), (out / "out").read_bytes(), (out / "err").read_bytes()

    def test_controlling_terminal_and_piped_stdin_are_independent(self):
        rc, output, err = self.invoke('''import os, sys, stat
assert stat.S_ISFIFO(os.fstat(0).st_mode)
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

    def test_program_environment_preserves_non_newline_separators(self):
        value="a\r\u0085b"
        rc, output, _ = self.invoke("import os;print(os.environ['ODD'].encode().hex());assert os.environ['PATH']==''", env={"ODD":value,"PATH":""})
        self.assertEqual((rc,output.decode().strip()),(0,value.encode().hex()))

    def test_closed_terminal_does_not_kill_a_still_running_leader(self):
        rc, _, _ = self.invoke("import os,time;[os.close(fd) for fd in (0,1,2)];time.sleep(.2);os._exit(7)")
        self.assertEqual(rc, 7)

    def test_timeout_kills_the_entire_process_group(self):
        rc, output, _ = self.invoke('''import subprocess,time
p = subprocess.Popen(['sleep','30'])
print(p.pid, flush=True)
time.sleep(30)
''', timeout=.3)
        self.assertEqual((rc,self.outcome['timed_out']), (137,1))
        pid = int(output)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            # An adopted zombie may await the container init; it must not be running.
            self.assertEqual(stat.read_text().split(") ", 1)[1].split()[0], "Z")

    def test_ordinary_streams_are_separate_and_special_exit_codes_are_not_timeouts(self):
        for terminal in [False, True]:
            for status in [0,1,124,137,255]:
                rc, output, err = self.invoke(f"import os;os.write(1,b'out');os.write(2,b'err');os._exit({status})", terminal=terminal)
                self.assertEqual(rc,status)
                self.assertEqual(self.outcome,{'timed_out':0,'exec_failed':0})
                self.assertEqual((output,err),(b'outerr',b'') if terminal else (b'out',b'err'))

    def test_ordinary_invocation_timeout_is_explicit(self):
        rc, _, _ = self.invoke('import time;time.sleep(30)',timeout=.2,terminal=False)
        self.assertEqual((rc,self.outcome['timed_out']),(137,1))

    def test_pipes_apply_backpressure_without_losing_input_or_output(self):
        payload="字"*20_000
        rc, output, err = self.invoke('''import os,stat,sys
assert all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in (0,1,2))
data=sys.stdin.buffer.read()
os.write(1,data)
os.write(2,b'e'*100_000)
''',stdin=payload,terminal=False)
        self.assertEqual((rc,output,err),(0,payload.encode(),b'e'*100_000))

    def test_fragmented_queries_drive_ordered_replies_without_consuming_business_stdin(self):
        rc, output, err = self.invoke('''import os,sys,time,termios
with open('/dev/tty','r+b',buffering=0) as tty:
 for answer in [b'first\\n', b'second\\n']:
  termios.tcflush(tty.fileno(),termios.TCIFLUSH)
  tty.write(b'QU');time.sleep(.02);tty.write(b'ERY?')
  assert tty.readline()==answer
print(sys.stdin.read(),end='')
''', stdin='business data', dialogue=[{'expect':'QUERY?','send':'first\n'},{'expect':'QUERY?','send':'second\n'}])
        self.assertEqual((rc,output,err,self.dialogue_complete),(0,b'QUERY?QUERY?business data',b'',1))
        self.assertEqual([e['index'] for e in self.dialogue_trace['exchanges']],[0,1])

    def test_early_exit_does_not_satisfy_an_unobserved_dialogue(self):
        rc, output, _ = self.invoke("print('other output')", dialogue=[{'expect':'QUERY?','send':'answer'}])
        self.assertEqual((rc,self.outcome['timed_out'],self.dialogue_complete),(0,0,0))
        self.assertEqual(self.dialogue_trace['exchanges'],[])

    def test_program_may_ignore_startup_input_when_no_dialogue_was_required(self):
        rc, _, _ = self.invoke("import os;os._exit(0)", terminal_input="x"*65536)
        self.assertEqual((rc,self.dialogue_complete),(0,1))


if __name__ == "__main__":
    unittest.main()
