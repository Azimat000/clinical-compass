"""Main-agent acceptance: actual state, diff, original history and restrictions."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'evidence/FE02'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((OUT/'baseline.json').read_text())
for group in ['protected','preexisting_untracked']:
    for path,digest in b[group].items():assert sha(ROOT/path)==digest,path
# This pinned clinical module was considered initially, then deliberately left unchanged.
git=lambda *a:subprocess.check_output(['git',*a],cwd=ROOT,text=True)
assert (ROOT/'apps/compass/backend_analyses.py').read_text()==git('show',b['head']+':apps/compass/backend_analyses.py')
with sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True) as db:
    tables={n:hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "'+n+'"').fetchall(),key=repr)).encode()).hexdigest() for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables==b['database_tables'],'Working DB changed'
    assert dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))==b['triggers']
assert sha(ROOT/'var/clinic-20261026-access.md')==b['accounts_sha256']
with urlopen('http://127.0.0.1:8000/healthz',timeout=5) as r:
    health=json.loads(r.read());assert r.status==200
assert health['schema_version']=='015_medication_marks'
with sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True) as db:
    ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
assert ledger==[160,748067]
r=json.loads((OUT/'runtime.json').read_text());assert r['status']=='PASS' and r['checks_count']==69
assert r['ledger_before']==r['ledger_after']==ledger and r['new_reservations']==0
assert r['original_triggers_preserved']==74 and r['migration_preserved_tables']==80
assert r['schema']=='022_backend_plan_reviews' and r['runtime_stopped']
for proc in r['processes']:
    # Do not signal PIDs: a later unrelated process could reuse one.
    result=subprocess.run(['ps','-p',str(proc['pid']),'-o','command='],capture_output=True,text=True)
    assert str(ROOT/'var/FE02-integration.sqlite3') not in result.stdout
with sqlite3.connect('file:'+str(ROOT/'var/FE02-integration.sqlite3')+'?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert db.execute('SELECT enabled FROM backend_job_settings').fetchone()[0]==0
assert (ROOT/'var/FE02-integration.sqlite3').stat().st_mode&0o077==0
browser=json.loads((OUT/'browser.json').read_text());assert browser['status']=='PASS' and browser['checks_count']==26 and browser['clinical_submissions']==0
preflight=json.loads((OUT/'preflight.json').read_text());assert preflight['diagnosis_runtime_admitted'] and preflight['therapy_runtime_admitted']
log=(OUT/'targeted-tests.log').read_text();assert 'Ran 78 tests' in log and log.rstrip().endswith('OK')
assert 'No broken requirements found.' in (OUT/'dependencies.log').read_text()
changed=git('diff','--name-only',b['head']).splitlines()
new=git('ls-files','--others','--exclude-standard').splitlines()
def allowed(p):return any(p==o or o.endswith('/') and p.startswith(o) for o in b['ownership'])
for path in changed+new:assert allowed(path) or path in b['preexisting_untracked'],path
old=json.loads(git('show',b['head']+':plan/coverage.json'))['items']
after=json.loads((ROOT/'plan/coverage.json').read_text())['items']
assert len(old)==len(after)
for before,current in zip(old,after):
    assert before['id']==current['id'] and before['subchecks']==current['subchecks']
    assert before['fulfilment_status']==current['fulfilment_status']
    assert set(before['actual_evidence'])<=set(current['actual_evidence'])
result={'status':'PASS','active_tables_unchanged':len(tables),'active_triggers_unchanged':len(b['triggers']),
        'active_schema':health['schema_version'],'active_health':200,'accounts_unchanged':True,
        'protected_files':len(b['protected']),'preexisting_files':len(b['preexisting_untracked']),
        'ledger':ledger,'new_model_calls':0,'targeted_tests':78,'http_checks':69,'browser_checks':26,
        'clinical_release':'blocked','full_regression':'deferred_by_user','changed_tracked':changed,
        'coverage_preserved':len(after),'new_dependencies':False,'working_service_restarted':False}
if '--read-only' not in sys.argv:
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
