"""Read-only dated evidence projection for rebuttal preparation."""
from pathlib import Path
from datetime import datetime,timezone
import csv,hashlib,json,random,statistics,time
ROOT=Path(__file__).resolve().parent
BASE=Path('/data/ProContract');sources={}
def read(p):
 p=Path(p);raw=p.read_bytes();sources[str(p)]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
def summary(v):return {'valid_instances':len(v),'mean_percent':statistics.mean(v.values()) if v else None,'at_least_95':sum(x>=95 for x in v.values()),'fully_resolved':sum(abs(x-100)<1e-9 for x in v.values())}
def comparison(a,b):
 keys=sorted(a.keys() & b.keys());d=[a[k]-b[k] for k in keys];rng=random.Random(20261107)
 samples=sorted(sum(rng.choices(d,k=len(d)))/len(d) for _ in range(10000))
 return {'n':len(keys),'ours_mean':statistics.mean(a[k] for k in keys),'reference_mean':statistics.mean(b[k] for k in keys),'delta_pp':statistics.mean(d),'task_bootstrap_95_percent_interval_pp':[samples[250],samples[9749]],'wins':sum(x>.0051 for x in d),'ties':sum(abs(x)<=.0051 for x in d),'losses':sum(x<-.0051 for x in d),'scope':'Paired tasks, seed20261107,10000 task resamples. Conditional on this observed valid task set; not repeated-run uncertainty or a held-out generalization estimate.'}
old=read(BASE/'programbench-luna-sol-vals-analysis-20261106/valid-view.json')
luna=read(BASE/'programbench-luna56-completion-20261107/COMPLETION.json')['values']
sol={t:v for t,v in old['sol_values'].items() if t not in set(old['sol_api_affected'])}
retry=read(BASE/'programbench-sol61-retries-20261106/MEASURED_COMPLETION.json')
for row in retry['rows']:
 if row['verified']:sol[row['task']]=row['score']['scorer_percent']
vals=read(BASE/'programbench-luna-sol-vals-analysis-20261106/vals-analysis-current.json');tasks=vals['heatmap']['taskOrder']
references={name:dict(zip(tasks,next(v['scores'] for v in vals['heatmap']['models'] if v['model']==model))) for name,model in [('luna','openai/gpt-5.6-luna'),('sol','openai/gpt-6.1-sol')]}
new={a:read(BASE/'programbench-gpt6-luna-20261106'/a/'STATUS.json') for a in ['procontract','vanilla-goal']}
paired_new={}
for a in new:
 data=read(BASE/'programbench-gpt6-luna-20261106'/a/'RESULTS.json');paired_new[a]={r['task']:r['score']['scorer_percent'] for r in data['rows'] if 'score' in r}
report={'at':time.time(),'utc':datetime.now(timezone.utc).isoformat(),'priority':'ProContract rebuttal','luna56':summary(luna),'sol61':summary(sol),'luna56_pending':sorted(set(tasks)-luna.keys()),'sol61_pending':sorted(set(tasks)-sol.keys()),'luna56_vs_vals':comparison(luna,references['luna']),'sol61_vs_vals':comparison(sol,references['sol']),'new_luna6_status':new,'new_luna6_common_scored':sorted(paired_new['procontract'].keys() & paired_new['vanilla-goal'].keys()),'reviewer_comments_received':False,'rsi_candidates_activated_in_live_cohorts':False,'source_sha256':sources,'scope':'Effective declared attempts/remeasurements. No best-of selection, missing-to-zero imputation, or rewriting of historical paper numbers.'}
(ROOT/'evidence-snapshot.json').write_text(json.dumps(report,indent=2)+'\n')
with (ROOT/'task-evidence.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['task','luna56','vals_luna56','sol61','vals_sol61','luna6_procontract','luna6_goal']);w.writeheader()
 for task in sorted(tasks):w.writerow({'task':task,'luna56':luna.get(task),'vals_luna56':references['luna'][task],'sol61':sol.get(task),'vals_sol61':references['sol'][task],'luna6_procontract':paired_new['procontract'].get(task),'luna6_goal':paired_new['vanilla-goal'].get(task)})
print(json.dumps({k:report[k] for k in ['utc','luna56','sol61','luna56_pending','sol61_pending','luna56_vs_vals','sol61_vs_vals','new_luna6_common_scored']},ensure_ascii=False))
