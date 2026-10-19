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
    def test_time_only_continuations_do_not_reintroduce_a_default_count_on_resume(self):
        args=(self.root/"package",self.workspace,self.root/"procodex",self.source,"sha256:"+"a"*64,None)
        home,_=procodex.configure(*args,successor_sessions=None,task_seconds=3600,continuous_work=True)
        original=json.loads((home/'pro_contract/settings.json').read_text())
        self.assertEqual(original['succession'],{'total_secs':3600})
        self.assertNotIn('max_publications',original['progress'])
        self.assertNotIn('executor_slice_secs',original['progress'])
        same,_=procodex.configure(*args,successor_sessions=3,task_seconds=7200,continuous_work=True)
        current=json.loads((same/'pro_contract/settings.json').read_text())
        self.assertEqual(original['succession'],current['succession'])
        self.assertEqual(original['progress'],current['progress'])

    def test_input_survives_output_replacement_and_reopening_after_source_disappears(self):
        original = self.root / "reference"
        original.write_text("original specification")
        original.chmod(0o555)
        args=(self.root/"package",self.workspace,self.root/"procodex",self.source,"sha256:"+"a"*64,None)
        home,config=procodex.configure(*args,inputs={"spec":original})
        snapshot=home/'inputs/files/spec'
        self.assertEqual(snapshot.read_text(),"original specification")
        self.assertEqual(snapshot.stat().st_mode & 0o777,0o555)
        (self.workspace/'executable').write_text('new implementation')
        original.unlink()
        reopened,_=procodex.configure(*args,inputs={"spec":original})
        self.assertEqual(home,reopened)
        self.assertEqual(snapshot.read_text(),"original specification")
        environment=tomllib.loads((home/'environments.toml').read_text())
        self.assertIn(f'type=bind,src={snapshot},dst=/inputs/spec,readonly',environment['environments'][0]['args'])
        self.assertIn('/inputs/spec',config['developer_instructions'])

    def test_strategy_changes_context_without_resetting_task_identity_or_grant(self):
        bundle=self.root/'strategy';bundle.mkdir()
        (bundle/'work_method.md').write_text('Investigate assumptions before changing proof structure.')
        args=(self.root/"package",self.workspace,self.root/"procodex",self.source,"sha256:"+"a"*64,None)
        home,_=procodex.configure(*args,successor_sessions=3,task_seconds=3600,continuous_work=True)
        before=json.loads((home/'pro_contract/settings.json').read_text())
        same,_=procodex.configure(*args,strategy=bundle,successor_sessions=1,task_seconds=7200,continuous_work=True)
        after=json.loads((home/'pro_contract/settings.json').read_text())
        self.assertEqual(home,same)
        self.assertEqual(before['succession'],after['succession'])
        self.assertEqual(before['progress'],after['progress'])
        self.assertEqual(after['policy'],str(bundle))

    def test_computation_is_opt_in_and_keeps_existing_task_state(self):
        args=(self.root/"package",self.workspace,self.root/"procodex",self.source,"sha256:"+"a"*64,None)
        home,_=procodex.configure(*args,successor_sessions=3,task_seconds=3600)
        self.assertNotIn("review_execution",json.loads((home/"pro_contract/settings.json").read_text()))
        retained=home/"pro_contract/existing-grant-marker"
        retained.write_text("original deadline and reservations")
        enabled,_=procodex.configure(*args,successor_sessions=3,task_seconds=3600,review_compute=True)
        self.assertEqual(enabled,home)
        self.assertEqual(retained.read_text(),"original deadline and reservations")
        settings=json.loads((home/"pro_contract/settings.json").read_text())
        self.assertEqual(settings["review_execution"],dict(max_calls=8,timeout_secs=30,max_output_bytes=65536))
        self.assertEqual(settings["succession"],dict(max_sessions=3,total_secs=3600))

    def test_succession_is_an_explicit_finite_native_grant(self):
        home, _ = procodex.configure(
            self.root / "package",
            self.workspace,
            self.root / "procodex",
            self.source,
            "sha256:" + "a" * 64,
            "true",
            successor_sessions=3,
            task_seconds=3600,
        )
        settings = json.loads((home / "pro_contract/settings.json").read_text())
        self.assertEqual(
            settings["succession"], {"max_sessions": 3, "total_secs": 3600}
        )
        with self.assertRaises(ValueError):
            procodex.configure(
                self.root / "package",
                self.workspace,
                self.root / "procodex",
                self.source,
                "unused",
                "true",
                successor_sessions=-1,
            )

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
        self.assertEqual(
            (config["sqlite_home"], config["log_dir"]), (str(home), str(home / "log"))
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
