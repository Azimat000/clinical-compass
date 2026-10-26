"""Independent local acceptance checks; never writes clinical data or calls a model."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
base=json.loads((ROOT/'evidence/BE06/baseline.json').read_text())
assert base['diff']==base['staged_diff']==''
for name,digest in base['preserved_files'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
changed=set(subprocess.check_output(['git','diff','--name-only',base['head']],cwd=ROOT,text=True).splitlines())
changed.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
allowed=set(base['owned_paths'])
foreign=set(base['preserved_files'])
for name in changed:
    assert name in allowed or name in foreign or name.startswith('evidence/BE06/'),name
old=json.loads(subprocess.check_output(['git','show',base['head']+':plan/coverage.json'],cwd=ROOT))
new=json.loads((ROOT/'plan/coverage.json').read_text())
assert len(new['items'])==83
assert sum(len(x.get('subchecks',[])) for x in new['items'])==160
for a,b in zip(old['items'],new['items']):
    assert {k:v for k,v in a.items() if k!='actual_evidence'}=={k:v for k,v in b.items() if k!='actual_evidence'}
    assert set(a.get('actual_evidence',[]))<=set(b.get('actual_evidence',[]))
code_paths=['apps/compass/backend_jobs.py','apps/compass/backend_analyses.py','apps/compass/events.py','apps/compass/__main__.py','apps/compass/migrations/017_backend_jobs.sql']
key=(ROOT/'var/deepseek-api-key').read_bytes().strip()
assert key
for name in changed-foreign:
    p=ROOT/name
    if p.is_file():assert key not in p.read_bytes(),name
with sqlite3.connect(f'file:{ROOT}/var/deepseek-budget.sqlite3?mode=ro',uri=True) as db:
    ledger=db.execute('SELECT sum(micro_usd),count(*) FROM calls').fetchone()
assert ledger==(36739,23),ledger
live=json.loads((ROOT/'evidence/BE06/live-processes.json').read_text())
assert live['pass'] and live['real_lease_wait'] and live['lease_seconds']==90
assert live['network_calls']==0 and live['simultaneous_processes']==2
assert live['risk_failed_while_generation_alive_seconds']<live['lease_seconds']<=live['total_seconds']
assert sorted(live['terminal_counts'].values())==[1,1]
assert len(live['attempts'])==6
for field in ('risk','generation'):
    assert live[field]['status']=='failed' and live[field]['result'] is None
    assert live[field]['errors'][0]['code']=='operation_unavailable'
assert any(a['outcome']=='expired' for a in live['attempts'])
check=(ROOT/'evidence/BE06/check.log').read_text()
assert 'Ran 705 tests in 245.029s\n\nOK' in check
assert 'Ran 70 tests in 18.770s\n\nOK' in check
assert 'No broken requirements found.' in check
assert 'Ran 20 tests' in (ROOT/'evidence/BE06/targeted-final.log').read_text()
assert (ROOT/'evidence/BE06/targeted-final.log').read_text().rstrip().endswith('OK')
with urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=5) as response:
    health=json.load(response)
assert health['status']=='ok' and health['schema_version']=='015_medication_marks' and health['foreign_keys']
report={'status':'PASS','code_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in code_paths},
        'preserved_files':len(foreign),'scope_compliance':'PASS','requirements':83,'subchecks':160,
        'requirement_statuses_texts_preserved':True,'targeted_tests':20,'full_app_tests':705,'tool_tests':70,
        'live_processes':'PASS','ledger_micro_usd':ledger[0],'ledger_calls':ledger[1],
        'secret_absent':True,'active_service_health':health}
print(json.dumps(report,ensure_ascii=False,indent=2))
