"""Keep the pinned benchmark scalar and execution completeness as separate facts."""
import collections,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'controller'))
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def project(task):
 import procontract_canonical as canonical
 case=ROOT/'inputs/cases'/task;registry=case/'canonical-registry.json';pins=case/'canonical-pins.json'
 canonical.configure(registry,sha(registry));canonical.bind_pins(sha(pins));canonical.preflight()
 instance=canonical.fixture(task)
 from programbench.submission import score_instance,test_results_map
 from programbench.utils.load_data import get_active_branches,get_ignored_tests
 active=set(get_active_branches(instance));ignored=get_ignored_tests(instance)
 expected={f'{branch}/{name}' for branch in active for name in instance['branches'][branch]['tests'] if f'{branch}/{name}' not in ignored}
 run=ROOT/'runs'/task;archive=run/'submission.tar.gz';submission=sha(archive);records=[]
 for path in sorted((run/'evaluation').glob('attempt-*/*/'+task+'.eval.json')):
  record={'eval_json':str(path),'eval_sha256':sha(path),'evaluation_attempt':path.parent.parent.name}
  try:
   data=json.loads(path.read_text());receipt=json.loads(path.with_name('evaluation-receipt.json').read_text())
   binding=(receipt.get('raw_eval_sha256')==record['eval_sha256'] and receipt.get('submission_sha256')==submission and receipt.get('task')==task and receipt.get('registry_sha256')==sha(registry) and receipt.get('pins_sha256')==sha(pins) and receipt.get('adapter_sha256')==sha(Path(canonical.__file__)))
   vector=test_results_map(path,instance);value=score_instance(path,instance)
   actual=[f"{x['branch']}/{x['name']}" for x in data['test_results'] if x['branch'] in active and f"{x['branch']}/{x['name']}" not in ignored]
   identity_ok=set(actual)==expected and len(actual)==len(expected)
   counts=collections.Counter(x['status'] for x in data['test_results'] if f"{x['branch']}/{x['name']}" in expected)
   errors={'error_code':data.get('error_code'),'error_details':data.get('error_details'),'test_branch_errors':data.get('test_branch_errors',{})}
   infrastructure=bool(errors['error_code'] or errors['test_branch_errors'] or counts['system_error'])
   record.update(scorer_value=value,scorer_percent=value*100,passed=sum(vector.values()),eligible=len(vector),expected_eligible=len(expected),
    eligible_identity_verified=identity_ok,submission_binding_verified=binding,status_counts=dict(counts),evaluation_errors=errors,
    execution_complete=identity_ok and not counts['not_run'] and not infrastructure,
    reportable=binding and identity_ok and not infrastructure,
    scope='Unmodified pinned ProgramBench scorer; non-passed statuses count false. Execution completeness/errors remain separate.')
  except Exception as error:record['projection_error']={'type':type(error).__name__,'message':str(error)}
  records.append(record)
 selected=next((r for r in records if r.get('reportable')),None)
 runtime=json.loads((run/'runtime-result.json').read_text())
 solver_failure=runtime.get('failure')
 terminal_goal=runtime.get('stop_reason')
 external_stop=terminal_goal in ('native_goal_usageLimited','native_goal_budgetLimited')
 out={'at':time.time(),'task':task,'submission_sha256':submission,'attempts':records,
      'available':selected is not None,'selected':selected,
      'valid_instance':selected is not None and not solver_failure and not external_stop,
      'solver_failure':solver_failure,'terminal_goal_resource_stop':external_stop,
      'selection_policy':'First protocol-ordered artifact-bound, exact-eligible-vector result without evaluator/system errors; not_run alone does not hide a defined score. All other defined scalar/error records remain visible. No maximum-score selection.',
      'cohort':'programbench-gpt6-luna-20261106/procontract','cohort_attempt':1,'independent_retry':False,'part_of_original_aggregate':False}
 target=run/'benchmark-score.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(out,indent=2)+'\n');temp.replace(target)
 return out
if __name__=='__main__':print(json.dumps(project(sys.argv[1]),indent=2))
