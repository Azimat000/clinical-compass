"""Read-only planning audit; comparison against the recorded pre-work commit."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
def load(p):return json.loads((ROOT/p).read_text())
def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args],text=True)
baseline=load('evidence/frontend-plan-2026-10-27/baseline.json')
def old(p):return json.loads(git('show',baseline['head']+':'+p))
s=load('memory/STATE.json');m=load('plan/manifest.json');c=load('plan/coverage.json')
f=load('plan/frontend/requirements.json');cases=load('plan/frontend/scenarios.json')['cases']
ids=[f'FE{i:02}' for i in range(1,13)];byid={x['id']:x for x in m['slices']}
assert s['current_slice'] is None and s['last_accepted_slice']=='BE16' and s['next_slice']=='FE01'
assert [x['id'] for x in m['slices'][:12]]==ids
assert all(s['slices'][i]['status']=='planned' and s['slices'][i]['commit_ref'] is None for i in ids)
assert all(s['slices'][i]['status']=='blocked' and s['slices'][i]['disposition']=='skipped_by_user' for i in ['BE17','BE18','BE19'])
for sid,entry in old('memory/STATE.json')['slices'].items():
 if entry['status']=='accepted':assert s['slices'][sid]==entry,sid
for i,sid in enumerate(ids):
 card=byid[sid];assert card['depends_on']==(['BE16'] if i==0 else [ids[i-1]])
 text=(ROOT/f'plan/slices/{sid}.md').read_text()
 for n,criterion in enumerate(card['acceptance'],1):assert f'{sid}-A{n:02}: {criterion}' in text
 for task in card['tasks']:assert task in text
 assert card['acceptance_tag']==f'slice/{sid}'
for row,previous in zip(c['items'],old('plan/coverage.json')['items']):
 assert row['id']==previous['id']
 for k,v in previous.items():
  if k=='verification_slices':assert set(v)<=set(row[k])
  else:assert row[k]==v,(row['id'],k)
assert len(c['items'])==len(old('plan/coverage.json')['items'])
assert load('plan/backend/requirements.json')['items']==old('plan/backend/requirements.json')['items']
assert len(f['items'])==12 and len(cases)==12
caseids={x['id'] for x in cases}
for r in f['items']:
 assert r['status']=='planned' and r['actual_evidence']==[]
 assert set(r['implementation_slices']+r['verification_slices'])<=set(ids)
 assert set(r['scenario_ids'])<=caseids
assert {x['patient_id'] for x in cases[:10]}=={f'P{i}' for i in range(201,211)}
for p,h in baseline['pre_existing_untracked_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
for p in ['var/clinic-20261026-access.md','apps/requirements.lock']:
 assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==baseline['baseline_sha256'][p],p
before=old('memory/BUDGET.json');after=load('memory/BUDGET.json')
for k,v in before.items():
 if k not in ['notes','last_plan_check']:assert after[k]==v,k
changed=git('diff','--name-only',baseline['head']).splitlines()
allowed={'AGENTS.md','START_HERE.md','docs/design/README.md','memory/BLOCKERS.md','memory/BUDGET.json','memory/DECISIONS.md','memory/EXTERNAL.md','memory/STATE.json','plan/COVERAGE.md','plan/backend/README.md','plan/backend/requirements.json','plan/coverage.json','plan/manifest.json','plan/slices/BE17.md','plan/slices/BE18.md','plan/slices/BE19.md','plan/slices/UI08.md','memory/sessions/frontend-plan-2026-10-27.md'}
for p in changed:
 assert p in allowed or p=='tools/test_plan_validation.py' or p.startswith(('plan/frontend/','evidence/frontend-plan-2026-10-27/')) or p in {f'plan/slices/{i}.md' for i in ids},p
for path in ['README.md','SESSION.md','requirements.json','scenarios.json']:assert (ROOT/'plan/frontend'/path).is_file()
print(json.dumps({'status':'PASS','new_slices':12,'frontend_requirements':12,'planned_scenarios':12,'patients_covered':10,'accepted_history_preserved':True,'original_requirements_and_subchecks_preserved':True,'backend_requirement_statuses_unchanged':True,'foreign_files_unchanged':4,'credentials_unchanged':True,'budget_accounting_unchanged':True,'application_edits':False,'next_slice':'FE01'},ensure_ascii=False,indent=2))
