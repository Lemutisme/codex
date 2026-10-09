"""Local install/configuration boundary tests: no Docker, provider or user configuration changes."""

import json
from pathlib import Path
import tempfile
import tomllib
import unittest
import sys

import procodex_config as procodex


@unittest.skipUnless(sys.platform == "linux", "Linux Docker launcher")
class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "project with spaces"
        self.workspace.mkdir()
        self.source = self.root / "existing-codex"
        self.source.mkdir()
        self.raw = """model="some-strong-model"\nmodel_provider="route"\nnotify=["do-not-inherit"]\nsandbox_mode="danger-full-access"\n[model_providers.route]\nname="Route"\nbase_url="http://127.0.0.1:1/v1"\nenv_key="TEST_ONLY_KEY"\nwire_api="responses"\n[mcp_servers.external]\ncommand="do-not-inherit"\n"""
        (self.source / "config.toml").write_text(self.raw)

    def configure(self, check=None):
        return procodex.configure(
            self.root / "package",
            self.workspace,
            self.root / "procodex",
            self.source,
            "sha256:" + "a" * 64,
            check,
        )

    def test_routing_is_inherited_but_permissions_hooks_and_existing_home_are_not(self):
        home, config = self.configure()
        self.assertEqual(tomllib.loads((home / "config.toml").read_text()), config)
        self.assertEqual((self.source / "config.toml").read_text(), self.raw)
        self.assertEqual(
            config["model_providers"], tomllib.loads(self.raw)["model_providers"]
        )
        self.assertNotIn("notify", config)
        self.assertNotIn("mcp_servers", config)
        self.assertEqual(
            (config["sandbox_mode"], config["approval_policy"]),
            ("workspace-write", "on-request"),
        )
        environment = tomllib.loads((home / "environments.toml").read_text())
        self.assertFalse(environment["include_local"])
        args = environment["environments"][0]["args"]
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn(f"type=bind,src={self.workspace},dst=/workspace", args)
        self.assertNotIn(str(self.source), " ".join(args))
        settings = json.loads((home / "pro_contract/settings.json").read_text())
        self.assertEqual(
            settings["evaluation"]["workspace_host_root"], str(self.workspace)
        )
        self.assertIsNone(settings["evaluation"]["reference_command"])

    def test_distinct_check_contracts_use_distinct_private_state(self):
        first, _ = self.configure()
        second, _ = self.configure("python3 -m unittest")
        self.assertNotEqual(first, second)
        self.assertIsNone(
            json.loads((first / "pro_contract/settings.json").read_text())[
                "evaluation"
            ]["check"]["build_command"]
        )
        self.assertEqual(
            json.loads((second / "pro_contract/settings.json").read_text())[
                "evaluation"
            ]["check"]["build_command"],
            "python3 -m unittest",
        )

    def test_redirected_state_is_rejected_without_modifying_the_target(self):
        home, _ = self.configure()
        target = self.root / "do-not-change"
        target.mkdir()
        settings = home / "pro_contract/settings.json"
        settings.unlink()
        settings.symlink_to(target / "settings.json")
        with self.assertRaises(ValueError):
            self.configure()
        self.assertEqual(list(target.iterdir()), [])

    def test_container_only_is_explicit_and_keeps_external_restrictions_and_approvals(
        self,
    ):
        nested, _ = self.configure()
        home, config = procodex.configure(
            self.root / "package",
            self.workspace,
            self.root / "procodex",
            self.source,
            "sha256:" + "a" * 64,
            None,
            isolation="container-only",
        )
        self.assertNotEqual(home, nested)
        self.assertEqual(
            (config["sandbox_mode"], config["approval_policy"]),
            ("danger-full-access", "on-request"),
        )
        arguments = tomllib.loads((home / "environments.toml").read_text())[
            "environments"
        ][0]["args"]
        self.assertEqual(
            (
                arguments[arguments.index("--network") + 1],
                arguments[arguments.index("--cap-drop") + 1],
            ),
            ("none", "ALL"),
        )
        self.assertNotIn("--privileged", arguments)
        self.assertNotIn(str(self.source), " ".join(arguments))


if __name__ == "__main__":
    unittest.main()
