"""Independent main-agent acceptance checks against the recorded Git baseline."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
baseline = json.loads((HERE / 'baseline.json').read_text())


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True)


def load(path):
    return json.loads((ROOT / path).read_text())


for path, sha in baseline['preserved_files'].items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha, path
coverage = load('plan/coverage.json')['items']
previous = json.loads(git('show', baseline['head'] + ':plan/coverage.json'))['items']
assert len(coverage) == len(previous) == 83
for current, old in zip(coverage, previous):
    for key in ('id', 'text', 'subchecks', 'primary_slice', 'fulfilment_status'):
        assert current[key] == old[key], (current['id'], key)
requirements = load('plan/backend/requirements.json')['items']
old_requirements = json.loads(git('show', baseline['head'] + ':plan/backend/requirements.json'))['items']
assert [(r['id'], r['text'], r['status']) for r in requirements] == [(r['id'], r['text'], r['status']) for r in old_requirements]
cards = {c['id']: c for c in load('plan/manifest.json')['slices']}
old_cards = {c['id']: c for c in json.loads(git('show', baseline['head'] + ':plan/manifest.json'))['slices']}
for sid in ('BE08', 'BE08B'):
    for key in ('tasks', 'acceptance', 'requirement_ids'):
        assert cards[sid][key] == old_cards[sid][key], (sid, key)
assert cards['BE08B02']['acceptance'] == old_cards['BE08B']['acceptance']
assert cards['BE08B']['depends_on'] == ['BE08B01', 'BE08B02']
for sid in ('BE08B01', 'BE08B02'):
    assert set(cards[sid]['requirement_ids']) == set(cards['BE08B']['requirement_ids'])
copy = load('evidence/BE08B01/copy-check.json')
assert copy['pass'] and copy['live_unchanged'] and copy['copy_mode'] == '0o600'
assert copy['existing_triggers_retained'] == 74 and copy['jobs_enabled'] == 0
targeted = (HERE / 'targeted.log').read_text()
regression = (HERE / 'check.log').read_text()
assert re.search(r'Ran 16 tests in .+\n\nOK', targeted)
assert re.search(r'Ran 752 tests in .+\n\nOK', regression)
assert re.search(r'Ran 70 tests in .+\n\nOK', regression)
assert 'FAILED' not in regression and 'Traceback' not in regression
allowed = {
    'apps/compass/backend_risk_episodes.py', 'apps/compass/migrations/018_backend_risk_episodes.sql',
    'apps/tests/test_backend_risk_episodes.py', 'docs/architecture/backend-risk-episodes.md',
    'apps/tests/test_backend_contracts.py', 'apps/tests/test_extraction.py',
    'START_HERE.md', 'plan/manifest.json', 'plan/slices/BE08B.md', 'plan/slices/BE08B01.md',
    'plan/slices/BE08B02.md', 'plan/backend/README.md', 'plan/backend/requirements.json',
    'plan/coverage.json', 'plan/COVERAGE.md', 'memory/STATE.json', 'memory/DECISIONS.md',
    'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json', 'memory/sessions/BE08B01.md'}
changed = set(git('diff', '--name-only', baseline['head']).splitlines())
untracked = set(git('ls-files', '--others', '--exclude-standard').splitlines())
for path in changed | untracked:
    assert path in allowed or path in baseline['preserved_files'] or path.startswith('evidence/BE08B01/'), path
report = {'pass': True, 'baseline': baseline['head'], 'original_requirements': len(coverage),
          'original_subchecks': sum(len(i['subchecks']) for i in coverage),
          'requirement_statuses_preserved': True, 'parent_tasks_and_criteria_preserved': True,
          'BE08B02_inherits_all_original_criteria': True, 'preserved_files': len(baseline['preserved_files']),
          'targeted_tests': 16, 'regression_application_tests': 752, 'regression_tools_tests': 70,
          'copy_check': True, 'scope_check': True, 'clinical_validation': False,
          'model_quality_evaluated_this_slice': False, 'open_false_discrepancy_unchanged': True}
(HERE / 'independent-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
