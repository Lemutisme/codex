"""Qualify and score an existing immutable artifact; never start a solver."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def process_identity(pid):
    return {'pid': pid, 'start_ticks': Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]}


def environment(task):
    env = {key: os.environ[key] for key in ('PATH','HOME','USER','LANG','LC_ALL','TMPDIR') if key in os.environ}
    env.update(PATH=str(ROOT/'bin') + ':' + env.get('PATH', '/usr/bin:/bin'),
               DOCKER_HOST='unix:///var/run/docker.sock', PC_TASK=task,
               PROGRAMBENCH_CONTAINER_PREFIX='score-recovery-' + task,
               PROGRAMBENCH_DOCKER_EXECUTABLE=str(ROOT/'bin/docker'),
               PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1')
    return env


def execute(command, env, log, seconds):
    with log.open('x') as output:
        child = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            return 124


def cleanup(task):
    command = [str(ROOT/'bin/docker')]
    flags = ['--filter','label=pc.grader-resources=20261107','--filter','label=pc.task=' + task]
    ids = subprocess.check_output(command + ['ps','-aq',*flags], text=True, timeout=15).split()
    removed = subprocess.run(command + ['rm','-f',*ids], capture_output=True, text=True, timeout=30) if ids else None
    until = time.monotonic() + 30
    while True:
        remaining = subprocess.check_output(command + ['ps','-aq',*flags], text=True, timeout=15).split()
        if not remaining or time.monotonic() >= until:
            return {'removed':ids,'remaining':remaining,'removal_exit':removed.returncode if removed else None,
                    'removal_diagnostic':removed.stderr if removed else None}
        time.sleep(.2)


def main(task):
    plan = json.loads((ROOT/'plan.json').read_text())
    assert task in plan['tasks']
    binding_record=plan['artifacts'][task]
    for name, expected in plan['files'].items():
        assert sha(name) == expected, name
    assert sha(binding_record['source_artifact']) == binding_record['source_artifact_sha256']
    assert sha(binding_record['original_solver_budget']) == binding_record['original_solver_budget_sha256']
    run = ROOT/'runs'/task
    with (run/'launch.json').open('x') as stream:
        json.dump({'at':time.time(),'plan_sha256':sha(ROOT/'plan.json'),'model_requests':0,**process_identity(os.getpid())}, stream)
    env = environment(task)
    case = ROOT/'inputs/cases'/task
    registry = case/'canonical-registry.json'
    pins = case/'canonical-pins.json'
    command = [plan['evaluator_python'],'-B',str(ROOT/'controller/procontract_canonical.py')]
    result = {'task':task,'started_at':time.time(),'model_requests':0,'solver_restarted':False,
              'source_artifact_sha256':binding_record['source_artifact_sha256'],'scope':plan['score_policy']}
    stage = 'preparing'
    try:
        from prepare_case import prepare_registry
        prepare_registry(task)
        binding = ['--registry',str(registry),'--registry-sha256',sha(registry)]
        save(run/'progress.json', {**result,'stage':stage})
        code = execute(command + ['freeze',*binding], env, run/'freeze.log', 300)
        if code:
            raise RuntimeError(f'freeze failed: {code}')
        binding += ['--pins-sha256',sha(pins)]
        code = execute(command + ['ready',*binding,'--task',task,'--output',str(case/'readiness')],
                       env, run/'readiness.log', plan['preparation_seconds'])
        if code:
            raise RuntimeError(f'readiness failed: {code}')
        ready = json.loads((case/'readiness/readiness.json').read_text())
        assert ready['valid'] and ready['eligible_total'] == json.loads(registry.read_text())['tasks'][task]['total']
        save(run/'prepared.json', {'at':time.time(),'registry_sha256':sha(registry),'pins_sha256':sha(pins),
                                  'readiness_sha256':sha(case/'readiness/readiness.json'),'model_requests':0})
        stage = 'grading'
        allocation = {'started':time.time(),'seconds':plan['external_grading_seconds'],'model_requests':0}
        allocation['deadline'] = allocation['started'] + allocation['seconds']
        save(run/'measurement-allocation.json', allocation)
        save(run/'progress.json', {**result,'stage':stage,'allocation':allocation})
        code = execute(command + ['evaluate',*binding,'--task',task,'--archive',str(run/'submission.tar.gz'),
                                  '--output',str(run/'evaluation')], env, run/'evaluation.log', allocation['seconds'])
        result['evaluator_exit'] = code
        scalar = run/'evaluation/canonical-result.json'
        if scalar.exists():
            result['canonical_result'] = json.loads(scalar.read_text())
        stage = 'score_projection'
        code = execute([plan['evaluator_python'],'-B',str(ROOT/'record_score.py'),task], env, run/'score.log', 300)
        result['projection_exit'] = code
        if not code:
            result['benchmark_score'] = json.loads((run/'benchmark-score.json').read_text())
        stage = 'scored' if result.get('benchmark_score', {}).get('available') else 'measurement_incomplete'
        assert sha(run/'submission.tar.gz') == binding_record['source_artifact_sha256']
        assert sha(binding_record['source_artifact']) == binding_record['source_artifact_sha256']
        assert sha(binding_record['original_solver_budget']) == binding_record['original_solver_budget_sha256']
        for path,expected in binding_record['preserved_original_files'].items():
            assert sha(path)==expected,path
    except BaseException as error:
        result['failure'] = {'stage':stage,'type':type(error).__name__,'message':str(error)}
        stage = 'measurement_failed'
    finally:
        try:
            result['cleanup'] = cleanup(task)
        except Exception as error:
            result['cleanup_error'] = str(error)
        result.update(stage=stage, finished_at=time.time())
        save(run/'RESULT.json', result)
        save(run/'progress.json', result)
        save(run/'JOB_RESULT.json', {'task':task,'stage':stage,'finished_at':time.time(),'model_requests':0})
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
