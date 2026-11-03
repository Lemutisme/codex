"""Scoped native cleanup controls for the real-model operations adapter."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from qualify_procontract_operations import build_identity, confirm_environment_shutdown, observe_build
from procontract_native_operation import collect_outputs,native,attach_socket,attach_project,submit_pending
from procontract_operations import Operations,Authority,Measurement
import tomllib
import sqlite3


class CleanupTest(unittest.TestCase):
    def test_declared_project_assessment_binds_actual_capture_root_before_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';(package/'bin').mkdir(parents=True)
            (package/'bin/codex').write_text('fixture')
            project=root/'project';project.mkdir()
            host=Operations.create(root/'host',Authority('fixture','fixture','artifact view',(),()),{})
            version=host.register({'kind':'research','files':{},'build':{},'model':{'name':'fixture','effort':'max'},'resolver':'fixture','tools':{}})
            observed=[]
            def stop_before_inference(argv,env,*args):
                observed.append(json.loads((Path(env['CODEX_HOME'])/'pro_contract/settings.json').read_text())['evaluation'])
                raise RuntimeError('stop before inference')
            for selected in (False,True):
                with patch('procontract_native_operation.verify_actor_view',return_value={'fixture':True}), \
                     patch('procontract_native_operation.confirm_environment_shutdown',return_value={'confirmed':True}), \
                     patch('procontract_native_operation.AppServer',side_effect=stop_before_inference):
                    with self.assertRaisesRegex(RuntimeError,'stop before inference'):
                        native(root/str(selected),package,'image',version,host,'Inspect artifact',inputs={},
                               project={'path':str(project),'writable':[],'excluded':['.git','build']},assessment_project=selected)
            self.assertEqual(observed[0]['workspace_container_root'],'/workspace')
            self.assertEqual(observed[1]['workspace_container_root'],'/workspace/project')
            self.assertEqual(observed[1]['workspace_host_root'],str(project))
            self.assertEqual(observed[1]['excluded_paths'],['.git','build'])

    def test_early_native_setup_failure_closes_resources_and_retains_absence_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';(package/'bin').mkdir(parents=True)
            (package/'bin/codex').write_text('fixture')
            host=Operations.create(root/'host',Authority('fixture','fixture','setup fault',(),()),{})
            version=host.register({'kind':'research','files':{},'build':{},'model':{'name':'fixture','effort':'max'},'resolver':'fixture','tools':{}})
            run=root/'native'
            with patch('procontract_native_operation.confirm_environment_shutdown',return_value={'confirmed':True,'remaining_owned':[]}):
                with self.assertRaisesRegex(ValueError,'task duration'):
                    native(run,package,'image',version,host,'No inference',inputs={},seconds=1.5)
            shutdown=json.loads((run/'shutdown.json').read_text())
            self.assertEqual(shutdown['native']['status'],'not_started')
            self.assertTrue(shutdown['environment']['confirmed'])
            with sqlite3.connect(run/'requests.sqlite') as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)

    def test_project_mount_has_readonly_root_and_only_declared_writable_subpaths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);home=root/'home';home.mkdir();project=root/'project';(project/'policies').mkdir(parents=True)
            path=home/'environments.toml'
            path.write_text('default="test"\n[[environments]]\nid="test"\nprogram="docker"\nargs=["run","image","executor"]\n')
            attach_project(home,{'path':str(project),'writable':['policies']},'image')
            args=tomllib.loads(path.read_text())['environments'][0]['args']
            mounts=[args[i+1] for i,value in enumerate(args) if value=='--mount']
            self.assertIn(f'type=bind,src={project},dst=/workspace/project,readonly',mounts)
            self.assertIn(f'type=bind,src={project}/policies,dst=/workspace/project/policies',mounts)
            (project/'escape').symlink_to(root)
            with self.assertRaisesRegex(ValueError,'redirected'):
                attach_project(home,{'path':str(project),'writable':['escape']},'image')

    def test_next_input_page_has_a_new_assignment_without_renewing_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            host=Operations.create(root/'host',Authority('fixture','fixture','test',(),('native-procontract',)),{
                'native-procontract':Measurement(('/bin/true',),'noop','fixture')})
            host.subscribe('research','input',['observation'])
            version=host.register({'kind':'research','files':{},'build':{},'model':{},'resolver':'fixture','tools':{}})
            for i in range(2):host.observation('item',[],{},{'i':i},{},source='input')
            def submit():return submit_pending(host,'research',version,root/'runs','analyze',inputs={},seconds=10)
            original=submit();self.assertEqual(submit(),original)
            host.run_worker(original[0])
            page=host.receive('research',limit=1)
            host.wait('research',page['epoch'],page['through'],{'event':True})
            following=submit()
            self.assertNotEqual(following[0],original[0])
            self.assertEqual(submit(),following)
            self.assertEqual(host.inspect(original[0])['request'],original[1]['request'])
            final=host.receive('research');host.wait('research',final['epoch'],final['through'],{'event':True})
            self.assertIsNone(submit())

    def test_socket_endpoint_is_independent_of_a_long_durable_workspace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/('a'*90)/('b'*90);home.mkdir(parents=True)
            path=home/'environments.toml'
            path.write_text('default="test"\n[[environments]]\nid="test"\nprogram="docker"\nargs=["run","--network","none","image","executor"]\n')
            attach_socket(home,Path('/tmp/short-ipc/s'),'image')
            arguments=tomllib.loads(path.read_text())['environments'][0]['args']
            self.assertEqual(arguments,['run','--network','none','--mount','type=bind,src=/tmp/short-ipc/s,dst=/workspace/s,readonly','image','executor'])

    def test_output_collection_never_follows_actor_links_and_retains_nontext_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'workspace';workspace.mkdir()
            private=root/'private';private.write_text('must not be released through a link')
            (workspace/'link').symlink_to(private)
            (workspace/'answer.txt').write_text('retained output')
            (workspace/'binary').write_bytes(b'\xff\x00')
            (workspace/'large').write_bytes(b'x'*(1<<20)+b'x')
            files,artifacts=collect_outputs(workspace)
            self.assertEqual(files,{'answer.txt':'retained output'})
            self.assertEqual(artifacts['link']['kind'],'symlink')
            self.assertEqual(artifacts['binary']['bytes'],2)
            self.assertFalse(artifacts['large']['inline_text'])

    def test_repeated_native_directory_is_rejected_before_model_or_host_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'native-admission.json').write_text('{}')
            with self.assertRaises(FileExistsError):native(root,None,'image','version',None,'prompt',inputs={})

    def run_cleanup(self, remaining):
        owned='a'*64;foreign='b'*64
        containers=[{'Id':owned,'Mounts':[{'Source':'/fixture/run/workspace'}]},
                    {'Id':foreign,'Mounts':[{'Source':'/another/invocation'}]}]
        final=[c for c in containers if c['Id'] in remaining]
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=[owned+'\n'+foreign,json.dumps(containers),remaining,*([json.dumps(final)] if remaining else [])]), \
             patch('qualify_procontract_operations.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','No such container')) as remove:
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
            self.assertEqual(remove.call_args.args[0],['docker','rm','-f',owned])
        return result

    def test_automatic_removal_race_is_confirmed_by_the_later_lifetime_observation(self):
        result=self.run_cleanup('b'*64+'\n')
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['removal']['exit_code'],1)

    def test_a_failed_remove_does_not_claim_a_still_live_container_ended(self):
        self.assertFalse(self.run_cleanup('a'*64+'\n')['confirmed'])

    def test_unavailable_docker_observation_is_unknown(self):
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=OSError('daemon unavailable')):
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
        self.assertFalse(result['confirmed'])
        self.assertIn('daemon unavailable',result['error'])

    def test_disappearing_foreign_container_does_not_hide_owned_shutdown(self):
        owned='a'*64;foreign='b'*64
        inspectable=[{'Id':owned,'Mounts':[{'Source':'/fixture/run/workspace'}]}]
        missing=subprocess.CalledProcessError(1,['docker','inspect'],output=json.dumps(inspectable),stderr='No such object')
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=[owned+'\n'+foreign,missing,owned,'']), \
             patch('qualify_procontract_operations.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as remove:
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
        self.assertTrue(result['confirmed'])
        self.assertEqual(remove.call_args.args[0],['docker','rm','-f',owned])

    def test_uninspectable_live_container_remains_unknown(self):
        identity='a'*64
        missing=subprocess.CalledProcessError(1,['docker','inspect'],output='[]',stderr='inspect failed')
        with patch('qualify_procontract_operations.subprocess.check_output',side_effect=[identity,missing,identity]):
            result=confirm_environment_shutdown(Path('/fixture/run/workspace'),Path('/fixture/run/state'))
        self.assertFalse(result['confirmed'])
        self.assertIn('live container',result['error'])

    def test_version_includes_tool_host_and_changed_bytes_are_fenced_before_model_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            package=Path(temporary);(package/'bin').mkdir()
            (package/'bin/codex').write_text('native')
            host=package/'bin/codex-code-mode-host';host.write_text('tool host v1')
            original=build_identity(package)
            definition={'build':{'snapshot':original}}
            self.assertIn('bin/codex-code-mode-host',original['package_files'])
            self.assertIn('resolver',original['host_sources'])
            self.assertEqual(observe_build(package,definition),original)
            host.write_text('tool host v2')
            with self.assertRaisesRegex(ValueError,'differ'):
                observe_build(package,definition)
            self.assertNotEqual(observe_build(package,{'build':{}}),original)

    def test_build_identity_does_not_include_the_per_run_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            first=Path(temporary)/'first';second=Path(temporary)/'second'
            for root in (first,second):
                (root/'bin').mkdir(parents=True);(root/'bin/codex').write_text('same binary')
            self.assertEqual(build_identity(first),build_identity(second))


if __name__=='__main__':unittest.main()
