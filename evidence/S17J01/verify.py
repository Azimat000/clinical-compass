"""Independent main-agent acceptance checks, separate from evaluator validator."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def read(name):
    return json.loads((ROOT / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


baseline = read('evidence/S17J01/baseline.json')
allowed_existing = {
    'START_HERE.md', 'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md',
    'memory/EXTERNAL.md', 'memory/BUDGET.json', 'plan/coverage.json', 'plan/COVERAGE.md',
    'plan/ROADMAP.md', 'plan/slices/S17J01.md',
}
allowed_new = {'tools/evaluate_retrieval.py', 'tools/test_retrieval_evaluation.py',
               'docs/architecture/source-retrieval-contract.md',
               'docs/validation/retrieval-protocol.md', 'memory/sessions/S17J01.md'}
allowed_new_dirs = ('data/synthetic/retrieval/', 'evidence/S17J01/')
changed = []
for name, expected in baseline['tracked'].items():
    path = ROOT / name
    assert path.is_file(), 'Deleted baseline path: ' + name
    if sha(path) != expected:
        assert name in allowed_existing, 'Unexpected changed path: ' + name
        changed.append(name)
for name, expected in baseline['pre_existing_untracked'].items():
    assert sha(ROOT / name) == expected, 'Changed pre-existing work: ' + name
all_new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
all_tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
new_paths = (set(all_new) | set(all_tracked)) - set(baseline['tracked']) - set(baseline['pre_existing_untracked']) - {''}
for name in new_paths:
    assert name in allowed_new or name.startswith(allowed_new_dirs), 'Unexpected new path: ' + name
original = json.loads(subprocess.check_output(['git', 'show', baseline['head']+':plan/coverage.json'], cwd=ROOT))
coverage = read('plan/coverage.json')
assert len(coverage['items']) == len(original['items']) == 83
assert sum(len(i['subchecks']) for i in coverage['items']) == 160
for old, new in zip(original['items'], coverage['items']):
    assert old['id'] == new['id']
    assert {k:v for k,v in old.items() if k != 'actual_evidence'} == {k:v for k,v in new.items() if k != 'actual_evidence'}
    assert set(old['actual_evidence']) <= set(new['actual_evidence'])
state_old = json.loads(subprocess.check_output(['git','show',baseline['head']+':memory/STATE.json'], cwd=ROOT))
state = read('memory/STATE.json')
for sid, old in state_old['slices'].items():
    if sid != 'S17J01':
        assert old == state['slices'][sid], 'Changed neighboring slice: ' + sid
assert state['slices']['S17J01']['status'] == 'accepted'
assert state['next_slice'] == 'S17J02' and state['current_slice'] is None
assert state['last_accepted_slice'] == 'S17J01'
manifest = read('evidence/S17J01/dataset-manifest.json')
for entry in manifest['frozen_files']:
    assert sha(ROOT / entry['path']) == entry['sha256'], entry['path']
parts = {s:read('data/synthetic/retrieval/'+s+'.json') for s in ('development','control','safety')}
assert [len(p) for p in parts.values()] == [60,60,24]
ids = [c['id'] for cases in parts.values() for c in cases]
assert len(ids) == len(set(ids)) == 144
for a, b in (('development','control'),('development','safety'),('control','safety')):
    for key in ('family','document_families'):
        def groups(cases):
            return {v for c in cases for v in (c[key] if isinstance(c[key],list) else [c[key]])}
        assert not (groups(parts[a]) & groups(parts[b])), (a,b,key)
control = parts['control']
cats = ('depression','anxiety','adverse_events','adherence_effect','aviandr','context_structure',
        'age','diagnosis_stage','version_rights','missing_evidence','conflict','injection')
category_counts = {cat:sum(cat in c['categories'] for c in control) for cat in cats}
assert min(category_counts.values()) >= 5
for direction in ('depression','anxiety'):
    assert sum(c['direction']==direction and c['expected']['status']=='FOUND' for c in control) >= 10
documents = {d['document_id']:d for d in read('data/synthetic/retrieval/documents.json')}
fragments = {f['fragment_id']:f for f in read('data/synthetic/retrieval/fragments.json')}
for f in fragments.values():
    d = documents[f['document_id']]
    text = d['pages'][f['page']-1]
    assert text[f['start']:f['end']] == f['quote']
    assert all(v in text for v in f['required_context'].values())
    assert sha(ROOT / 'apps/requirements.lock') == baseline['tracked']['apps/requirements.lock']
for cases in parts.values():
    for c in cases:
        assert c['clinical_review'] is None
        if c['expected']['status'] == 'FOUND':
            assert c['mode']=='reference' and c['context'] is None
            assert all(fid in fragments for s in c['expected']['sufficient_sets'] for fid in s)
        else:
            assert c['expected']['reason_code'] and not c['expected']['sufficient_sets']
result = dict(status='PASS', preserved_tracked=len(baseline['tracked']),
              preserved_pre_existing_untracked=len(baseline['pre_existing_untracked']),
              changed_existing=changed, new_paths=sorted(new_paths), groups=83,subchecks=160,
              category_counts=category_counts, fragments=len(fragments), documents=len(documents),
              runtime_unchanged=True, other_slice_states_unchanged=True,
              clinical_validation=False, control_retrieval_runs=0)
(ROOT/'evidence/S17J01/preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
