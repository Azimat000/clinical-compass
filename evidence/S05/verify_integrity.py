"""Compare S05 result with recorded baseline without exposing local credentials."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / 'evidence/S05/baseline.json').read_text())
ALLOWED = {
    'README.md', 'apps/compass/__main__.py', 'apps/compass/repository.py',
    'apps/compass/web.py', 'apps/compass/access.py', 'apps/compass/migrations/002_access.sql',
    'apps/compass/static/app.css', 'apps/compass/templates/base.html',
    'apps/compass/templates/dashboard.html', 'apps/compass/templates/patient.html',
    'apps/compass/templates/login.html', 'apps/compass/templates/invitation.html',
    'apps/compass/templates/result.html', 'apps/tests/test_foundation.py',
    'apps/tests/test_access.py', 'apps/tests/smoke_restart.py',
    'docs/RUNBOOK.md', 'docs/architecture/access.md', 'docs/architecture/data-model.md',
    'docs/architecture/decisions.md', 'docs/architecture/system.md',
    'memory/BUDGET.json', 'memory/BLOCKERS.md', 'memory/DECISIONS.md',
    'memory/EXTERNAL.md', 'memory/STATE.json', 'memory/sessions/S05.md',
    'plan/coverage.json', 'plan/COVERAGE.md'
}
assert BASE['status'] == '' and BASE['diff'] == '', 'Baseline contained existing changes'
files = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0'))
files |= set(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0'))
files.discard('')
changed = set(files) - set(BASE['sha256'])
for path, sha in BASE['sha256'].items():
    p = ROOT / path
    assert p.exists(), f'Deleted baseline file: {path}'
    if hashlib.sha256(p.read_bytes()).hexdigest() != sha:
        changed.add(path)
unexpected = sorted(p for p in changed if p not in ALLOWED and not p.startswith('evidence/S05/'))
assert not unexpected, f'Unexpected paths: {unexpected}'
old = json.loads(subprocess.check_output(['git', 'show', BASE['commit'] + ':plan/coverage.json'], cwd=ROOT))
new = json.loads((ROOT / 'plan/coverage.json').read_text())
immutable = lambda r: {k: v for k, v in r.items() if k not in ('fulfilment_status', 'actual_evidence')}
assert [immutable(r) for r in old['items']] == [immutable(r) for r in new['items']], 'Requirements changed'
assert all(r['fulfilment_status'] not in ('fulfilled', 'not_applicable') for r in new['items']), 'Unsupported fulfilment'
# Scan all files proposed for Git against actual generated local random passwords.
private = ROOT / 'var/s05-credentials.json'
passwords = [r['password'].encode() for r in json.loads(private.read_text())] if private.exists() else []
assert len(passwords) == 8, 'Expected local credentials were not available for leak check'
leaks = [p for p in sorted(files) if any(secret in (ROOT / p).read_bytes() for secret in passwords)]
assert not leaks, f'Credential exposure in proposed Git files: {leaks}'
assert private.stat().st_mode & 0o077 == 0, 'Private credential file permissions too broad'
result = {'status': 'PASS', 'base_commit': BASE['commit'], 'baseline_clean': True,
          'requirements': len(new['items']), 'subchecks': sum(len(r['subchecks']) for r in new['items']),
          'requirement_definitions_unchanged': True, 'untouched_files_preserved': True,
          'new_fulfilled_or_not_applicable': 0, 'local_random_passwords_scanned': len(passwords),
          'password_leaks_in_git_files': [], 'private_credentials_mode': oct(private.stat().st_mode & 0o777),
          'changed_paths': sorted(changed), 'unexpected_paths': unexpected}
(ROOT / 'evidence/S05/integrity-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
