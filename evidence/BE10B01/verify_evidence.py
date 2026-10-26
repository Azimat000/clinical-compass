"""Main-agent read-only acceptance audit, independent of the test fixtures."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass import backend_diagnosis_criteria as criteria
from apps.compass import backend_sources as sources


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


baseline = read('evidence/BE10B01/baseline.json')
assert baseline['diff'] == baseline['cached_diff'] == ''
assert all(sha((ROOT / p).read_bytes()) == value for p, value in baseline['preserved_files'].items())
assert sha((ROOT / 'var/clinic-20261026-access.md').read_bytes()) == baseline['access_sha256']
with closing(sqlite3.connect('file:' + str(ROOT / 'var/compass.sqlite3') + '?mode=ro', uri=True)) as db:
    tables = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        rows = sorted(json.dumps(row, ensure_ascii=False, default=str) for row in db.execute('SELECT * FROM "' + table + '"'))
        tables[table] = sha(json.dumps(rows, ensure_ascii=False).encode())
    assert tables == baseline['active_db_tables']
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    patients = db.execute('SELECT count(*) FROM patients').fetchone()[0]
with closing(sqlite3.connect('file:' + str(ROOT / 'var/deepseek-budget.sqlite3') + '?mode=ro', uri=True)) as db:
    ledger = list(db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())
assert ledger == baseline['ledger'] == [28, 50905]
old = json.loads(subprocess.check_output(['git', 'show', baseline['head'] + ':plan/coverage.json'], cwd=ROOT, text=True))
coverage = read('plan/coverage.json')
assert [(i['id'], i['subchecks'], i['fulfilment_status']) for i in old['items']] == [
    (i['id'], i['subchecks'], i['fulfilment_status']) for i in coverage['items']]
oldmanifest = json.loads(subprocess.check_output(['git', 'show', baseline['head'] + ':plan/manifest.json'], cwd=ROOT, text=True))
manifest = read('plan/manifest.json')
original = next(i for i in oldmanifest['slices'] if i['id'] == 'BE10')['acceptance']
for sid in ('BE10', 'BE10B', 'BE10B02'):
    assert next(i for i in manifest['slices'] if i['id'] == sid)['acceptance'] == original
# The only pre-existing test change is the recorded two-line fixture isolation.
extra = baseline['additional_scope_baseline']['apps/tests/test_backend_alerts.py']
original_alert_test = subprocess.check_output(['git','show',baseline['head'] + ':apps/tests/test_backend_alerts.py'],cwd=ROOT)
assert extra['diff'] == '' and sha(original_alert_test) == extra['sha256']
fixed_alert_test = (ROOT / 'apps/tests/test_backend_alerts.py').read_bytes()
added = b'''        # Exercise this signal five times, regardless of the other alert's ID/order.
        self.db.execute("UPDATE outbox_events SET available_at='2999' WHERE id<>?", (row['event_id'],))
'''
assert fixed_alert_test.count(added) == 1 and fixed_alert_test.replace(added,b'') == original_alert_test
catalog = criteria.release()
current = sources.capture()
for c in catalog['conditions'].values():
    sources.require(current, [c['admission_claim']], 'diagnosis', age_min=18, age_max=120, condition=c['condition'])
    src = current['sources'][c['source_id']]['source']
    assert sha((ROOT / src['path']).read_bytes()) == src['sha256']
for p in ['apps/compass/backend_diagnoses.py', 'apps/compass/backend_jobs.py',
          'apps/compass/backend_analyses.py', 'data/backend/diagnosis-domains-v1.json',
          'data/retrieval/source-registry.json', 'data/backend/source-catalog-v1.json']:
    assert (ROOT / p).read_bytes() == subprocess.check_output(['git','show',baseline['head'] + ':' + p],cwd=ROOT)
key = (ROOT / 'var/deepseek-api-key').read_bytes().strip()
files = [ROOT / p for p in ['apps/compass/backend_diagnosis_criteria.py',
    'apps/tests/test_backend_diagnosis_criteria.py','data/backend/diagnosis-criteria-v1.json']]
files += [p for p in (ROOT / 'evidence/BE10B01').rglob('*') if p.is_file()]
assert key and all(key not in p.read_bytes() for p in files)
print(json.dumps({'status':'PASS','active_tables_unchanged':len(tables),'patients':patients,
    'integrity':'ok','foreign_keys':'PASS','preserved_files':len(baseline['preserved_files']),
    'access_unchanged':True,'ledger_calls':ledger[0],'ledger_micro_usd':ledger[1],
    'new_model_calls':0,'source_gates':'PASS','original_source_bytes':'PASS',
    'candidate_engine_jobs_api_registry_unchanged':True,'parent_acceptance_unchanged':True,
    'requirements':len(coverage['items']),'subchecks':sum(len(i['subchecks']) for i in coverage['items']),
    'fulfilment_unchanged':True,'catalog_sha256':catalog['catalog_sha256'],
    'engine_sha256':catalog['engine_sha256'],'research_sha256':catalog['evidence_sha256'],
    'content_review_sha256':catalog['content_review_sha256'],'secret_scan':'PASS',
    'independent_clinical_review':False},ensure_ascii=False,indent=2))
