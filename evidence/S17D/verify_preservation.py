"""Verify S17D documentation scope against the recorded clean baseline."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / 'evidence/S17D/baseline.json').read_text())
ALLOWED = {'START_HERE.md', 'memory/STATE.json', 'memory/DECISIONS.md',
           'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
           'plan/coverage.json', 'plan/COVERAGE.md', 'docs/release/known-limitations.md'}
NEW = {'docs/clinical/first-visit-clinical-review.md', 'memory/sessions/S17D.md'}

def original(path):
    return json.loads(subprocess.check_output(
        ['git', 'show', BASE['head'] + ':' + path], cwd=ROOT, text=True))

changed = []
for name, digest in BASE['tracked_sha256'].items():
    path = ROOT / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        changed.append(name)
assert set(changed) <= ALLOWED, changed
assert BASE['status'] == '' and BASE['diff'] == ''
current = json.loads((ROOT / 'plan/coverage.json').read_text())
previous = original('plan/coverage.json')
assert len(current['items']) == 83
assert sum(len(x['subchecks']) for x in current['items']) == 160
for old, new in zip(previous['items'], current['items']):
    assert {k:v for k,v in old.items() if k != 'actual_evidence'} == {k:v for k,v in new.items() if k != 'actual_evidence'}
    assert all(p in new['actual_evidence'] for p in old['actual_evidence'])
    assert all((ROOT / p).exists() for p in new['actual_evidence'])
state = json.loads((ROOT / 'memory/STATE.json').read_text())
oldstate = original('memory/STATE.json')
assert state['last_accepted_slice'] == oldstate['last_accepted_slice'] == 'S17C'
assert state['current_slice'] is None and state['next_slice'] == 'S17E'
assert state['slices']['S17D']['status'] == 'blocked'
assert state['slices']['S17D']['commit_ref'] is None
for sid, value in oldstate['slices'].items():
    if sid != 'S17D':
        assert value == state['slices'][sid], sid
for entry in json.loads((ROOT / 'evidence/S17D/review-packet.json').read_text())['files']:
    assert hashlib.sha256((ROOT / entry['path']).read_bytes()).hexdigest() == entry['sha256']
newfiles = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
assert all(p in NEW or p.startswith('evidence/S17D/') for p in newfiles), newfiles
assert subprocess.run(['git', 'rev-parse', '--verify', 'refs/tags/slice/S17D'], cwd=ROOT, capture_output=True).returncode != 0
print(json.dumps({'result':'PASS','changed_baseline_paths':changed,'requirements':83,'subchecks':160,'new_clinical_rules':False,'app_sources_data_dependencies_unchanged':True,'S17D':'blocked','next_slice':'S17E'}, ensure_ascii=False, indent=2))
