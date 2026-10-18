"""Compare S04 with the recorded clean baseline, including frozen requirements."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
baseline = json.loads((ROOT / 'evidence/S04/baseline.json').read_text())
changed_existing = []
for path, digest in baseline['tracked_sha256'].items():
    current = ROOT / path
    if not current.exists() or hashlib.sha256(current.read_bytes()).hexdigest() != digest:
        changed_existing.append(path)
allowed_existing = {'.gitignore', 'README.md', 'memory/STATE.json', 'memory/DECISIONS.md',
                    'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
                    'plan/coverage.json', 'plan/COVERAGE.md'}
assert set(changed_existing) <= allowed_existing, changed_existing
base_coverage = json.loads(subprocess.check_output(['git', 'show', baseline['base_commit'] + ':plan/coverage.json'], cwd=ROOT))
coverage = json.loads((ROOT / 'plan/coverage.json').read_text())
before = [{k: v for k, v in item.items() if k not in ('fulfilment_status', 'actual_evidence')} for item in base_coverage['items']]
after = [{k: v for k, v in item.items() if k not in ('fulfilment_status', 'actual_evidence')} for item in coverage['items']]
assert before == after
new_files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
new_files = sorted(set(new_files) - set(baseline['tracked_sha256']))
allowed_prefixes = ('apps/', 'docs/architecture/', 'evidence/S04/')
allowed_new = {'.dockerignore', 'Makefile', 'docker-compose.yml', 'docs/RUNBOOK.md', 'memory/sessions/S04.md'}
assert all(p.startswith(allowed_prefixes) or p in allowed_new for p in new_files), new_files
assert all(i['fulfilment_status'] not in ('fulfilled', 'not_applicable') for i in coverage['items'])
result = {'status': 'PASS', 'base_commit': baseline['base_commit'], 'pre_existing_changes': baseline['status_short'],
          'changed_existing_paths': changed_existing, 'new_paths': new_files, 'requirements_preserved': len(after),
          'subchecks_preserved': sum(len(i['subchecks']) for i in coverage['items']),
          'source_data_cards_and_other_baseline_paths_unchanged': True,
          'scope_note': '.dockerignore added to restrict Docker build context; no adjacent slice work'}
(ROOT / 'evidence/S04/integrity-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
