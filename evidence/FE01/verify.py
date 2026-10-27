"""Main-agent acceptance: protected files, live tables, scope and coverage remain intact."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'evidence/FE01'
baseline=json.loads((OUT/'baseline.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for group in ['protected','preexisting_untracked']:
    for path, digest in baseline[group].items():
        assert sha(ROOT/path)==digest, f'Changed preserved file: {path}'
with sqlite3.connect(f'file:{ROOT}/var/compass.sqlite3?mode=ro',uri=True) as db:
    tables={n:hashlib.sha256(repr(sorted(db.execute('SELECT * FROM "'+n+'"').fetchall(),key=repr)).encode()).hexdigest() for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert tables==baseline['database_tables'], 'Active data changed'
with sqlite3.connect(f'file:{ROOT}/var/deepseek-budget.sqlite3?mode=ro',uri=True) as db:
    ledger=list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
assert ledger==[160,748067], 'Model accounting changed since BE16'
with urlopen('http://127.0.0.1:8000/healthz',timeout=5) as r:
    assert r.status==200
    health=json.loads(r.read())
assert health['schema_version']=='015_medication_marks'
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True)
owned=baseline['ownership']['main']
def allowed(p): return any(p==o or (o.endswith('/') and p.startswith(o)) for o in owned)
changed=git('diff','--name-only',baseline['head']).splitlines()
new=git('ls-files','--others','--exclude-standard').splitlines()
for path in changed+new:
    assert allowed(path) or path in baseline['preexisting_untracked'], f'Unexpected change: {path}'
before=json.loads(git('show',baseline['head']+':plan/coverage.json'))['items']
after=json.loads((ROOT/'plan/coverage.json').read_text())['items']
assert len(before)==len(after)
for old,new_item in zip(before,after):
    assert old['id']==new_item['id']
    assert old['subchecks']==new_item['subchecks']
    assert old['fulfilment_status']==new_item['fulfilment_status']
    assert set(old['actual_evidence'])<=set(new_item['actual_evidence'])
browser=json.loads((OUT/'browser.json').read_text())
assert browser['status']=='PASS' and len(browser['checks'])==130 and browser['writes']==[]
assert 'Ran 49 tests' in (OUT/'targeted-tests.log').read_text() and (OUT/'targeted-tests.log').read_text().rstrip().endswith('OK')
for name in ['signals','diagnosis','plan']:
    for width in [375,768,1440]:
        for prefix in ['before','after','block']:
            assert (OUT/f'screenshots/{prefix}-{name}-{width}.png').is_file()
result={'status':'PASS','protected_files':len(baseline['protected']),'preexisting_files':len(baseline['preexisting_untracked']),
        'active_tables_unchanged':len(tables),'active_schema':health['schema_version'],'live_health':200,
        'ledger':ledger,'new_model_calls':0,'targeted_tests':49,'browser_checks':130,'backend_integration':False,
        'coverage_preserved':len(after),'changed_tracked':changed,'new_owned_files':len([p for p in new if allowed(p)]),
        'clinical_release':'blocked','full_regression':'deferred_by_user'}
(OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
