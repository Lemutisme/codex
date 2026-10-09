"""Future build/runtime external-file capabilities; exploration is NOT restricted here.

Real Linux subprocesses test narrow custody, not Rust authorship, semantic dependency
use, reference intent, no-install or external-network compliance. Compilation is trusted
fixture preparation. Unsupported kernel capability is a failure, never a passing skip.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).with_name("procontract_exec_capabilities.c")


@unittest.skipUnless(sys.platform == "linux", "Linux-only capability launcher")
class ExecCapabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.cc = shutil.which("cc")
        if cls.cc is None:
            raise RuntimeError(
                "required C compiler unavailable; capability not verified"
            )
        cls.launcher = cls.root / "launcher"
        cls.compile(SOURCE, cls.launcher)
        source = cls.root / "candidate.c"
        source.write_text(
            '#include <stdio.h>\nint main(void) { puts("candidate-ok"); return 0; }\n'
        )
        cls.candidate = cls.root / "candidate"
        cls.compile(source, cls.candidate)
        cls.candidate.chmod(0o555)
        cls.echo = Path("/usr/bin/echo").resolve(strict=True)
        cls.bash = Path("/usr/bin/bash").resolve(strict=True)
        cls.sh = Path("/usr/bin/sh").resolve(strict=True)
        cls.python = Path("/usr/bin/python3").resolve(strict=True)
        cls.nl = Path("/usr/bin/nl").resolve(strict=True)
        script = "import subprocess,shutil,json,socket,termios,sys; from pathlib import Path; print(json.dumps(sorted({str(Path(m.__file__).resolve()) for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).is_file()})))"
        cls.python_files = {
            Path(p)
            for p in json.loads(
                subprocess.check_output(
                    [str(cls.python), "-I", "-S", "-B", "-c", script], text=True
                )
            )
        }
        cls.reads = set(cls.python_files)
        for binary in (cls.echo, cls.bash, cls.sh, cls.python, *cls.python_files):
            if binary.suffix == ".py":
                continue
            cls.reads.update(cls.dependencies(binary))
        cls.loader = next(p for p in cls.reads if p.name.startswith("ld-linux"))
        cls.executables = {cls.echo, cls.bash, cls.sh, cls.python, cls.loader}
        cls.listings = {p.parent for p in cls.python_files}

    @classmethod
    def compile(cls, source, output):
        subprocess.run(
            [
                cls.cc,
                "-std=c11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-static",
                str(source),
                "-o",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

    @staticmethod
    def dependencies(binary):
        result = subprocess.run(
            ["ldd", str(binary)], capture_output=True, text=True, check=False
        )
        return {
            Path(path).resolve(strict=True)
            for path in re.findall(r"(/[^\s()]+)", result.stdout)
            if Path(path).is_file()
        }

    def setUp(self):
        self.case = Path(self.enterContext(tempfile.TemporaryDirectory(dir=self.root)))
        self.serial = 0

    def arguments(self, command, *, candidate=None, launcher=None, extra=()):
        candidate = candidate or self.candidate
        scratch = self.case / f"scratch-{self.serial}"
        self.serial += 1
        scratch.mkdir(mode=0o700)
        args = [
            str(launcher or self.launcher),
            "--scratch",
            str(scratch),
            "--candidate",
            str(candidate),
        ]
        for kind, paths in (
            ("--exec", self.executables),
            ("--read", self.reads | self.dependencies(candidate)),
            ("--list", self.listings),
        ):
            for path in sorted(paths):
                args.extend([kind, str(path)])
        args.extend([*extra, "--", *map(str, command)])
        return args

    def invoke(self, command, *, candidate=None, launcher=None, extra=(), **options):
        return subprocess.run(
            self.arguments(
                command, candidate=candidate, launcher=launcher, extra=extra
            ),
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            **options,
        )

    def python_run(self, script, **options):
        return self.invoke([self.python, "-I", "-S", "-B", "-c", script], **options)

    def successful(self, result, expected):
        self.assertEqual(
            result.returncode,
            0,
            f"required kernel/profile capability failed: {result.stderr}",
        )
        self.assertEqual(result.stdout.strip(), expected)

    def test_allowed_candidate_bash_and_python_are_positive_controls(self):
        self.successful(self.invoke([self.candidate]), "candidate-ok")
        self.successful(self.invoke([self.echo, "allowed"]), "allowed")
        self.successful(
            self.invoke([self.bash, "-c", f"{self.echo} bash-child"]), "bash-child"
        )
        self.successful(
            self.python_run(
                f"import subprocess; subprocess.run([{str(self.echo)!r}, 'python-child'], check=True)"
            ),
            "python-child",
        )
        self.successful(
            self.python_run(
                "import subprocess; subprocess.run(['sh','-c','printf name-lookup'],check=True)"
            ),
            "name-lookup",
        )
        self.successful(
            self.invoke(
                [self.sh, "-c", "printf discarded >/dev/null; printf null-redirection"]
            ),
            "null-redirection",
        )
        self.successful(
            self.invoke(
                [self.bash, "-c", self.candidate.name],
                extra=["--path", str(self.candidate.parent)],
            ),
            "candidate-ok",
        )

    def test_unlisted_nl_is_denied_for_build_runtime_principal_and_descendants(self):
        direct = self.invoke([self.nl, "--version"])
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn("not an executable grant", direct.stderr)
        shell = self.invoke(
            [
                self.bash,
                "-c",
                f"{self.nl} --version; s=$?; test $s -ne 0 || exit 1; printf denied",
            ]
        )
        self.successful(shell, "denied")
        self.assertIn("Permission denied", shell.stderr)
        python = self.python_run(
            f"import subprocess;\ntry: subprocess.run([{str(self.nl)!r}])\nexcept PermissionError: print('denied')\nelse: raise AssertionError('unlisted runtime executable ran')"
        )
        self.successful(python, "denied")
        self.successful(
            self.python_run(
                "import subprocess;\ntry: subprocess.run(['nl'])\nexcept PermissionError: print('denied-by-capability')\nelse: raise AssertionError('unlisted nl name resolved and ran')"
            ),
            "denied-by-capability",
        )
        background = self.invoke(
            [
                self.bash,
                "-c",
                f'( {self.nl}; echo $? > "$TMPDIR/status" ) & wait; read s < "$TMPDIR/status"; test "$s" -ne 0 || exit 1; printf inherited',
            ]
        )
        self.successful(background, "inherited")

    def test_unlisted_file_cannot_be_copied_or_read_by_explicit_dynamic_loader(self):
        result = self.python_run(
            f"import os,shutil,subprocess;\ntry: shutil.copyfile({str(self.nl)!r}, os.environ['TMPDIR']+'/clone')\nexcept PermissionError: pass\nelse: raise AssertionError('unlisted executable was readable')\np=subprocess.run([{str(self.loader)!r},{str(self.nl)!r}],capture_output=True,text=True)\nassert p.returncode != 0 and 'Permission denied' in p.stderr, p\nprint('blocked')"
        )
        self.successful(result, "blocked")

    def test_candidate_is_immutable_while_scratch_is_writable_but_not_executable(self):
        before = self.candidate.read_bytes()
        result = self.python_run(
            f"import os,shutil,subprocess;\ntry: open({str(self.candidate)!r},'wb')\nexcept PermissionError: pass\nelse: raise AssertionError('candidate mutable')\np=os.environ['TMPDIR']+'/copy'\nshutil.copyfile({str(self.candidate)!r},p); os.chmod(p,0o755)\ntry: subprocess.run([p])\nexcept PermissionError: print('separated')\nelse: raise AssertionError('scratch executable ran')"
        )
        self.successful(result, "separated")
        self.assertEqual(self.candidate.read_bytes(), before)

    def test_candidate_truncate_link_and_rename_cannot_cross_into_scratch(self):
        before = self.candidate.read_bytes()
        try:
            script = f"import os,errno; p={str(self.candidate)!r}; s=os.environ['TMPDIR']; os.chmod(p,0o755)\nfor op in [lambda:os.open(p,os.O_RDONLY|os.O_TRUNC),lambda:os.link(p,s+'/alias'),lambda:os.rename(p,s+'/moved')]:\n try: op()\n except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM,errno.EXDEV), e\n else: raise AssertionError('immutable input changed')\nprint('immutable')"
            self.successful(self.python_run(script), "immutable")
            self.assertEqual(self.candidate.read_bytes(), before)
        finally:
            self.candidate.chmod(0o555)

    def test_inherited_file_descriptor_is_closed_before_granted_python(self):
        with self.nl.open("rb") as inherited:
            result = self.python_run(
                f"import os,errno;\ntry: os.read({inherited.fileno()},1)\nexcept OSError as error: assert error.errno == errno.EBADF\nelse: raise AssertionError('inherited descriptor readable')\nprint('closed')",
                pass_fds=(inherited.fileno(),),
            )
        self.successful(result, "closed")

    def test_tcp_loopback_is_not_silently_disabled(self):
        result = self.python_run(
            "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); c=socket.socket(); c.connect(s.getsockname()); a,_=s.accept(); c.sendall(b'ok'); assert a.recv(2)==b'ok'; a.close(); c.close(); s.close(); print('loopback')"
        )
        self.successful(result, "loopback")

    def test_fd_import_socketpair_and_memfd_profiles_are_refused(self):
        script = "import socket,os,errno\nfor op in [lambda:socket.socket(socket.AF_UNIX),socket.socketpair,lambda:os.memfd_create('bytes')]:\n try: op()\n except OSError as e: assert e.errno == errno.EPERM, e\n else: raise AssertionError('unsupported FD import profile allowed')\nprint('refused')"
        self.successful(self.python_run(script), "refused")

    def test_pseudo_filesystem_grants_fail_before_command_execution(self):
        result = self.invoke(
            [self.echo, "UNSAFE"], extra=["--read", f"/proc/{os.getpid()}/status"]
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("filesystem", result.stderr)

    def test_stdio_rejects_regular_files_and_sockets(self):
        import socket

        with (self.case / "output").open("w") as output:
            result = subprocess.run(
                self.arguments([self.candidate]),
                input="",
                stdout=output,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stdio", result.stderr)
        left, right = socket.socketpair()
        with left, right:
            result = subprocess.run(
                self.arguments([self.candidate]),
                stdin=left,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stdio", result.stderr)

    def test_explicit_pty_slave_works_but_default_and_master_are_rejected(self):
        import pty

        master, slave = pty.openpty()
        try:
            for fd, extra in ((slave, []), (master, ["--pty-stdio"])):
                result = subprocess.run(
                    self.arguments([self.candidate], extra=extra),
                    stdin=fd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("stdio", result.stderr)
            result = subprocess.run(
                self.arguments(
                    [self.bash, "-c", 'printf "%s\\n" "$TERM"'],
                    extra=["--pty-stdio", "--term", "xterm"],
                ),
                stdin=slave,
                stdout=slave,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(os.read(master, 128), b"xterm\r\n")
            script = "import fcntl,termios,errno\ntry: fcntl.ioctl(0,termios.TIOCSTI,b'x')\nexcept OSError as e: assert e.errno == errno.EPERM\nelse: raise AssertionError('TTY input injection permitted')\nprint('no-injection')"
            result = subprocess.run(
                self.arguments(
                    [self.python, "-I", "-S", "-B", "-c", script], extra=["--pty-stdio"]
                ),
                stdin=slave,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=15,
            )
            self.successful(result, "no-injection")
        finally:
            os.close(master)
            os.close(slave)

    def test_registered_rust_runs_but_command_nl_is_denied(self):
        compilers = sorted((Path.home() / ".rustup/toolchains").glob("*/bin/rustc"))
        if not compilers:
            self.skipTest(
                "no installed direct Rust toolchain; no installation attempted"
            )
        source = self.case / "candidate.rs"
        source.write_text(
            f'fn main() {{ let allowed = std::process::Command::new("sh").args(["-c", "printf rust-allowed"]).output().unwrap(); assert!(allowed.status.success()); assert_eq!(allowed.stdout, b"rust-allowed"); let error = std::process::Command::new({json.dumps(str(self.nl))}).output().unwrap_err(); assert_eq!(error.kind(), std::io::ErrorKind::PermissionDenied); println!("rust-denied"); }}'
        )
        candidate = self.case / "rust-candidate"
        subprocess.run(
            [str(compilers[0]), "--edition=2021", str(source), "-o", str(candidate)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        candidate.chmod(0o555)
        self.successful(self.invoke([candidate], candidate=candidate), "rust-denied")

    def test_unsupported_kernel_has_no_unrestricted_fallback(self):
        wrapper = self.case / "unavailable.c"
        wrapper.write_text(
            "#define _GNU_SOURCE\n#include <errno.h>\n#include <unistd.h>\n#include <sys/syscall.h>\n#define syscall(number, ...) ((number)==SYS_landlock_create_ruleset ? (errno=ENOSYS,-1L) : (syscall)((number),__VA_ARGS__))\n#include "
            + json.dumps(str(SOURCE.resolve()))
            + "\n"
        )
        binary = self.case / "unavailable"
        self.compile(wrapper, binary)
        result = self.invoke([self.echo, "UNCONFINED"], launcher=binary)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("required; no fallback", result.stderr)


if __name__ == "__main__":
    unittest.main()
