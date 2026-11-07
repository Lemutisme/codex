"""Admit the eight artifact-only recoveries into the existing shared capacity."""
import collections
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from job import ROOT, process_identity, save

ORIGINAL = Path('/data/ProContract/programbench-sol61-20261104')


def alive(record):
    try:
        fields = Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[0] != 'Z' and fields[19] == record['start_ticks']
    except (OSError, KeyError):
        return False


def live_jobs(root):
    return [record for path in (root/'jobs').glob('*.json')
            if alive(record := json.loads(path.read_text()))]


def external_count(capacity):
    return len(live_jobs(ORIGINAL)) + sum(len(live_jobs(Path(root)))
        for root in capacity['external_job_roots'] if Path(root) != ROOT)


def release_reservation(capacity):
    reservation = capacity.get('measurement_slot_reservation')
    if reservation and reservation['owner'] == str(ROOT):
        capacity['max_concurrent_attempts'] = reservation['base_target']
        capacity.pop('measurement_slot_reservation')
        capacity.update(at=time.time(), reason='Reserved scoring-recovery admissions registered; all Sol and artifact-only jobs share the current authorized slots without changed solver grants.')
        with (ORIGINAL/'capacity-history.jsonl').open('a') as stream:
            stream.write(json.dumps(capacity)+'\n')
        save(ORIGINAL/'capacity.json', capacity)


def report(plan, active, other):
    rows = []
    for task in plan['tasks']:
        run = ROOT/'runs'/task
        row = {'task':task, 'state':'queued'}
        if (run/'progress.json').exists():
            row['progress'] = json.loads((run/'progress.json').read_text())
            row['state'] = row['progress'].get('stage', 'preparing')
        if (run/'JOB_RESULT.json').exists():
            row['job'] = json.loads((run/'JOB_RESULT.json').read_text())
            row['state'] = row['job']['stage']
        elif task in active and row['state'] == 'queued':
            row['state'] = 'preparing'
        if (run/'benchmark-score.json').exists():
            score = json.loads((run/'benchmark-score.json').read_text())
            if score.get('available'):
                row['score'] = score['selected']
        rows.append(row)
    scores = [row['score'] for row in rows if 'score' in row]
    status = {'at':time.time(), 'root':str(ROOT), 'tasks':len(rows),
        'states':dict(collections.Counter(row['state'] for row in rows)),
        'active_jobs':len(active), 'other_active_jobs':other, 'combined_active_jobs':len(active)+other,
        'capacity':json.loads((ORIGINAL/'capacity.json').read_text())['authorized_max'], 'model_requests':0, 'solver_restarted':False,
        'scored':len(scores), 'scored_mean_percent':sum(score['scorer_percent'] for score in scores)/len(scores) if scores else None,
        'fully_resolved_count':sum(score['passed']==score['eligible'] for score in scores),
        'scope':'Independent grading resource calibration on stopped retained artifacts. Original records remain unchanged.'}
    save(ROOT/'RESULTS.json', {**status,'rows':rows})
    save(ROOT/'STATUS.json', status)


def main():
    with (ROOT/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(ROOT/'supervisor-process.json', process_identity(os.getpid()))
        plan_bytes = (ROOT/'plan.json').read_bytes()
        plan = json.loads(plan_bytes)
        qualification = json.loads((ROOT/'QUALIFIED.json').read_text())
        assert qualification['plan_sha256'] == hashlib.sha256(plan_bytes).hexdigest()
        active, children = {}, {}
        for task in plan['tasks']:
            run = ROOT/'runs'/task
            if (run/'JOB_RESULT.json').exists():
                continue
            meta = ROOT/'jobs'/(task+'.json')
            launch = run/'launch.json'
            if not meta.exists() and launch.exists():
                save(meta, {**json.loads(launch.read_text()), 'task':task})
            if meta.exists():
                record = json.loads(meta.read_text())
                if alive(record):
                    active[task] = record
                else:
                    save(run/'JOB_RESULT.json', {'task':task,'stage':'interrupted_measurement','at':time.time(),'model_requests':0})
        while True:
            for task, record in list(active.items()):
                child = children.get(task)
                if (child.poll() is None) if child else alive(record):
                    continue
                if not (ROOT/'runs'/task/'JOB_RESULT.json').exists():
                    save(ROOT/'runs'/task/'JOB_RESULT.json', {'task':task,'stage':'worker_exited_without_result','at':time.time(),'model_requests':0})
                active.pop(task);children.pop(task, None)
            pending = [task for task in plan['tasks'] if task not in active and not (ROOT/'runs'/task/'JOB_RESULT.json').exists()]
            with (ORIGINAL/'shared-admission.lock').open('a') as admission:
                fcntl.flock(admission, fcntl.LOCK_EX)
                capacity = json.loads((ORIGINAL/'capacity.json').read_text())
                assert str(ROOT) in capacity['external_job_roots']
                other = external_count(capacity)
                memory = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
                eligible = [task for task in pending if Path(plan['artifacts'][task]['original_job_terminal']).exists()]
                if (eligible and len(active)<1 and len(active)+other<capacity['authorized_max']
                    and not (ROOT/'PAUSE_ADMISSIONS').exists() and not (ORIGINAL/'PAUSE_ADMISSIONS').exists()
                    and memory>=capacity['admission_memory_reserve_bytes'] and shutil.disk_usage(ROOT).free>=capacity['disk_admission_reserve_bytes']):
                    task = eligible[0]
                    with (ROOT/'jobs'/(task+'.log')).open('x') as output:
                        child = subprocess.Popen([sys.executable,'-B',str(ROOT/'job.py'),task], cwd=ROOT,
                            stdout=output, stderr=output, start_new_session=True,
                            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                    record = {**process_identity(child.pid),'task':task,'at':time.time(),'kind':'artifact_only_scoring'}
                    save(ROOT/'jobs'/(task+'.json'), record)
                    active[task] = record;children[task] = child
                if len(list((ROOT/'jobs').glob('*.json'))) >= len(plan['tasks']) or not pending:
                    release_reservation(capacity)
            report(plan, active, other)
            if not active and not pending:
                return
            time.sleep(3)


if __name__ == '__main__':
    main()
