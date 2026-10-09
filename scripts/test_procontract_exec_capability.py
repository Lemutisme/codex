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
