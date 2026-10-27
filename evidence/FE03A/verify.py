"""Independent main-agent acceptance of scope, preservation and measured packets."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'evidence/FE03A'
b=json.loads((OUT/'baseline.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
git=lambda *a:subprocess.check_output(['git',*a],cwd=ROOT,text=True)
for group in ['protected','preexisting_untracked']:
    for p,h in b[group].items():assert sha(ROOT/p)==h,p
with sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True) as db:
    tables={n:hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "'+n+'"').fetchall(),key=repr)).encode()).hexdigest()
            for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert tables==b['database_tables']
assert sha(ROOT/'var/clinic-20261026-access.md')==b['access_sha256']
with urlopen('http://127.0.0.1:8000/healthz',timeout=5) as response:
    health=json.loads(response.read());assert response.status==200
assert health['schema_version']=='015_medication_marks'
with sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True) as db:
    ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
assert ledger==[160,748067]
r=json.loads((OUT/'full-history.json').read_text())
assert r['status']=='PASS' and r['patients']==10 and r['branches']==20
assert len(r['results'])==20 and {x['patient_id'] for x in r['results']}=={'P'+str(i) for i in range(201,211)}
for item in r['results']:
    assert item['roundtrip_exact'] and item['source_sha256']==item['roundtrip_sha256']
    assert item['packet_count']==len(item['measurements'])==len(item['packet_sha256'])
    assert all(m['input_bytes']<=16000 and m['reservation_micro_usd']<=20000 for m in item['measurements'])
assert sum(x['packet_count'] for x in r['results'])==92
assert r['network_calls']==r['budget_reservations']==0
assert r['quality_gates_unchanged'] and not r['default_generator_changed']
with sqlite3.connect('file:'+r['copy']+'?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
assert (ROOT/r['copy']).stat().st_mode&0o077==0
log=(OUT/'targeted-tests.log').read_text();assert 'Ran 70 tests' in log and log.rstrip().endswith('OK')
assert 'No broken requirements found.' in (OUT/'dependencies.log').read_text()
# All original parent work/acceptance and the twelve planned scenarios remain.
old_manifest=json.loads(git('show',b['head']+':plan/manifest.json'))
old_parent=next(x for x in old_manifest['slices'] if x['id']=='FE03')
manifest=json.loads((ROOT/'plan/manifest.json').read_text());parent=next(x for x in manifest['slices'] if x['id']=='FE03');child=next(x for x in manifest['slices'] if x['id']=='FE03C')
for field in ['tasks','acceptance','outputs']:
    assert old_parent[field]==parent[field]==child[field],field
for old_card in old_manifest['slices']:
    current=next(x for x in manifest['slices'] if x['id']==old_card['id'])
    if old_card['id']!='FE03':assert current==old_card,old_card['id']
old_state=json.loads(git('show',b['head']+':memory/STATE.json'))
new_state=json.loads((ROOT/'memory/STATE.json').read_text())
assert old_state['backend_program']==new_state['backend_program']
for sid,entry in old_state['slices'].items():assert new_state['slices'][sid]==entry,sid
old_budget=json.loads(git('show',b['head']+':memory/BUDGET.json'))
new_budget=json.loads((ROOT/'memory/BUDGET.json').read_text())
for sid,value in old_budget['model_api_accounting'].items():assert new_budget['model_api_accounting'][sid]==value,sid
old_cases=json.loads(git('show',b['head']+':plan/frontend/scenarios.json'))
new_cases=json.loads((ROOT/'plan/frontend/scenarios.json').read_text())
assert old_cases['cases']==new_cases['cases'] and len(new_cases['cases'])==12
before=json.loads(git('show',b['head']+':plan/coverage.json'))['items'];after=json.loads((ROOT/'plan/coverage.json').read_text())['items']
assert len(before)==len(after)
for a,z in zip(before,after):
    assert a['id']==z['id'] and a['subchecks']==z['subchecks'] and a['fulfilment_status']==z['fulfilment_status']
    assert set(a['actual_evidence'])<=set(z['actual_evidence'])
changed=git('diff','--name-only',b['head']).splitlines();new=git('ls-files','--others','--exclude-standard').splitlines()
allowed=lambda p:any(p==a or a.endswith('/') and p.startswith(a) for a in b['ownership'])
for p in changed+new:assert allowed(p) or p in b['preexisting_untracked'],p
result={'status':'PASS','working_tables_unchanged':len(tables),'working_schema':health['schema_version'],
        'working_health':200,'access_unchanged':True,'protected_files':len(b['protected']),
        'preexisting_files':len(b['preexisting_untracked']),'ledger':ledger,'new_model_calls':0,
        'targeted_tests':70,'patients':10,'branches':20,'packets':92,'roundtrip_exact':True,
        'parent_FE03_accepted':False,'parent_requirements_preserved':True,'D01_D12':'planned_not_seeded',
        'default_generator_changed':False,'clinical_release':'blocked','full_regression':'deferred_by_user',
        'changed_tracked':changed}
if '--read-only' not in sys.argv:(OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
