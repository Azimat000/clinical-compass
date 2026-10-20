#!/usr/bin/env python3
"""Verify this planning revision against its recorded baseline; no runtime admission."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'evidence/rag-corpus-expansion'
BASE = json.loads((OUT / 'baseline.json').read_text())
MODIFIED = {
    'START_HERE.md', 'memory/BLOCKERS.md', 'memory/BUDGET.json',
    'memory/DECISIONS.md', 'memory/EXTERNAL.md', 'memory/STATE.json',
    'plan/COVERAGE.md', 'plan/ROADMAP.md', 'plan/S17J-production.md',
    'plan/coverage.json', 'plan/manifest.json', 'plan/s17j-subdivision.json',
    'plan/slices/S17J.md', 'plan/slices/S17J03.md',
}
NEW_IDS = ['S17J02A', 'S17J02B', 'S17J02C']


def load(path):
    return json.loads((ROOT / path).read_text())


def old(path):
    return json.loads(subprocess.check_output(['git', '-C', str(ROOT), 'show', f"{BASE['head']}:{path}"]))


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    assert not BASE['tracked_diff'], 'Pre-existing tracked changes require manual reconciliation'
    changed = [p for p, sha in BASE['tracked_sha256'].items() if not (ROOT / p).is_file() or digest(p) != sha]
    assert set(changed) == MODIFIED, set(changed) ^ MODIFIED
    for p, sha in BASE['pre_existing_untracked_sha256'].items():
        assert digest(p) == sha, p
    previous, coverage = old('plan/coverage.json'), load('plan/coverage.json')
    assert len(coverage['items']) == 83
    assert sum(len(x['subchecks']) for x in coverage['items']) == 160
    for a, b in zip(previous['items'], coverage['items']):
        assert {k: v for k, v in a.items() if k != 'verification_slices'} == {k: v for k, v in b.items() if k != 'verification_slices'}
        assert b['verification_slices'][:len(a['verification_slices'])] == a['verification_slices']
        assert set(b['verification_slices'][len(a['verification_slices']):]) <= set(NEW_IDS)
    state, prior_state = load('memory/STATE.json'), old('memory/STATE.json')
    for sid, entry in prior_state['slices'].items():
        assert state['slices'][sid] == entry, sid
    assert state['current_slice'] is None and state['last_accepted_slice'] == 'S17J02'
    assert state['next_slice'] == 'S17J02A'
    for sid in NEW_IDS:
        assert state['slices'][sid]['status'] == 'planned'
        assert state['slices'][sid]['commit_ref'] is None
    cards = {x['id']: x for x in load('plan/manifest.json')['slices']}
    for a in old('plan/manifest.json')['slices']:
        b = cards[a['id']]
        if a['id'] not in {'S17J', 'S17J03'}:
            assert a == b, a['id']
            continue
        for k, v in a.items():
            if k in {'depends_on', 'tasks', 'acceptance'}:
                assert b[k][:len(v)] == v, (a['id'], k)
            elif k != 'target_date':
                assert b[k] == v, (a['id'], k)
    expected = {'S17J02A': ['S17J02'], 'S17J02B': ['S17J02A'], 'S17J02C': ['S17J02B']}
    for sid, deps in expected.items():
        assert cards[sid]['depends_on'] == deps
        body = (ROOT / f'plan/slices/{sid}.md').read_text()
        assert all(s in body for s in cards[sid]['tasks'] + cards[sid]['acceptance'])
    assert cards['S17J03']['depends_on'] == ['S17J02', 'S17J02C']
    assert set(NEW_IDS) <= set(cards['S17J']['depends_on'])
    sub, prior_sub = load('plan/s17j-subdivision.json'), old('plan/s17j-subdivision.json')
    assert sub['original_parent'] == prior_sub['original_parent']
    assert sub['release_gates'] == prior_sub['release_gates']
    assert sub['supplemental_release_gates'] == ['COVERAGE-1']
    previous_production = subprocess.check_output(['git', '-C', str(ROOT), 'show', f"{BASE['head']}:plan/S17J-production.md"], text=True)
    current_production = (ROOT / 'plan/S17J-production.md').read_text()
    assert [s for s in previous_production.splitlines() if s.startswith('| G0')] == [s for s in current_production.splitlines() if s.startswith('| G0')]
    for child in sub['children']:
        assert child['depends_on'] == cards[child['id']]['depends_on']
        assert child['requirement_ids'] == cards[child['id']]['requirement_ids']
    for mapping in ['original_task_mapping', 'original_acceptance_mapping']:
        for key, entries in prior_sub[mapping].items():
            assert sub[mapping][key][:len(entries)] == entries
    for f in load('evidence/S17J01/dataset-manifest.json')['frozen_files']:
        assert digest(f['path']) == f['sha256'], f['path']
    plan = load('data/retrieval/corpus-coverage-plan.json')
    assert plan['status'] == 'planning_only' and plan['runtime_registry'] is False
    assert plan['current_corpus']['sufficient_for_service'] is False
    assert plan['current_corpus']['authored_fact_cards'] == 15
    assert plan['coverage_gate']['status'] == 'NOT_READY'
    assert plan['coverage_gate']['required_cells'] is None
    assert plan['coverage_gate']['coverage_percent'] is None
    assert len(plan['domains']) == len({d['id'] for d in plan['domains']}) == 12
    card_ids = set()
    for p in (ROOT / 'data/retrieval/reference-cards').glob('*.json'):
        card_ids.update(x['fragment_id'] for x in json.loads(p.read_text())['fragments'])
    assert len(card_ids) == 15
    for d in plan['domains']:
        assert d['readiness'] == 'NOT_READY' and d['required'] is True
        assert set(d['existing_card_ids']) <= card_ids
        assert d['remaining']
    for candidate in plan['source_candidates']:
        assert candidate['url'].startswith('https://') and candidate['verification'] and candidate['rights']
        assert candidate['status'] != 'admitted'
    budget = load('memory/BUDGET.json')
    for k, v in old('memory/BUDGET.json').items():
        if k != 'note':
            assert budget[k] == v
    result = dict(status='PASS', baseline_commit=BASE['head'], requirements=83, subchecks=160,
                  preserved_existing_slice_states=len(prior_state['slices']), new_slices_planned=NEW_IDS,
                  next_slice=state['next_slice'], modified_existing_paths=sorted(changed),
                  unchanged_tracked_files=len(BASE['tracked_sha256'])-len(changed),
                  preserved_pre_existing_untracked=len(BASE['pre_existing_untracked_sha256']),
                  frozen_J01_sha_pass=True, G01_G09_unchanged=True, J02_runtime_and_evidence_unchanged=True,
                  coverage_gate='NOT_READY', clinical_validation=False, imported_new_sources=0,
                  application_code_changed=False, expenses_rub=0)
    (OUT / 'preservation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
