"""Read-only acceptance audit: scope, preservation, requirements and review hashes."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
def read(name):
    return json.loads((ROOT / name).read_text())
def old(name):
    return json.loads(subprocess.check_output(['git', 'show', baseline['base_commit'] + ':' + name], cwd=ROOT))
def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()

baseline = read('evidence/S17H/baseline.json')
allowed = {
    'START_HERE.md', 'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md',
    'memory/EXTERNAL.md', 'memory/BUDGET.json', 'plan/manifest.json', 'plan/coverage.json',
    'plan/COVERAGE.md', 'plan/ROADMAP.md', 'plan/slices/S17I.md',
    'docs/product/psychiatrist-followup-plan.md',
}
new = {
    'plan/slices/S17J.md', 'docs/clinical/followup-recommendation-spec.md',
    'docs/clinical/followup-review-packet.md', 'docs/architecture/ai-decision.md',
    'memory/sessions/S17H.md',
}
changed = []
for name, sha in baseline['tracked'].items():
    assert (ROOT / name).is_file(), name
    if digest(name) != sha:
        assert name in allowed, name
        changed.append(name)
for name, sha in baseline['pre_existing_untracked'].items():
    assert digest(name) == sha, name
untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
for name in filter(None, untracked):
    assert name in baseline['pre_existing_untracked'] or name in new or name.startswith('evidence/S17H/'), name
before = old('plan/coverage.json')['items']
after = read('plan/coverage.json')['items']
assert len(before) == len(after) == 83
rows = []
relevant = next(c for c in read('plan/manifest.json')['slices'] if c['id'] == 'S17H')['requirement_ids']
for a, b in zip(before, after):
    assert a['id'] == b['id']
    for key in a.keys() - {'verification_slices', 'actual_evidence'}:
        assert a[key] == b[key], (a['id'], key)
    assert b['verification_slices'][:len(a['verification_slices'])] == a['verification_slices']
    assert set(b['verification_slices']) - set(a['verification_slices']) <= {'S17J'}
    assert b['actual_evidence'][:len(a['actual_evidence'])] == a['actual_evidence']
    assert set(b['actual_evidence']) - set(a['actual_evidence']) <= {'evidence/S17H/acceptance.md', 'evidence/S17H/requirements-review.json'}
    rows.append({'id': a['id'], 'subchecks': [x['id'] for x in a['subchecks']],
                 'status_preserved': b['fulfilment_status'],
                 's17h_disposition': 'Подготовительная спецификация/источники/пакет; клинического выполнения не заявлено.' if a['id'] in relevant else 'Без нового выполнения; прежние доказательства/статус сохранены.'})
assert sum(len(x['subchecks']) for x in after) == 160
before_state = old('memory/STATE.json')
state = read('memory/STATE.json')
for sid, value in before_state['slices'].items():
    if sid != 'S17H': assert state['slices'][sid] == value, sid
for key in before_state.keys() - {'updated_on', 'current_slice', 'last_accepted_slice', 'next_slice', 'slices'}:
    assert state[key] == before_state[key], key
before_manifest = old('plan/manifest.json')['slices']
cards = read('plan/manifest.json')['slices']
assert {x['id'] for x in cards} - {x['id'] for x in before_manifest} == {'S17J'}
for c in before_manifest:
    now = next(x for x in cards if x['id'] == c['id'])
    if c['id'] == 'S17I':
        assert now['depends_on'] == c['depends_on'] + ['S17J']
        for key in c.keys() - {'depends_on'}: assert c[key] == now[key], key
    else: assert now == c, c['id']
packet = read('evidence/S17H/review-packet.json')
assert packet['status'] == 'not_reviewed' and packet['independent_clinical_validation'] is False
assert packet['reviewer'] is None
assert len(packet['cards']) == 8 and all(not c['active'] and not c['clinical_validation'] for c in packet['cards'])
for f in packet['files']: assert digest(f['path']) == f['sha256'], f['path']
for f in new | {'evidence/S17H/source-map.md', 'evidence/S17H/research.md'}:
    if not f.endswith('.md'): continue
    text = (ROOT / f).read_text()
    for link in re.findall(r'\]\(([^)]+)\)', text):
        if '://' in link or link.startswith('#'): continue
        assert (ROOT / f).parent.joinpath(link.split('#')[0]).is_file(), (f, link)
assert read('memory/BUDGET.json')['spent'] == read('memory/BUDGET.json')['commitments'] == 0
assert read('memory/BUDGET.json')['limit'] == 5000
report = {'status':'PASS', 'base_commit':baseline['base_commit'],
          'tracked_preserved_or_allowed':len(baseline['tracked']),
          'pre_existing_untracked_preserved':list(baseline['pre_existing_untracked']),
          'changed_tracked':changed, 'requirements':83, 'subchecks':160,
          'all_requirement_statuses_preserved':True,
          'runtime_sources_forms_dependencies_preserved':True,
          'sibling_states_preserved':True, 'new_slice_planned_only':'S17J',
          's17i_change':'Additional S17J dependency only; original tasks and acceptance retained',
          'review_packet_hashes_match':True, 'clinical_validation':False,
          'local_document_links_valid':True, 'budget_spent_and_commitments':0}
print(json.dumps({'preservation':report, 'requirements':rows}, ensure_ascii=False, indent=2))
