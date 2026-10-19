"""Main-agent verification: baseline, protected inputs, live prior data and secrets."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / 'evidence/S06/baseline.json').read_text())
assert BASE['status'] == '' and BASE['diff'] == ''
protected = [p for p in BASE['sha256'] if p.startswith(('research/', 'data/', 'docs/clinical/', 'plan/slices/'))]
protected += ['plan/manifest.json', 'plan/contest-obligations.json', 'apps/requirements.lock',
              'apps/compass/migrations/001_initial.sql', 'apps/compass/migrations/002_access.sql']
for path in protected:
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == BASE['sha256'][path], path
baseline_coverage = json.loads(subprocess.check_output(['git', 'show', BASE['commit'] + ':plan/coverage.json'], cwd=ROOT))
coverage = json.loads((ROOT / 'plan/coverage.json').read_text())
assert len(coverage['items']) == len(baseline_coverage['items']) == 83
for before, after in zip(baseline_coverage['items'], coverage['items']):
    for key in before.keys() - {'fulfilment_status', 'actual_evidence'}:
        assert before[key] == after[key], (before['id'], key)
assert sum(len(r['subchecks']) for r in coverage['items']) == 160
# Compare hashes of the SAME old columns in the stopped S05 snapshot and live upgraded database.
# The runtime emits only table names/counts and row hashes, never credentials or record bodies.
with sqlite3.connect(ROOT / 'var/s06-docker-before.sqlite3') as old:
    tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'encounter_search%' ORDER BY name")]
    columns = {t: [r[1] for r in old.execute('PRAGMA table_info(' + t + ')')] for t in tables}
    mutable = {'sessions', 'login_challenges', 'login_limits'}
    before_hashes = {t: [hashlib.sha256(json.dumps(r,ensure_ascii=False).encode()).hexdigest() for r in old.execute('SELECT * FROM '+t)]
                     for t in tables if t not in mutable}
script = '''import sqlite3,json,hashlib
columns=json.loads(%r)
with sqlite3.connect('/app/var/compass.sqlite3') as db:
 db.execute('BEGIN')
 rows={t:[hashlib.sha256(json.dumps(r,ensure_ascii=False).encode()).hexdigest() for r in db.execute('SELECT '+','.join(cs)+' FROM '+t)] for t,cs in columns.items()}
 counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('clinical_entries','self_reports','observations','adverse_events','care_actions','catalog_versions','assessments','patients')}
 print(json.dumps({'hashes':rows,'counts':counts,'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'foreign_keys':db.execute('PRAGMA foreign_key_check').fetchall()}))
''' % json.dumps(columns)
result = json.loads(subprocess.check_output(['docker','compose','-p','hac-s04','exec','-T','web','python','-c',script],cwd=ROOT))
for table, hashes in before_hashes.items():
    assert set(hashes) <= set(result['hashes'][table]), table
assert result['integrity'] == 'ok' and result['foreign_keys'] == []
assert result['counts']['patients'] == 6
assert result['counts']['clinical_entries'] == 2 and result['counts']['adverse_events'] == 1
assert all(result['counts'][t] == 0 for t in ('care_actions','catalog_versions','assessments'))
changed = subprocess.check_output(['git','diff',BASE['commit'],'--name-only'],cwd=ROOT,text=True).splitlines()
new = subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
creds = json.loads((ROOT/'var/s05-credentials.json').read_text())
for path in changed + new:
    if Path(path).suffix in ('.png', '.sqlite3'):
        continue
    raw = (ROOT/path).read_bytes()
    for cred in creds:
        assert cred['password'].encode() not in raw, 'Local credential in ' + path
summary = {'baseline_commit':BASE['commit'],'baseline_clean':True,'protected_input_files':len(set(protected)),
           'requirements':83,'subchecks':160,'preserved_old_tables':sorted(before_hashes),
           'mutable_auth_tables_excluded':sorted(mutable),'runtime_counts':result['counts'],
           'integrity':result['integrity'],'foreign_key_violations':len(result['foreign_keys']),
           'local_passwords_checked':len(creds),'new_or_changed_paths':sorted(changed+new)}
print(json.dumps(summary,ensure_ascii=False,indent=2))
