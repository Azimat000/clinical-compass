"""Verify preservation against the pre-change commit and exercise the new gates."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from validate_plan import ready_id, validate


def read(path):
    return json.loads((ROOT / path).read_text())


baseline = read('evidence/therapist-plan/baseline.json')
base = baseline['base_commit']
assert baseline['git_status_short'] == '', 'Unexpected pre-existing changes'


def old(path):
    return json.loads(subprocess.check_output(['git', 'show', f'{base}:{path}'], cwd=ROOT, text=True))


allowed = {
    'START_HERE.md', 'plan/manifest.json', 'plan/coverage.json', 'plan/COVERAGE.md',
    'plan/ROADMAP.md', 'plan/slices/S18.md',
    'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md',
    'memory/EXTERNAL.md', 'memory/BUDGET.json', 'memory/sessions/therapist-plan.md',
    'docs/design/skills-workflow.md', 'docs/product/contest-strategy.md',
    'docs/product/therapist-first-visit-plan.md', 'docs/release/known-limitations.md',
    'evidence/therapist-plan/baseline.json', 'evidence/therapist-plan/update_plan.py',
    'evidence/therapist-plan/verify.py', 'evidence/therapist-plan/preservation.json',
    'evidence/therapist-plan/checks.log', 'evidence/therapist-plan/acceptance.md',
} | {f'plan/slices/S17{suffix}.md' for suffix in 'BCDEF'}

changed = []
for path, sha in baseline['tracked_sha256'].items():
    p = ROOT / path
    assert p.is_file(), f'Deleted baseline file: {path}'
    if hashlib.sha256(p.read_bytes()).hexdigest() != sha:
        changed.append(path)
        assert path in allowed, f'Unexpected edit: {path}'
untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
new_tracked = subprocess.check_output(['git', 'diff', '--name-only', base, '-z'], cwd=ROOT).decode().split('\0')
assert all(not p or p in allowed for p in untracked + new_tracked), 'Unexpected path outside plan scope'

previous_items = old('plan/coverage.json')['items']
items = read('plan/coverage.json')['items']
new_ids = ['S17B', 'S17C', 'S17D', 'S17E', 'S17F']
assert [r['id'] for r in items] == [r['id'] for r in previous_items]
assert len(items) == 83 and sum(len(r['subchecks']) for r in items) == 160
for before, after in zip(previous_items, items):
    normalized = copy.deepcopy(after)
    normalized['verification_slices'] = [s for s in normalized['verification_slices'] if s not in new_ids]
    assert normalized == before, f'Original requirement/status/evidence changed: {before["id"]}'
assert all('S17F' in r['verification_slices'] for r in items)

cards = read('plan/manifest.json')['slices']
old_cards = old('plan/manifest.json')['slices']
by_id = {c['id']: c for c in cards}
assert [c['id'] for c in cards if c['id'] not in new_ids] == [c['id'] for c in old_cards]
order = [c['id'] for c in cards]
start = order.index('S17')
assert order[start:start+7] == ['S17'] + new_ids + ['S18']
for before in old_cards:
    after = copy.deepcopy(by_id[before['id']])
    if before['id'] == 'S18':
        assert after['depends_on'] == ['S17', 'S17F']
        after['depends_on'].remove('S17F')
    assert after == before, f'Existing slice changed: {before["id"]}'

state = read('memory/STATE.json')
previous_state = old('memory/STATE.json')
assert state['current_slice'] is None and state['next_slice'] == 'S17B'
assert state['last_accepted_slice'] == previous_state['last_accepted_slice'] == 'S15'
assert state['qualification'] == previous_state['qualification'] == 'unknown'
assert state['postcontest_authorized'] is previous_state['postcontest_authorized'] is False
assert 'S16' not in by_id and 'S17A' not in by_id
for sid, entry in previous_state['slices'].items():
    assert state['slices'][sid] == entry, f'Existing acceptance/blocker changed: {sid}'
for sid in new_ids:
    assert state['slices'][sid]['status'] == 'planned'
    assert state['slices'][sid]['commit_ref'] is None
assert ready_id(cards, state) == 'S17B'

probe = copy.deepcopy(state)
probe['slices']['S17B']['status'] = 'accepted'
assert ready_id(cards, probe) == 'S17C'
probe['slices']['S17C']['status'] = 'accepted'
assert ready_id(cards, probe) == 'S17D'
probe['slices']['S17D']['status'] = 'blocked'
assert ready_id(cards, probe) == 'S17E', 'Independent interface blocked by clinical review'
probe['slices']['S17E']['status'] = 'accepted'
assert ready_id(cards, probe) is None, 'Release passed blocked clinical branch'
probe['slices']['S17D']['status'] = 'accepted'
assert ready_id(cards, probe) == 'S17F'
probe['slices']['S17F']['status'] = 'accepted'
assert ready_id(cards, probe) is None, 'S18 bypassed original S17 blocker'
probe['slices']['S17']['status'] = 'accepted'
assert ready_id(cards, probe) == 'S18'
probe['slices']['S17F']['status'] = 'blocked'
assert ready_id(cards, probe) is None, 'S18 bypassed the new gate'

budget = read('memory/BUDGET.json')
before_budget = old('memory/BUDGET.json')
assert {k:v for k,v in budget.items() if k != 'note'} == {k:v for k,v in before_budget.items() if k != 'note'}
errors, summary = validate(ROOT)
assert not errors, errors
result = {
    'status': 'PASS', 'base_commit': base, 'summary': summary,
    'tracked_files_checked': len(baseline['tracked_sha256']),
    'changed_baseline_paths': changed,
    'preserved': ['83 original requirements and 160 subchecks', 'all original statuses and actual evidence',
                  'all old slice tasks/outputs/acceptance/conditions and IDs', 'runtime/SQL/forms/synthetic data/source documents',
                  'S17 blocked and 19 accepted slices', 'qualification and postcontest permissions', 'budget and transaction history'],
    'routing_probes': ['S17B next while S17 blocked', 'B→C→D', 'E independent when D blocked',
                       'F waits for D+E', 'S18 waits for S17+F'],
}
(ROOT / 'evidence/therapist-plan/preservation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
