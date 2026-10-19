"""Check S17B scope against its recorded clean baseline and original coverage."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
baseline = json.loads((ROOT / 'evidence/S17B/baseline.json').read_text())
allowed_old = {
    'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md',
    'memory/EXTERNAL.md', 'memory/BUDGET.json', 'plan/coverage.json', 'plan/COVERAGE.md',
    'START_HERE.md',
}
allowed_new = {
    'memory/sessions/S17B.md', 'docs/clinical/first-visit-protocol.md',
    'docs/clinical/first-visit-instrument-decision.md',
    'docs/validation/first-visit-scenarios.md',
}
changed = []
for name, digest in baseline['files'].items():
    p = ROOT / name
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        changed.append(name)
        assert name in allowed_old, f'Unexpected old-file change: {name}'
new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
for name in filter(None, new):
    assert name in allowed_new or name.startswith('evidence/S17B/'), name
for name in ('memory/DECISIONS.md', 'memory/BLOCKERS.md', 'memory/EXTERNAL.md'):
    old_text = subprocess.check_output(['git','show',baseline['base_commit'] + ':' + name], cwd=ROOT).decode()
    assert (ROOT / name).read_text().startswith(old_text), f'History overwritten: {name}'
base_coverage = json.loads(subprocess.check_output(['git', 'show', baseline['base_commit'] + ':plan/coverage.json'], cwd=ROOT))
coverage = json.loads((ROOT / 'plan/coverage.json').read_text())
assert coverage.keys() == base_coverage.keys()
assert len(coverage['items']) == 83
assert sum(len(i['subchecks']) for i in coverage['items']) == 160
for old, current in zip(base_coverage['items'], coverage['items']):
    assert {k:v for k,v in old.items() if k != 'actual_evidence'} == {k:v for k,v in current.items() if k != 'actual_evidence'}, old['id']
    assert set(old['actual_evidence']) <= set(current['actual_evidence']), old['id']
    for name in set(current['actual_evidence']) - set(old['actual_evidence']):
        assert (ROOT / name).is_file(), name
base_state = json.loads(subprocess.check_output(['git','show',baseline['base_commit'] + ':memory/STATE.json'],cwd=ROOT))
state = json.loads((ROOT / 'memory/STATE.json').read_text())
for sid in base_state['slices']:
    if sid != 'S17B':
        assert state['slices'][sid] == base_state['slices'][sid], sid
assert state['slices']['S17']['status'] == 'blocked'
assert not subprocess.run(['git','show-ref','--verify','--quiet','refs/tags/slice/S17'],cwd=ROOT).returncode == 0
cases = json.loads((ROOT / 'data/synthetic/cases.json').read_text())['cases']
assert [c['id'] for c in cases] == ['D01','D02','D03','D04','D05','D06']
scenarios = (ROOT / 'docs/validation/first-visit-scenarios.md').read_text()
for num in range(1,8):
    assert f'| FV{num:02d},' in scenarios
rules=json.loads((ROOT/'apps/compass/resources/clinical-rules-v1.json').read_text())
assert rules['clinical_validation'] is False and rules['active_rules'] == ['A02-v2']
for name in allowed_new - {'memory/sessions/S17B.md'}:
    assert (ROOT/name).is_file(), name
result = {'result':'PASS','baseline_commit':baseline['base_commit'], 'baseline_clean':not baseline['status'], 'changed_existing_paths':changed, 'coverage_requirements':83,'subchecks':160,'coverage_statuses_and_wording_unchanged':True,'all_other_slices_preserved':True,'original_synthetic_cases_unchanged':True,'new_documented_profiles':7,'runtime_sources_dependencies_and_rules_unchanged':True,'S17_remains_blocked_without_tag':True}
(ROOT/'evidence/S17B/verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
