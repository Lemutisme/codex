"""Install publication tests over synthetic packages, never the user's installation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import install_procodex as installer


class InstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.package = self.root / "package"
        self.prefix = self.root / "prefix"
        for folder in (
            self.source / "scripts",
            self.source / "codex-rs/ext/pro-contract/policies",
            self.package / "bin",
            self.prefix / "bin",
        ):
            folder.mkdir(parents=True)
        for name in (
            "procodex.py",
            "procodex_config.py",
            "PROCODEX.md",
            "procontract_rsi.py",
        ):
            (self.source / "scripts" / name).write_text("fixture " + name)
        (self.source / "codex-rs/ext/pro-contract/policies/reviewer.md").write_text(
            "fixture"
        )
        binaries = {}
        for name in ("codex", "codex-code-mode-host", "pro-contract-store"):
            path = self.package / "bin" / name
            path.write_text("fixture " + name)
            binaries[name] = installer.sha(path)
        (self.package / "build-source.json").write_text(
            json.dumps(dict(source_commit="a" * 40, binaries=binaries))
        )
        (self.prefix / "bin/codex").write_bytes(b"original codex")
        self.enterContext(
            mock.patch.object(
                installer.subprocess,
                "check_output",
                side_effect=lambda args, **kw: (
                    "a" * 40 + "\n" if "rev-parse" in args else b""
                ),
            )
        )

    def install(self):
        return installer.install(
            self.source, self.package, "sha256:" + "b" * 64, self.prefix
        )

    def test_publish_complete_separate_release_without_changing_codex(self):
        result = self.install()
        self.assertEqual((self.prefix / "bin/codex").read_bytes(), b"original codex")
        self.assertEqual(
            (self.prefix / "share/procodex/current").resolve(), Path(result["release"])
        )
        self.assertEqual(
            (Path(result["release"]) / "scripts/procodex_config.py").read_text(),
            "fixture procodex_config.py",
        )
        self.assertIn(
            "PROC0DEX_LOCAL_LAUNCHER", (self.prefix / "bin/procodex").read_text()
        )
        with self.assertRaises(RuntimeError):
            self.install()

    def test_foreign_executable_and_changed_binary_fail_before_publication(self):
        path = self.prefix / "bin/procodex"
        path.write_bytes(b"foreign")
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertEqual(path.read_bytes(), b"foreign")
        self.assertFalse((self.prefix / "share/procodex/current").exists())
        path.unlink()
        (self.package / "bin/codex").write_bytes(b"changed")
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertFalse((self.prefix / "share/procodex/current").exists())


if __name__ == "__main__":
    unittest.main()
