"""Main-agent acceptance: preserve sources/requirements/user data and constrain the diff."""
import collections
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
baseline = json.loads((ROOT/'evidence/S07/review/baseline.json').read_text())
allowed_existing = {
    'README.md', 'apps/compass/records.py', 'apps/compass/web.py', 'apps/compass/static/app.css',
    'apps/compass/templates/patient.html', 'apps/compass/templates/dashboard.html', 'apps/tests/smoke_restart.py',
    'docs/RUNBOOK.md', 'docs/architecture/data-model.md', 'docs/clinical/scales-rights.md',
    'docs/clinical/sources.md', 'docs/clinical/rule-catalog.md', 'memory/STATE.json',
    'memory/DECISIONS.md', 'memory/BLOCKERS.md', 'memory/EXTERNAL.md', 'memory/BUDGET.json',
    'memory/sessions/S07.md', 'plan/manifest.json', 'plan/ROADMAP.md', 'plan/coverage.json',
    'plan/COVERAGE.md', 'plan/slices/S07.md', 'evidence/S07/acceptance.md',
}
allowed_new = {
    'apps/compass/assessments.py', 'apps/compass/migrations/004_assessments.sql',
    'apps/compass/resources/dass42-ru-v1.json', 'apps/compass/templates/assessment_form.html',
    'apps/compass/templates/assessment_receipt.html', 'apps/compass/templates/assessments_panel.html',
    'apps/tests/test_assessments.py', 'docs/architecture/assessments.md',
    'docs/compliance/third-party.md', 'docs/product/contest-strategy.md',
}


def previous(path):
    return json.loads(subprocess.check_output(['git','show',baseline['base_commit']+':'+path],cwd=ROOT))


def requirements(document):
    return [{k:v for k,v in item.items() if k not in ('fulfilment_status','actual_evidence')}
            for item in document['items']]


changed = [p for p,h in baseline['tracked_sha256'].items()
           if not (ROOT/p).is_file() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
listed = set(subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0'))-{''}
added = listed-set(baseline['tracked_sha256'])
unexpected = sorted(set(changed)-allowed_existing)
unexpected_new = sorted(p for p in added if p not in allowed_new and not p.startswith('evidence/S07/review/'))
before = previous('plan/coverage.json')
after = json.loads((ROOT/'plan/coverage.json').read_text())
old_plan, new_plan = previous('plan/manifest.json'), json.loads((ROOT/'plan/manifest.json').read_text())
old_s07 = next(s for s in old_plan['slices'] if s['id']=='S07')
new_s07 = next(s for s in new_plan['slices'] if s['id']=='S07')
old_s07['tasks'][1] = new_s07['tasks'][1]

db_before = json.loads((ROOT/'evidence/S07/review/docker-before.json').read_text())
db_after = json.loads((ROOT/'evidence/S07/review/docker-after.json').read_text())
lost = {t:sum((collections.Counter(rows)-collections.Counter(db_after['row_digests'].get(t,[]))).values())
        for t,rows in db_before['row_digests'].items()}
lost = {t:n for t,n in lost.items() if n}
budget = json.loads((ROOT/'memory/BUDGET.json').read_text())

def passwords(value):
    if isinstance(value,dict):
        for key,child in value.items():
            if key=='password' and isinstance(child,str) and child: yield child
            else: yield from passwords(child)
    elif isinstance(value,list):
        for child in value: yield from passwords(child)

secrets = set()
for name in ('var/s05-credentials.json','var/demo-credentials.json','var/docker-demo-credentials.json'):
    path=ROOT/name
    if path.is_file(): secrets.update(passwords(json.loads(path.read_text())))
leaks = sorted(p for p in set(changed)|added if (ROOT/p).is_file()
               and any(secret.encode() in (ROOT/p).read_bytes() for secret in secrets))
result = {
    'base_commit':baseline['base_commit'], 'initial_git_clean':not baseline['git_status_short'] and not baseline['diff'],
    'changed_existing_files':sorted(changed), 'new_files':sorted(added),
    'unexpected_changed_files':unexpected, 'unexpected_new_files':unexpected_new,
    'requirement_definitions_and_all_subchecks_preserved':requirements(before)==requirements(after),
    'groups':len(after['items']), 'subchecks':sum(len(i['subchecks']) for i in after['items']),
    'only_documented_s07_task_clarification_in_manifest':old_plan==new_plan,
    'original_acceptance_criteria_preserved':old_s07['acceptance']==new_s07['acceptance'],
    'original_sources_datasets_old_migrations_and_other_cards_preserved':not unexpected,
    'new_fulfilled_requirements':sorted({i['id'] for i in after['items'] if i['fulfilment_status']=='fulfilled'}
        -{i['id'] for i in before['items'] if i['fulfilment_status']=='fulfilled'}),
    'preserved_prior_table_snapshots':len(db_before['row_digests']), 'lost_or_changed_prior_rows':lost,
    'database_integrity':db_after['integrity_check'], 'foreign_key_check':db_after['foreign_key_check'],
    'random_local_passwords_checked':len(secrets), 'password_leak_files':leaks,
    'spent_rub':budget['spent'], 'commitments_rub':budget['commitments'],
}
passed = (result['initial_git_clean'] and not unexpected and not unexpected_new
          and result['requirement_definitions_and_all_subchecks_preserved']
          and result['only_documented_s07_task_clarification_in_manifest']
          and result['original_acceptance_criteria_preserved']
          and not lost and db_after['integrity_check']=='ok' and not db_after['foreign_key_check']
          and not leaks and budget['spent']==0 and budget['commitments']==0)
result['status']='PASS' if passed else 'FAIL'
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if passed else 1)
