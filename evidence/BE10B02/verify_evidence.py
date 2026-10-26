"""Main-agent audit; read-only active DB and budget, no model/network generation."""
from contextlib import closing
import hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass import backend_diagnosis_service as service,backend_diagnosis_criteria as criteria
from apps.compass import backend_snapshot as snapshots,backend_sources as sources
from apps.compass.backend_model import ModelError
h=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads((ROOT/p).read_text())
b=read('evidence/BE10B02/baseline.json');assert b['diff']==b['cached_diff']==''
for p,sha in b['preserved_files'].items():assert h((ROOT/p).read_bytes())==sha,p
assert h((ROOT/'var/clinic-20261026-access.md').read_bytes())==b['access_sha256']
with closing(sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)) as db:
 tables={t:h(json.dumps(sorted(json.dumps(r,ensure_ascii=False,default=str) for r in db.execute('SELECT * FROM "'+t+'"')),ensure_ascii=False).encode()) for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 assert tables==b['active_db_tables']
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 patients=db.execute('SELECT count(*) FROM patients').fetchone()[0]
with closing(sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True)) as db:
 assert list(db.execute('SELECT count(*),sum(micro_usd) FROM calls WHERE rowid<=28').fetchone())==b['ledger']==[28,50905]
 ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone());assert ledger==[34,83138]
 assert ledger[1]<=100000
for path in ['apps/compass/backend_diagnoses.py','apps/compass/backend_diagnosis_criteria.py','apps/compass/backend_risk_context.py','apps/compass/backend_risk_rules.py','data/backend/diagnosis-criteria-v1.json','data/backend/diagnosis-domains-v1.json','data/backend/source-catalog-v1.json','data/retrieval/source-registry.json','apps/requirements.lock','plan/manifest.json']:
 assert (ROOT/path).read_bytes()==subprocess.check_output(['git','show',b['head']+':'+path],cwd=ROOT),path
coverage=read('plan/coverage.json');old=json.loads(subprocess.check_output(['git','show',b['head']+':plan/coverage.json'],cwd=ROOT))
assert [(i['id'],i['text'],i['subchecks'],i['fulfilment_status']) for i in old['items']]==[(i['id'],i['text'],i['subchecks'],i['fulfilment_status']) for i in coverage['items']]
req=read('plan/backend/requirements.json');oldreq=json.loads(subprocess.check_output(['git','show',b['head']+':plan/backend/requirements.json'],cwd=ROOT))
assert [(i['id'],i['text'],i['status']) for i in oldreq['items']]==[(i['id'],i['text'],i['status']) for i in req['items']]
state=read('memory/STATE.json');assert state['current_slice']=='BE10B02' and state['last_accepted_slice']=='BE10B01'
assert state['slices']['BE10B02']['status']=='in_progress' and state['slices']['BE10B02']['commit_ref'] is None
assert state['backend_program']['clinical_release']=='blocked'
for sid in ('BE10','BE10B','BE11'):assert state['slices'][sid]['status']=='planned'
quality=read('evidence/BE10/diagnosis-quality.json');assert quality==read('evidence/BE10B02/diagnosis-quality.json')
assert quality['pass'] is False and quality['admitted'] is False
freeze=read('evidence/BE10B02/quality-freeze.json')
assert h((ROOT/'evidence/BE10B02/quality-cases.json').read_bytes())==freeze['cases_sha256']
assert h((ROOT/'evidence/BE10B02/quality-policy.md').read_bytes())==freeze['policy_sha256']
# Exact recorded model version/input/quote mapping independently reconstructed.
verified=0
for name in ('depressive','mania','medication'):
 value=read('evidence/BE10B02/live-'+name+'.json');report=value['report']['diagnosis_report'];ctx=report['context'];snapshot=value['snapshot']
 assert snapshots.digest(snapshot)==ctx['snapshot_sha256']
 units={u['unit_id']:u for u in service.context.prepare_snapshot(snapshot)}
 for e in ctx['evidence']:
  u=units[e['unit_id']];assert u['text'][e['start']:e['end']]==e['quote']
  assert u['source_ref']==e['source_ref'] and u['source_sha256']==e['source_sha256'] and u['metadata']==e['metadata'];verified+=1
 assert report['model_metadata']['test_double'] is False
 assert report['model_metadata']['returned_model']=='deepseek-flash'
 assert value['http_status']==200 and value['http_report_matches'] is True and value['clinical_actions']==0
 assert ctx['established_diagnosis'] is ctx['diagnosis_code'] is ctx['plan'] is None
 assert ctx['clinical_ready'] is False
 # Production route is closed despite explicit synthetic input.
 try:service.execute('diagnosis',snapshot)
 except ModelError as exc:assert exc.code=='diagnosis_quality_not_admitted'
 else:raise AssertionError('quality gate open')
catalog=criteria.release();current=sources.capture()
for c in catalog['conditions'].values():
 sources.require(current,[c['admission_claim']],'diagnosis',age_min=18,age_max=120,condition=c['condition'])
 src=current['sources'][c['source_id']]['source'];assert h((ROOT/src['path']).read_bytes())==src['sha256']
allowed={'apps/compass/backend_diagnosis_service.py','apps/compass/backend_analyses.py','apps/compass/backend_jobs.py','apps/compass/backend_sources.py','apps/compass/web.py','apps/tests/test_backend_diagnosis_integration.py','docs/architecture/backend-api.json','docs/architecture/backend-diagnoses.md','START_HERE.md','memory/STATE.json','memory/sessions/BE10B02.md','memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json','plan/backend/requirements.json','plan/coverage.json','plan/COVERAGE.md','evidence/BE10/diagnosis-quality.json'}
changed=set(subprocess.check_output(['git','diff','HEAD','--name-only'],cwd=ROOT,text=True).splitlines())
new=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())-set(b['preserved_files'])
for p in changed|new:assert p in allowed or p.startswith('evidence/BE10B02/'),p
secret=(ROOT/'var/deepseek-api-key').read_bytes().strip()
for p in changed|new:
 assert secret not in (ROOT/p).read_bytes(),p
print(json.dumps({'status':'PASS','active_tables_unchanged':len(tables),'patients':patients,'integrity':'ok','foreign_keys':'PASS','access_and_preserved_files':'PASS','preserved_files':len(b['preserved_files']),'ledger':ledger,'new_network_reservations':6,'old_ledger_preserved':True,'parent_criteria_and_statuses_preserved':True,'requirements':len(coverage['items']),'subchecks':sum(len(i['subchecks']) for i in coverage['items']),'exact_citations_checked':verified,'quality':'FAIL_NOT_ADMITTED','default_model_execution_blocked':True,'scope':'PASS','secret_scan':'PASS','current_runtime_sha256':snapshots.digest(service.release())},ensure_ascii=False,indent=2))
