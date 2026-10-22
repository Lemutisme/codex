"""Real app-server, code mode, Docker and ProContract roles through one gateway."""
import json
import os
from pathlib import Path
import threading
import tomllib
import unittest
from unittest.mock import patch

import procodex
from procontract_benchmark_gateway import Budget, Gateway
import test_procodex_native as fixture


@unittest.skipUnless(os.environ.get('PROCODEX_NATIVE_PACKAGE'), 'requires native release and Docker')
class NativeBenchmarkGatewayTests(unittest.TestCase):
    def test_executor_and_review_share_the_wire_budget(self):
        self.run_gateway_case()

    def test_unavailable_image_observation_does_not_end_the_original_task(self):
        self.run_gateway_case(text_route=True)

    def run_gateway_case(self, text_route=False):
        original = procodex.configure
        resources = []

        def configure(*args, **kwargs):
            home, config = original(*args, **kwargs)
            provider = config['model_providers'][config['model_provider']]
            budget = Budget(home/'benchmark.sqlite')
            gateway = Gateway(budget, provider['base_url'], api_key='LOCAL_FIXTURE_ONLY')
            thread = threading.Thread(target=gateway.serve_forever, daemon=True)
            thread.start();budget.arm()
            resources.append((home, budget, gateway, thread))
            provider.update(base_url=gateway.base_url, request_max_retries=0, stream_max_retries=0)
            config['features']['view_image'] = False
            (home/'config.toml').write_text(procodex.toml(config))
            path=home/'environments.toml'
            path.write_text(path.read_text().replace('--max-process-seconds 1800','--max-process-seconds 180'))
            if docker := os.environ.get('PROCODEX_TEST_DOCKER'):
                path.write_text(path.read_text().replace('program="docker"', 'program='+json.dumps(docker)))
                settings_path=home/'pro_contract/settings.json'
                settings=json.loads(settings_path.read_text())
                settings['evaluation']['check']['docker']=docker
                settings_path.write_text(json.dumps(settings))
            if runtime := os.environ.get('PROCODEX_TEST_EXEC_RUNTIME'):
                environment=tomllib.loads(path.read_text())
                arguments=environment['environments'][0]['args']
                arguments[1:1]=['--mount',f'type=bind,src={runtime},dst=/opt/pc-runtime,readonly']
                arguments[-1]=arguments[-1].replace('exec /opt/procodex/bin/codex',
                    'exec /opt/pc-runtime/ld-linux-x86-64.so.2 --library-path /opt/pc-runtime /opt/procodex/bin/codex')
                path.write_text('default="procodex"\ninclude_local=false\n[[environments]]\nid="procodex"\nprogram='+json.dumps(docker or 'docker')+'\nargs='+json.dumps(arguments)+'\n')
            return home,config

        case=fixture.NativeEvidenceTest('test_real_executor_and_reviewer_use_frozen_handles')
        case.progress_fixture=True
        case.observation_fixture=True
        case.text_route_fixture=text_route
        case.task_text='Make answer.txt contain ready. Obtain the retained feedback bytes before repairing the artifact.'
        try:
            with patch.object(procodex, 'configure', configure):
                case.debug()
            self.assertEqual(len(resources),1)
            home,budget,_,_=resources[0]
            status=budget.status()
            self.assertGreater(status['used'],5)
            self.assertLess(status['used'],1000)
            rows=budget.db.execute('SELECT http_status,terminal,failure FROM requests').fetchall()
            self.assertTrue(all(r==(200,'response.completed',None) for r in rows),rows)
            if text_route:
                adjustments=[v for row in budget.db.execute('SELECT truncations FROM requests') for v in json.loads(row[0])]
                self.assertTrue(any(v.get('kind')=='unavailable_observation' for v in adjustments))
                self.assertIsNone(status['last_rejection'])
            report=os.environ.get('PROCODEX_TEST_REPORT')
            if report:
                Path(report).mkdir(parents=True,exist_ok=True)
                (Path(report)/'gateway.json').write_text(json.dumps({'budget':status,'requests':rows},indent=2))
        finally:
            for _,budget,gateway,thread in resources:
                gateway.shutdown();gateway.server_close();thread.join();budget.close()


if __name__=='__main__':unittest.main()
