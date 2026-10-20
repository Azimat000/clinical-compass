"""Main-agent preservation and exact-corpus audit; run from repository root."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass.retrieval_corpus import build_manifest, load_snapshot


def load(path):
    return json.loads((ROOT / path).read_text())


def checksum(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


baseline = load('evidence/S17J02/baseline.json')
allowed = {'START_HERE.md', 'memory/STATE.json', 'memory/DECISIONS.md',
           'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
           'plan/coverage.json', 'plan/COVERAGE.md'}
changed = [p for p, value in baseline['tracked'].items()
           if not (ROOT/p).is_file() or checksum(p) != value]
assert set(changed) <= allowed, changed
for path, value in baseline['pre_existing_untracked'].items():
    assert checksum(path) == value, path


def original(path):
    return json.loads(subprocess.check_output(['git', '-C', str(ROOT), 'show',
                     baseline['head'] + ':' + path]))


old, new = original('plan/coverage.json')['items'], load('plan/coverage.json')['items']
assert len(old) == len(new) == 83
assert sum(len(i['subchecks']) for i in new) == 160
for before, after in zip(old, new):
    for key in before:
        if key != 'actual_evidence':
            assert before[key] == after[key], (before['id'], key)
    assert set(before['actual_evidence']) <= set(after['actual_evidence'])
before, after = original('memory/STATE.json'), load('memory/STATE.json')
for sid, entry in before['slices'].items():
    if sid != 'S17J02':
        assert after['slices'][sid] == entry, sid
assert after['last_accepted_slice'] == before['last_accepted_slice'] == 'S17J01'
assert load('memory/BUDGET.json')['spent'] == load('memory/BUDGET.json')['commitments'] == 0
registry = load('data/retrieval/source-registry.json')
manifest, blobs = build_manifest(ROOT, registry, load('evidence/S17J02/import-results.json')['evaluated_at'])
assert manifest == load('evidence/S17J02/corpus-manifest.json')
assert load_snapshot(ROOT/'evidence/S17J02/corpus'/manifest['corpus_version']) == manifest
assert not blobs
assert len(manifest['sources']) == 3
assert all(x['disposition'] == 'quarantined' for x in manifest['sources'])
result = {'status': 'PASS', 'tracked_baseline_count': len(baseline['tracked']),
          'changed_original_paths': changed,
          'pre_existing_untracked_preserved': list(baseline['pre_existing_untracked']),
          'requirements_preserved': 83, 'subchecks_preserved': 160,
          'other_slice_states_preserved': True, 'original_sources_and_dependencies_preserved': True,
          'corpus_version': manifest['corpus_version'], 'quarantined': 3,
          'admitted': 0, 'new_pdf_copies': 0, 'spent_and_commitments': 0}
print(json.dumps(result, ensure_ascii=False, indent=2))
