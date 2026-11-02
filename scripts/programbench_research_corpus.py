#!/usr/bin/env python3
"""Read-only ProgramBench adapter: index retained first-attempt evidence for research.

The adapter reports observations and coverage. It does not assign root causes,
derive strategy, change scores or select a solver/research workflow.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import tarfile
import time


def read(path):
    return json.loads(Path(path).read_text())


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def selected_result_path(row,run):
    """Bind the declared measurement; independent retries are a different attempt."""
    candidates=[row.get('established_result_path'),row.get('result_path')]
    if row.get('completion_kind')!='independent_retry':candidates.append(row.get('completion_result'))
    candidates.append(run/'RESULT.json')
    paths=list(dict.fromkeys(Path(p) for p in candidates if p and Path(p).is_file()))
    declared=row.get('external') or {}
    keys=[key for key in ('valid','eval_sha256','submission_sha256','resolved','total','pass_rate') if key in declared]
    if keys:
        for path in paths:
            observed=read(path).get('external') or {}
            if all(observed.get(key)==declared[key] for key in keys):return path
        return None
    return paths[0] if paths else None


def wanted(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:return False
    name=str(path)
    return (name.startswith('codex-home/sessions/') and path.name.startswith('rollout-') and name.endswith('.jsonl')) or name in {
        'codex-home/pro_contract/ledger_1.sqlite','codex-home/pro_contract/ledger_1.sqlite-wal','codex-home/pro_contract/ledger_1.sqlite-shm'}


def extract(run,target):
    archive=run/'retained-work.tar.zst';sources=[]
    if archive.exists():
        observed=digest(archive);retention=read(run/'retention.json') if (run/'retention.json').exists() else {}
        if retention.get('sha256') and retention['sha256']!=observed:raise ValueError('archive differs from retained identity')
        process=subprocess.Popen(['zstd','-dc',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|') as contents:
                for member in contents:
                    if not member.isfile() or not wanted(member.name):continue
                    destination=target/PurePosixPath(member.name);destination.parent.mkdir(parents=True,exist_ok=True)
                    with contents.extractfile(member) as stream,destination.open('wb') as output:shutil.copyfileobj(stream,output)
                    sources.append({'path':str(destination),'member':member.name,'sha256':digest(destination),'bytes':member.size})
            error=process.stderr.read().decode(errors='replace');code=process.wait()
            if code:raise RuntimeError('archive decompression failed: '+error[:2000])
        finally:
            process.stdout.close();process.stderr.close()
            if process.poll() is None:process.kill();process.wait()
        return {'kind':'retained_archive','path':str(archive),'sha256':observed,'bytes':archive.stat().st_size,
            'recorded_sha256':retention.get('sha256'),'sources':sources}
    for path in sorted((run/'codex-home').rglob('*')):
        relative=path.relative_to(run)
        if path.is_file() and not path.is_symlink() and wanted(relative.as_posix()):
            destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
            observed=digest(destination)
            if digest(path)!=observed:raise ValueError('unpacked retained input changed during capture')
            sources.append({'path':str(destination),'origin':str(path),'sha256':observed,'bytes':destination.stat().st_size})
    return {'kind':'stopped_unpacked_run','path':str(run),'sources':sources}


def content_text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return '\n'.join(str(item.get('text','')) for item in value if isinstance(item,dict))
    return ''


def session_index(source,directory,number):
    path=Path(source['path']);counts=collections.Counter();tools=collections.Counter();messages=[];calls={};outputs={}
    metadata=None;first=None;last=None;offset=0;errors=[];turns=0
    with path.open('rb') as stream:
        for line_number,line in enumerate(stream,1):
            location={'session_sha256':source['sha256'],'line':line_number,'offset':offset,'length':len(line)};offset+=len(line)
            try:item=json.loads(line)
            except ValueError:errors.append(location);continue
            if not isinstance(item,dict):continue
            payload=item.get('payload') or {};kind=item.get('type');stamp=item.get('timestamp')
            if not isinstance(payload,dict):continue
            first=first or stamp;last=stamp or last;ptype=payload.get('type');counts[str(kind)+':'+str(ptype)]+=1
            if kind=='session_meta':metadata=payload
            if kind=='event_msg' and ptype=='task_started':turns+=1
            if kind=='response_item' and ptype=='message' and payload.get('role')=='assistant':
                messages.append({'at':stamp,'location':location,'text':content_text(payload.get('content')),'meaning':'assistant statement; not an independent observation'})
            if kind=='compacted':messages.append({'at':stamp,'location':location,'text':payload.get('message',''),'meaning':'agent-authored compaction summary'})
            if kind=='response_item' and ptype in ('custom_tool_call','function_call'):
                text=payload.get('input',payload.get('arguments',''));text=text if isinstance(text,str) else json.dumps(text)
                name=payload.get('name','unknown');tools[name]+=1
                calls[payload.get('call_id',str(line_number))]={'at':stamp,'name':name,'call':location,'input_preview':text[:1600],'input_preview_complete':len(text)<=1600}
            if kind=='response_item' and ptype in ('custom_tool_call_output','function_call_output'):
                text=content_text(payload.get('output'));outputs[payload.get('call_id',str(line_number))]={'at':stamp,'output':location,'output_preview':text[:1200],'output_preview_complete':len(text)<=1200}
    index=directory/'tool-index'/f'{number:04}.jsonl';index.parent.mkdir(parents=True,exist_ok=True)
    with index.open('w') as stream:
        for identity in dict.fromkeys([*calls,*outputs]):stream.write(json.dumps({'call_id':identity,**calls.get(identity,{}),**outputs.get(identity,{})},ensure_ascii=False)+'\n')
    return {'source':source,'session':metadata,'first':first,'last':last,'turns':turns,'event_counts':dict(counts),'tools':dict(tools),
        'tool_index':{'path':str(index),'sha256':digest(index),'rows':len(calls.keys()|outputs.keys())},'messages':messages,'parse_errors':errors}


def ledger_index(path):
    if not path.exists():return {'available':False}
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    events=[];phases=collections.Counter();kinds=collections.Counter();choices=collections.Counter();errors=[]
    if 'experiment_events' in tables:
        for seq,raw in db.execute('SELECT seq,event_json FROM experiment_events ORDER BY seq'):
            value=json.loads(raw);body=value.get('body') or {};phase=body.get('phase');kinds[value.get('kind','unknown')]+=1
            if phase:phases[phase]+=1
            if phase=='continuation_decision':choices[(body.get('choice') or {}).get('action','unavailable')]+=1
            if phase in ('continuation_decision','successor_returned','successor_reserved','task_delivery','progress_assessed','work_assessed','interruption_snapshot') or value.get('kind')=='verification':
                events.append({'seq':seq,'event':value})
            if body.get('error'):errors.append({'seq':seq,'phase':phase,'error':body['error']})
    subjects=db.execute('SELECT COUNT(*) FROM subjects').fetchone()[0] if 'subjects' in tables else None
    record_kinds=dict(db.execute('SELECT kind,COUNT(*) FROM records GROUP BY kind')) if 'records' in tables else {}
    db.close()
    return {'available':True,'source':str(path),'sha256':digest(path),'event_kinds':dict(kinds),'phases':dict(phases),
        'choices':dict(choices),'distinct_captured_subjects':subjects,'record_kinds':record_kinds,'selected_events':events,'errors':errors,
        'meaning':'Recorded lifecycle/choice counts; neither causal credit nor successful repair counts'}


def case(row,run,output,first_solver):
    directory=output/'cases'/row['task'];done=directory/'dossier.json'
    if done.exists():
        prior=read(done)
        if prior['recorded_result']!=row or prior['solver_run']!=str(run) or prior['first_admission_after_preparation_repair']!=first_solver:
            raise ValueError('retained case index belongs to different inputs; use a new research output')
        return prior
    directory.mkdir(parents=True,exist_ok=True)
    origin=extract(run,directory/'retained')
    sessions=[session_index(source,directory,n) for n,source in enumerate(origin['sources']) if source['path'].endswith('.jsonl')]
    ledger=ledger_index(directory/'retained/codex-home/pro_contract/ledger_1.sqlite')
    messages=[]
    for session in sessions:
        for message in session.pop('messages'):
            messages.append({'session':session['source']['path'],**message})
    messages.sort(key=lambda item:item.get('at') or '')
    message_path=directory/'statements.jsonl'
    with message_path.open('w') as stream:
        for message in messages:stream.write(json.dumps(message,ensure_ascii=False)+'\n')
    result_path=selected_result_path(row,run)
    native_path=run/'RESULT.json'
    result=read(native_path) if native_path.exists() else read(run/'runtime-result.json') if (run/'runtime-result.json').exists() else {}
    runtime=read(run/'runtime-result.json') if (run/'runtime-result.json').exists() else {}
    dossier={'schema':'programbench-research-case-v1','task':row['task'],'subject':'programbench:first-attempt:'+row['task'],
        'solver_run':str(run),'first_admission_after_preparation_repair':first_solver,
        'recorded_result':row,'result_source':{'path':str(result_path),'sha256':digest(result_path)} if result_path else None,
        'native_result_source':{'path':str(native_path),'sha256':digest(native_path)} if native_path.exists() else None,
        'native_status_snapshot':result.get('status'),'native_budget':result.get('budget'),
        'native_elapsed_seconds':runtime.get('elapsed'),
        'native_stop_reason':result.get('stop_reason'),'native_internal_support':result.get('internal_support'),'source_custody':origin,
        'ledger':ledger,'sessions':sessions,'statements':{'path':str(message_path),'sha256':digest(message_path),'count':len(messages)},
        'coverage':{'outcome_indexed':True,'ledger_indexed':ledger['available'],'rollout_sessions_indexed':len(sessions),
            'semantic_root_cause_review':'not asserted by this mechanical index','source_parse_errors':sum(len(s['parse_errors']) for s in sessions)}}
    write(done,dossier);return dossier


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True);parser.add_argument('--completion',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=8)
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    combined=read(args.completion/'COMBINED_RESULTS.json');records=read(args.completion/'completion-list.json')['records']
    first={r['task'] for r in records if r['kind']=='first_solver'}
    rows=combined['rows'];tasks=[r['task'] for r in rows]
    if len(set(tasks))!=len(tasks):raise ValueError('duplicate task in cohort')
    snapshot={'combined':combined,'completion_records':records,
        'sources':{str(p):digest(p) for p in [args.completion/'COMBINED_RESULTS.json',args.completion/'completion-list.json',args.original/'RESULTS.json']}}
    snapshot_path=output/'input-snapshot.json'
    if snapshot_path.exists() and read(snapshot_path)!=snapshot:
        raise ValueError('retained population changed; use a new research output')
    write(snapshot_path,snapshot)
    results=[];failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(case,row,(args.completion if row['task'] in first else args.original)/'runs'/row['task'],output,row['task'] in first):row['task'] for row in rows}
        for future in concurrent.futures.as_completed(futures):
            task=futures[future]
            try:results.append(future.result())
            except Exception as error:failures.append({'task':task,'error':type(error).__name__+': '+str(error)})
            write(output/'progress.json',{'completed':len(results),'failed':failures,'total':len(rows),'at':time.time()})
            print(json.dumps({'completed':len(results),'failed':len(failures),'task':task}),flush=True)
    ordered={r['task']:r for r in results};census=[]
    for row in rows:
        d=ordered.get(row['task']);external=row.get('external') or {};ledger=d['ledger'] if d else {}
        budget=(d.get('native_budget') or {}) if d else {}
        census.append({'task':row['task'],'external':external,'vals_luna_max_percent':row.get('vals_luna_max_percent'),
            'requests':budget.get('used',row.get('requests')),'solve_minutes':(d['native_elapsed_seconds']/60
                if d and isinstance(d.get('native_elapsed_seconds'),(int,float)) else row.get('solve_minutes')),
            'stop_reason':d.get('native_stop_reason') or row.get('stop_reason') if d else row.get('stop_reason'),
            'status':d.get('native_status_snapshot') or row.get('native_status') if d else row.get('native_status'),
            'internal_support':(d.get('native_internal_support') if d and d.get('native_internal_support') is not None else row.get('internal_support')),
            'coverage':d['coverage'] if d else {'index_error':next(e for e in failures if e['task']==row['task'])},
            'choices':ledger.get('choices'),'phases':ledger.get('phases'),'captured_subjects':ledger.get('distinct_captured_subjects'),
            'dossier':str(output/'cases'/row['task']/'dossier.json') if d else None})
    write(output/'census.json',{'schema':'programbench-research-census-v1','cohort_size':len(rows),
        'scope':combined['scope'],'recorded_strict_valid_scores':combined['valid_scores'],'recorded_mean_percent':combined['mean_percent'],
        'reference_limit':'Vals differs in request resources; evaluation conditions require their own qualification',
        'rows':census,'index_failures':failures})
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
