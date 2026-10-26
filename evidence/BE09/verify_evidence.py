"""Main-agent acceptance gate: baseline, scope, coverage, checks, limits and evidence."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

ROOT=Path(__file__).resolve().parents[2]
def read(p):return json.loads((ROOT/p).read_text())
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True)
b=read('evidence/BE09/baseline.json')
assert b['diff']==b['cached_diff']==''
assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in b['untracked'].items())
paths=git('diff',b['head'],'--name-only').splitlines()+git('ls-files','--others','--exclude-standard').splitlines()
scopes=b['scope']+list(b['scope_extensions'])
for p in paths:
    assert p in b['untracked'] or any(p.startswith(s) if s.endswith('/') else p==s for s in scopes),p
    if p not in b['untracked']:assert Path(p).suffix not in {'.html','.css','.js'},p
for path in ('plan/coverage.json','plan/backend/requirements.json'):
    old=json.loads(git('show',b['head']+':'+path));new=read(path)
    for d in (old,new):
        for item in d['items']:item.pop('actual_evidence',None)
    assert old==new,path
coverage=read('plan/coverage.json');assert len(coverage['items'])==83
assert sum(len(i['subchecks']) for i in coverage['items'])==160
assert git('show',b['head']+':plan/manifest.json')==(ROOT/'plan/manifest.json').read_text()
checks=(ROOT/'evidence/BE09/check.log').read_text()
assert re.search(r'Ran 775 tests in [0-9.]+s\n\nOK',checks)
assert re.search(r'Ran 70 tests in [0-9.]+s\n\nOK',checks)
assert 'No broken requirements found.' in checks
assert '"status": "PASS"' in checks
assert not re.search(r'\nFAILED|\nFAIL:|\nERROR:',checks)
live=read('evidence/BE09/live-channel.json');copy=read('evidence/BE09/copy-check.json')
assert live['pass'] and copy['pass'] and live['external_model_calls']==0
assert live['restart_receipt_preserved'] and not live['view_or_decision_inferred']
assert copy['active_rows_unchanged'] and copy['jobs_enabled']==0 and copy['mode']=='0o600'
assert copy['old_tables_preserved']==80 and copy['old_triggers_preserved']==74
with sqlite3.connect((ROOT/'var/deepseek-budget.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
    count,amount=db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone()
assert (count,amount)==(27,45150) and amount<=50000
state=read('memory/STATE.json')
assert state['last_accepted_slice']=='BE09' and state['current_slice'] is None and state['next_slice']=='BE10'
assert state['backend_program']['clinical_release']=='blocked'
for p in ('evidence/BE09/acceptance.md','memory/sessions/BE09.md'):
    t=(ROOT/p).read_text();assert 'STATUS: ACCEPTED' in t and 'PENDING' not in t
result={'pass':True,'changed_scope_checked':True,'application_tests':775,'tool_tests':70,
        'original_requirements':83,'subchecks':160,'statuses_preserved':True,'no_new_slices':True,
        'preserved_untracked_files':len(b['untracked']),'real_http_channel':True,'receipt_ms':live['record_to_physician_receipt_ms'],
        'human_reading_or_clinical_validation':False,'active_database_unchanged':True,'live_schema':copy['active_health']['schema_version'],
        'ledger_calls':count,'ledger_micro_usd':amount,'external_model_calls':0,'clinical_release':'blocked',
        'code_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if p.startswith('apps/') and p not in b['untracked']}}
(ROOT/'evidence/BE09/independent-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
