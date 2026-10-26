"""Main-agent acceptance: actual scope/state/evidence, preserved data, no model calls."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
b=json.loads((ROOT/'evidence/BE07/baseline.json').read_text())
assert b['diff']==b['staged_diff']==''
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
for name,value in b['preserved_files'].items(): assert sha(ROOT/name)==value,name
changed=set(subprocess.check_output(['git','diff','--name-only',b['head']],cwd=ROOT,text=True).splitlines())
changed.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
foreign=set(b['preserved_files'])
for name in changed:
    assert name in b['owned_paths'] or name in foreign or name.startswith('evidence/BE07/'),name
assert not any(name.endswith(('.html','.css','.js')) for name in changed-foreign)
old=json.loads(subprocess.check_output(['git','show',b['head']+':plan/coverage.json'],cwd=ROOT))
new=json.loads((ROOT/'plan/coverage.json').read_text())
assert len(new['items'])==83 and sum(len(i.get('subchecks',[])) for i in new['items'])==160
for a,c in zip(old['items'],new['items']):
    assert {k:v for k,v in a.items() if k!='actual_evidence'}=={k:v for k,v in c.items() if k!='actual_evidence'}
    assert set(a.get('actual_evidence',[]))<=set(c.get('actual_evidence',[]))
old_state=json.loads(subprocess.check_output(['git','show',b['head']+':memory/STATE.json'],cwd=ROOT))
state=json.loads((ROOT/'memory/STATE.json').read_text())
for sid,entry in old_state['slices'].items():
    if sid!='BE07': assert state['slices'][sid]==entry,sid
assert state['last_accepted_slice']=='BE07' and state['next_slice']=='BE08' and state['current_slice'] is None
assert state['backend_program']['clinical_release']=='blocked'
assert not state['backend_program']['active_service_migrated']
with sqlite3.connect('file:'+str(ROOT/'var/deepseek-budget.sqlite3')+'?mode=ro',uri=True) as db:
    ledger=db.execute('SELECT sum(micro_usd),count(*) FROM calls').fetchone()
assert ledger==(36739,23),ledger
secret=(ROOT/'var/deepseek-api-key').read_bytes().strip()
assert secret
for name in changed-foreign:
    path=ROOT/name
    if path.is_file(): assert secret not in path.read_bytes(),name
check=(ROOT/'evidence/BE07/check.log').read_text()
assert 'Ran 725 tests in 226.988s\n\nOK' in check
assert 'Ran 70 tests in 14.808s\n\nOK' in check
assert 'No broken requirements found.' in check
final=(ROOT/'evidence/BE07/targeted-final.log').read_text()
assert 'Ran 75 tests in 30.615s\n\nOK' in final
live=json.loads((ROOT/'evidence/BE07/live-processes.json').read_text())
assert live['pass'] and live['production_cli_processes']==3 and live['model_calls']==live['network_calls']==0
assert not live['source_fixture_substitution']
assert {p for out in live['outputs'] for p in out['pattern_ids']}=={
    'DEP-SUICIDE-FACT','GAD-PSY-REVIEW','GAD-ADVERSE-REVIEW','GAD-INITIAL-ANXIETY'}
assert [out['assessment'] for out in live['outputs']]==['potential_risk','potential_risk','no_pattern_found']
assert all(out['attempts']==1 and out['release']=='blocked' and out['model'] is None for out in live['outputs'])
copy=json.loads((ROOT/'evidence/BE07/copy-check.json').read_text())
assert copy['pass'] and copy['original_tables']==80 and copy['source_mode']=='ro' and copy['copy_mode']=='0o600'
assert copy['old_clinical_tables_and_schema_preserved'] and copy['audit_only_appended']
assert len(copy['outcomes'])==10 and all(o['status']=='insufficient_data' for o in copy['outcomes'])
with urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=5) as response: health=json.load(response)
assert health['status']=='ok' and health['schema_version']=='015_medication_marks' and health['foreign_keys']
paths=[name for name in changed-foreign if name.endswith('.py') and name.startswith('apps/compass/')]
report={'status':'PASS','scope_compliance':'PASS','preserved_foreign_files':len(foreign),
        'requirements':83,'subchecks':160,'original_requirement_statuses_preserved':True,
        'other_slice_statuses_preserved':True,'app_regression_tests':725,'tool_tests':70,
        'final_affected_tests':75,'live_production_processes':3,'copy_cases':10,'copy_old_tables':80,
        'ledger_micro_usd':ledger[0],'ledger_calls':ledger[1],'secrets_absent':True,
        'final_code_sha256':{name:sha(ROOT/name) for name in sorted(paths)},'live_health':health,
        'clinical_release':'blocked','other_slices_started':False}
print(json.dumps(report,ensure_ascii=False,indent=2))
