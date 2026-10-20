"""Verify this planning change against the retained pre-change repository state."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = json.loads((HERE / 'baseline.json').read_text())


def read(name):
    return json.loads((ROOT / name).read_text())


def old(name):
    return json.loads(subprocess.check_output(
        ['git', 'show', f"{BASE['base_commit']}:{name}"], cwd=ROOT))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


allowed_existing = {
    'START_HERE.md', 'docs/architecture/ai-decision.md',
    'memory/BLOCKERS.md', 'memory/BUDGET.json', 'memory/DECISIONS.md',
    'memory/EXTERNAL.md', 'memory/STATE.json', 'plan/COVERAGE.md',
    'plan/ROADMAP.md', 'plan/coverage.json', 'plan/manifest.json',
    'plan/slices/S17I.md', 'plan/slices/S17J.md',
}
children = [f'S17J{i:02}' for i in range(1, 9)]
allowed_new = {
    'plan/S17J-production.md', 'plan/s17j-subdivision.json',
    'plan/archive/S17J-before-split-2026-10-20.md',
    'memory/sessions/plan-S17J-2026-10-20.md',
    *(f'plan/slices/{sid}.md' for sid in children),
}
changed = []
for name, before in BASE['tracked_sha256'].items():
    path = ROOT / name
    assert path.is_file(), f'Pre-existing file lost: {name}'
    if sha(path) != before:
        changed.append(name)
        assert name in allowed_existing, f'Unexpected tracked change: {name}'
for name, before in BASE['untracked_sha256'].items():
    assert sha(ROOT / name) == before, f'Pre-existing untracked file changed: {name}'

paths = subprocess.check_output(
    ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
    cwd=ROOT).decode().split('\0')
new = set(paths) - set(BASE['tracked_sha256']) - set(BASE['untracked_sha256']) - {''}
for name in new:
    assert name in allowed_new or name.startswith('evidence/planning/S17J-2026-10-20/'), name

manifest, previous_manifest = read('plan/manifest.json'), old('plan/manifest.json')
cards = {c['id']: c for c in manifest['slices']}
original_cards = {c['id']: c for c in previous_manifest['slices']}
assert set(cards) - set(original_cards) == set(children)
for sid, original in original_cards.items():
    if sid != 'S17J':
        assert cards[sid] == original, f'Unrelated manifest card changed: {sid}'
parent, original_parent = cards['S17J'], original_cards['S17J']
for key in ['tasks', 'acceptance', 'outputs']:
    assert parent[key][:len(original_parent[key])] == original_parent[key], key
assert parent['requirement_ids'] == original_parent['requirement_ids']
assert parent['depends_on'] == ['S17H'] + children
for index, sid in enumerate(children):
    c = cards[sid]
    assert c['depends_on'] == (['S17H'] if index == 0 else [children[index - 1]])
    text = (ROOT / f'plan/slices/{sid}.md').read_text()
    assert 'STATUS: PLANNED' in text
    assert all(task in text for task in c['tasks'])
    assert all(criterion in text for criterion in c['acceptance'])
    assert c['acceptance_tag'] == f'slice/{sid}'

state, previous_state = read('memory/STATE.json'), old('memory/STATE.json')
assert state['current_slice'] is None
assert state['last_accepted_slice'] == previous_state['last_accepted_slice'] == 'S17H'
assert state['next_slice'] == 'S17J01'
for sid, original in previous_state['slices'].items():
    assert state['slices'][sid] == original, f'Existing slice state changed: {sid}'
for sid in children:
    assert state['slices'][sid]['status'] == 'planned'
    assert state['slices'][sid]['commit_ref'] is None
assert state['latest_followup_spec']['clinical_validation'] is False
assert state['latest_followup_spec']['all_cards_active'] is False
assert cards['S17I']['depends_on'] == original_cards['S17I']['depends_on']

coverage, previous_coverage = read('plan/coverage.json'), old('plan/coverage.json')
assert len(coverage['items']) == len(previous_coverage['items']) == 83
assert sum(len(r['subchecks']) for r in coverage['items']) == 160
for now, before in zip(coverage['items'], previous_coverage['items']):
    for key in before:
        if key != 'verification_slices':
            assert now[key] == before[key], f"Changed requirement {before['id']}.{key}"
    assert now['verification_slices'][:len(before['verification_slices'])] == before['verification_slices']
    added = now['verification_slices'][len(before['verification_slices']):]
    assert all(sid in children for sid in added)

register = read('plan/s17j-subdivision.json')
assert register['original_parent'] == original_parent
assert set(register['original_task_mapping']) == {str(n) for n in range(1, 7)}
assert set(register['original_acceptance_mapping']) == {str(n) for n in range(1, 5)}
assert set(register['release_gates']) == {f'G{i:02}' for i in range(1, 10)}
for mapping in ['original_task_mapping', 'original_acceptance_mapping']:
    assert all(value and set(value) <= set(children + ['S17J']) for value in register[mapping].values())
archive = ROOT / register['original_card_archive']
assert archive.read_bytes() == subprocess.check_output(
    ['git', 'show', f"{BASE['base_commit']}:plan/slices/S17J.md"], cwd=ROOT)
budget, previous_budget = read('memory/BUDGET.json'), old('memory/BUDGET.json')
for key in ['limit', 'spent', 'commitments', 'transactions', 'allocation_caps']:
    assert budget[key] == previous_budget[key]
assert budget['spent'] == budget['commitments'] == 0

print(json.dumps({
    'status': 'PASS', 'baseline_commit': BASE['base_commit'],
    'original_tracked_files': len(BASE['tracked_sha256']),
    'original_untracked_files_preserved': len(BASE['untracked_sha256']),
    'changed_existing_paths': sorted(changed), 'new_children': children,
    'requirements_preserved': 83, 'subchecks_preserved': 160,
    'existing_slice_states_preserved': True,
    'original_parent_tasks_and_criteria_preserved': True,
    'runtime_sources_dependencies_and_preexisting_evidence_preserved': True,
    'next_slice': state['next_slice'], 'implementation_started': False,
}, ensure_ascii=False, indent=2))
