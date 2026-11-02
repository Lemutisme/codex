#!/usr/bin/env python3
"""Opt-in real-model ProContract operational closure on a synthetic reducer defect.

The research actor chooses and executes the investigation through operations; this
fixture supplies a task outcome, independent measurement and one next task. It
contains no candidate patch, adoption decision or model-response substitution.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib

import procontract_operations as ops
from procontract_operations_rpc import Broker
from procontract_benchmark_runner import AppServer
from procontract_benchmark_gateway import Budget, Gateway
import procodex_config

REPO=Path(__file__).resolve().parent.parent


from procontract_native_operation import (build_identity, observe_build, verify_actor_view, confirm_environment_shutdown, AuditedBudget, native, native_measure, run_assigned)


def measure(assignment_path):
    path=Path(assignment_path);assignment=json.loads(path.read_text())
    config=json.loads(Path(assignment['measurement']['argv'][3]).read_text())
    script=path.parent/'reducer.py';script.write_text(assignment['version']['definition']['files']['reducer.py'])
    observations=[]
    for text,expected in config['cases']:
        run=subprocess.run(['docker','run','--rm','-i','--network','none','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--read-only','--memory','128m','--pids-limit','32',
            '--mount',f'type=bind,src={script},dst=/tool.py,readonly',config['image'],'python3','/tool.py'],
            input=text,text=True,capture_output=True,timeout=20)
        observations.append({'exit_code':run.returncode,'stdout':run.stdout,'expected':str(expected)+'\n','stderr':run.stderr})
    valid=all(x['exit_code']==0 for x in observations)
    passed=sum(x['exit_code']==0 and x['stdout']==x['expected'] for x in observations)
    # Finite sealed evidence, no universal solver-quality claim. Details remain in
    # host custody; research receives an aggregate and exact measurement identity.
    ops.atomic(path.parent/'sealed-observations.json',observations)
    ops.atomic(path.parent/'result.json',{'validity':'valid' if valid else 'execution_failed','quality':passed/len(observations) if valid else None,
        'effects_resolved':True,
        'passed':passed,'count':len(observations),'admissible':valid and passed==len(observations),
        'scope':'These sealed reducer inputs only; authorized isolated deployment trial',
        'sealed_evidence':ops.sha(observations)})


def episode(root, package, image):
    root.mkdir(parents=True,exist_ok=False)
    image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',image],text=True).strip()
    # Qualify the execution capability before spending model calls.
    subprocess.run(['docker','run','--rm','--network','none','--mount',f'type=bind,src={package},dst=/opt/procodex,readonly',
        image,'/bin/bash','-c','python3 -c "import json,socket" && /opt/procodex/bin/codex --version'],check=True,capture_output=True)
    config=root/'sealed.json'
    numbers=[secrets.randbelow(2_000_001)-1_000_000 for _ in range(9)]
    a,b,c,d,e,f,g,h,i=numbers
    # Actual cases are host-private per-episode data, never package source or
    # actor workspace content. The protected verifier's algorithm is not itself
    # evidence that its input data was beyond the candidate's reach.
    ops.atomic(config,{'image':image,'cases':[[f'{a}\n{b}',a+b],[f'{c}\n{d}\n',c+d],
        [f'{e}\r\n{f}',e+f],['',0],[f'\n{g}\n\n{h}\n',g+h],[str(i),i]]})
    measurement=ops.Measurement((sys.executable,str(Path(__file__).resolve()),'measure',str(config)),
        ops.sha({'runner':ops.sha(Path(__file__).read_bytes()),'inputs':ops.sha(config.read_bytes())}), image,True,120,True,'sealed-reducer')
    native_config=root/'native.json'
    ops.atomic(native_config,{'host':str(root/'host'),'package':str(package),'image':image,'offered_measurements':['reducer-contract-v1']})
    native_cap=ops.Measurement((sys.executable,str(Path(__file__).resolve()),'native-measure',str(native_config)),
        ops.sha({'runner':ops.sha(Path(__file__).read_bytes()),'configuration':ops.sha(native_config.read_bytes())}),image,False,None,True,'native-episode')
    host=ops.Operations.create(root/'host',ops.Authority('delegating-user',
        ops.sha((REPO/'docs/research/procontract-rsi-delegation-20261031.md').read_bytes()),
        'isolated reducer trial; frozen ProgramBench excluded',('reducer.py',),('reducer-contract-v1','native-procontract'),True),
        {'reducer-contract-v1':measurement,'native-procontract':native_cap})
    host.issue('meta.episode',{'goal':'Investigate scoped task outcomes; retain knowledge and consider authorized tool revisions',
                             'hard_deadline':None,'authority_source':host.authority.source})
    host.subscribe('meta.episode','tasks',['operation_outcome'])
    host.subscribe('tasks','external-input',['observation'])
    policies={p.name:p.read_text() for p in (REPO/'codex-rs/ext/pro-contract/policies').glob('*.md')}
    files={**policies,'reducer.py':'import sys\nrows = sys.stdin.read().split("\\n")[:-1]\nprint(sum(int(row) for row in rows if row.strip()))\n'}
    definition={'kind':'task','files':files,'build':{'codex':ops.sha((package/'bin/codex').read_bytes()),'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
                'snapshot':build_identity(package)},
                'model':{'name':'gpt-5.6-luna','effort':'max'},'resolver':'procodex-config-v1','tools':{'network':'none','immutable_inputs':True}}
    incumbent=host.register(definition);host.bootstrap(incumbent)
    research_definition={**definition,'kind':'research','files':{**policies,'work_method.md':(REPO/'strategies/research/operations.md').read_text()}}
    research=host.register(research_definition)
    # Retain a source-linked real trajectory interpretation through the same read
    # path, without treating it as the synthetic tool's performance evidence.
    trajectory=REPO/'docs/research/procontract-publication-lifecycle-20261026.md'
    raw=host.put('source_snapshot',{'path':str(trajectory),'sha256':ops.sha(trajectory.read_bytes()),'text':trajectory.read_text()})
    host.observation('recorded-publication-lifecycle',[raw],{'scope':'stopped frozen trajectories; no solver feedback'},
        {'execution':'caller-loss/pending-finalization observed','quality':None,'measurement':'no causal quality estimate'}, {},source='historical-research')
    task_prompt='Run the pinned reducer at /inputs/reducer.py using /inputs/readings.txt as stdin. Preserve its exact stdout in answer.txt. Do not alter either input or substitute your own computation. Report the command and actual result; this task captures the behavior of the pinned tool.'
    first_input=root/'first.txt';first_input.write_text('4\n9')
    tool=root/'tool-initial.py';tool.write_text(files['reducer.py'])
    first,observation=run_assigned(host,'task.initial','tasks',incumbent,{'run':str(root/'t1'),'prompt':task_prompt,
        'inputs':{'reducer.py':str(tool),'readings.txt':str(first_input)},'seconds':360,'expected':'13\n',
        'conditions':{'input':'4\n9','input_sha256':ops.sha(first_input.read_bytes()),'expected_semantics':'sum signed decimal integers, including final non-newline-terminated record; blank lines ignored'}})
    # Operation finalization atomically publishes the outcome and coalesced wake.
    wake=next((item for item in host.wakes() if item['id']=='meta.episode'),None)
    if wake is None:raise RuntimeError('task event did not wake research')
    ops.atomic(root/'wake.json',wake)
    prompt=f'''An automatically delivered task outcome is pending for your improvement responsibility meta.episode.\nObservation: {observation}. Task version: {incumbent}. Research version: {research}.\nUse your operation capability socket and research strategy. Investigate the tool's behavior and retain an evidence-bound interpretation. Standing authorization permits editing only reducer.py, experiments with measurement reducer-contract-v1 (inputs={{}}, purpose authored by you), and adoption for this isolated trial when the host admits the sealed evidence. Its contract is: sum signed decimal integer records; accept LF/CRLF, blank input and blank lines; include a last record without a terminator. The measurement is independent, sealed and cannot be changed through your capability. You may retain the incumbent or propose/test/adopt a candidate if warranted. All experiments retain their own assignments and original limits. Finish by writing report.md with your diagnosis, evidence, decision and limits, and select a wait through the inbox cursor. Do the operations yourself; there is no human patch relay. The historical lifecycle observation is separate evidence, not a score for this tool.'''
    analysis,_=run_assigned(host,'research.delivery.'+str(wake['pending']),'meta.episode',research,
        {'run':str(root/'r'),'prompt':prompt,'inputs':{'client.py':str(REPO/'scripts/procontract_operations_rpc.py')},'seconds':900,'socket_host':'meta.episode'})
    selected=host.incumbent()
    if selected['version']==incumbent:raise RuntimeError('episode retained incumbent; rollout path not exercised (see retained research outcome)')
    selected_files=host.get(selected['version'],'version')['definition']['files']
    tool2=root/'tool-selected.py';tool2.write_text(selected_files['reducer.py'])
    next_input=root/'next.txt';next_input.write_text('12\n-5\n6')
    following,final_observation=run_assigned(host,'task.after-selection','tasks',selected['version'],
        {'run':str(root/'t2'),'prompt':task_prompt,'inputs':{'reducer.py':str(tool2),'readings.txt':str(next_input)},'seconds':360,
         'expected':'13\n','conditions':{'input_sha256':ops.sha(next_input.read_bytes()),'fresh_input':True}})
    summary={'scope':'synthetic defect, operational closure; no generalized improvement or model-weight RL',
        'initial':incumbent,'research':research,'selected':selected,'initial_observation':observation,'next_observation':final_observation,
        'initial_actual':first['files'].get('answer.txt'),'next_actual':following['files'].get('answer.txt'),
        'research_report':analysis['files'].get('report.md'),'costs':[x['cost'] for x in (first,analysis,following)],'next_resolved_input':following['resolved_input']}
    ops.atomic(root/'summary.json',summary)
    if summary['next_actual']!='13\n':raise RuntimeError('next task used selected version but fresh output was incorrect')
    return summary


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='measure':
        measure(sys.argv[-1])
    elif len(sys.argv)>1 and sys.argv[1]=='native-measure':
        native_measure(sys.argv[-1])
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--root',required=True,type=Path);parser.add_argument('--package',required=True,type=Path);parser.add_argument('--image',required=True)
        args=parser.parse_args()
        print(json.dumps(episode(args.root.resolve(),args.package.resolve(),args.image),indent=2))
