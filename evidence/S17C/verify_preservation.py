"""Baseline comparison: immutable requirements, sources and unrelated work."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
baseline = json.loads((ROOT/'evidence/S17C/baseline.json').read_text())
allowed = {
    'START_HERE.md', 'apps/compass/ages.py', 'apps/compass/decisions.py',
    'apps/compass/web.py', 'apps/compass/templates/patient.html', 'apps/compass/static/app.css',
    'apps/tests/test_clinical_rules.py', 'apps/tests/test_decisions.py',
    'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md', 'memory/EXTERNAL.md',
    'memory/BUDGET.json', 'plan/coverage.json', 'plan/COVERAGE.md', 'docs/release/known-limitations.md',
}
changed = []
for name, digest in baseline['files'].items():
    path = ROOT/name
    assert path.is_file(), name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        assert name in allowed, 'Unexpected change: '+name
        changed.append(name)

old = json.loads(subprocess.check_output(['git','show',baseline['commit']+':plan/coverage.json'],cwd=ROOT))
new = json.loads((ROOT/'plan/coverage.json').read_text())
assert len(new['items']) == 83
assert sum(len(i['subchecks']) for i in new['items']) == 160
for before, after in zip(old['items'],new['items']):
    assert {k:v for k,v in before.items() if k!='actual_evidence'} == {k:v for k,v in after.items() if k!='actual_evidence'}, before['id']
    assert all(item in after['actual_evidence'] for item in before['actual_evidence'])

oldstate = json.loads(subprocess.check_output(['git','show',baseline['commit']+':memory/STATE.json'],cwd=ROOT))
state = json.loads((ROOT/'memory/STATE.json').read_text())
for sid, data in oldstate['slices'].items():
    if sid != 'S17C':
        assert state['slices'][sid] == data, sid
assert state['slices']['S17']['status'] == 'blocked'
assert not state['postcontest_authorized']
new_files = set(subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0'))-{''}
new_files |= set(subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=A','-z'],cwd=ROOT).decode().split('\0'))-{''}
permitted_new = {'apps/compass/first_visits.py','apps/compass/migrations/013_first_visits.sql',
                 'apps/compass/templates/first_visit.html','apps/tests/test_first_visits.py',
                 'docs/architecture/first-visit.md','memory/sessions/S17C.md'}
assert all(name in permitted_new or name.startswith('evidence/S17C/') for name in new_files),new_files-permitted_new
result = {'status':'PASS','baseline_commit':baseline['commit'], 'requirements':83,'subchecks':160,
          'statuses_unchanged':True,'other_slices_unchanged':True,'changed_original_files':changed,
          'unchanged_original_files':len(baseline['files'])-len(changed),
          'source_forms_runtime_old_migrations_and_synthetic_data':'exact baseline SHA retained'}
(ROOT/'evidence/S17C/preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
