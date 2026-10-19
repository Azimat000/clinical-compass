"""Verify that the blocked S07 review preserved the accepted product and requirements."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
baseline = json.loads((ROOT / 'evidence/S07/baseline.json').read_text())
allowed = {
    'memory/STATE.json', 'memory/DECISIONS.md', 'memory/BLOCKERS.md',
    'memory/EXTERNAL.md', 'memory/BUDGET.json', 'memory/sessions/S07.md',
    'docs/clinical/sources.md', 'docs/clinical/scales-rights.md',
    'plan/coverage.json', 'plan/COVERAGE.md',
}
changed = [name for name, digest in baseline['tracked_sha256'].items()
           if not (ROOT / name).is_file()
           or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
unexpected = sorted(set(changed) - allowed)
before = json.loads(subprocess.check_output(
    ['git', 'show', baseline['base_commit'] + ':plan/coverage.json'], cwd=ROOT))
after = json.loads((ROOT / 'plan/coverage.json').read_text())


def requirements(document):
    return [{k: v for k, v in item.items()
             if k not in ('fulfilment_status', 'actual_evidence')}
            for item in document['items']]


budget = json.loads((ROOT / 'memory/BUDGET.json').read_text())
listed = subprocess.check_output(
    ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
added = set(listed) - set(baseline['tracked_sha256']) - {''}
unexpected_new = sorted(p for p in added if p not in allowed and not p.startswith('evidence/S07/'))
result = {
    'base_commit': baseline['base_commit'],
    'initial_git_clean': not baseline['git_status_short'] and not baseline['diff'],
    'changed_tracked_files': sorted(changed),
    'unexpected_changed_files': unexpected,
    'unexpected_new_files': unexpected_new,
    'accepted_application_datasets_sources_cards_and_tools_unchanged': not unexpected,
    'requirement_definitions_and_subchecks_unchanged': requirements(before) == requirements(after),
    'requirement_groups': len(after['items']),
    'subchecks': sum(len(item['subchecks']) for item in after['items']),
    'fulfilled_statuses_unchanged': [i['id'] for i in before['items'] if i['fulfilment_status'] == 'fulfilled']
        == [i['id'] for i in after['items'] if i['fulfilment_status'] == 'fulfilled'],
    'spent_rub': budget['spent'],
    'commitments_rub': budget['commitments'],
}
passed = (result['initial_git_clean'] and not unexpected and not unexpected_new
          and result['requirement_definitions_and_subchecks_unchanged']
          and result['fulfilled_statuses_unchanged']
          and budget['spent'] == 0 and budget['commitments'] == 0)
result['status'] = 'PASS' if passed else 'FAIL'
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if passed else 1)
