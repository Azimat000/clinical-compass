"""Read-only comparison with the recorded baseline and original requirement matrix."""
import hashlib
import json
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[2]
def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True)
baseline=json.loads((root/'evidence/S17I01/baseline.json').read_text())
for name,digest in baseline['untracked_sha256'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
old=json.loads(git('show',baseline['base_commit']+':plan/coverage.json'))
new=json.loads((root/'plan/coverage.json').read_text())
assert len(old['items'])==len(new['items'])==83
assert sum(len(x['subchecks']) for x in new['items'])==160
for a,b in zip(old['items'],new['items']):
    assert {k:v for k,v in a.items() if k!='actual_evidence'}=={k:v for k,v in b.items() if k!='actual_evidence'},a['id']
    assert set(a['actual_evidence'])<=set(b['actual_evidence']),a['id']
for name in ['plan/manifest.json','plan/optional-rag.json']:
    assert git('show',baseline['base_commit']+':'+name)==(root/name).read_text(),name
allowed={'apps/compass/follow_up.py','apps/compass/templates/follow_up.html',
         'apps/compass/templates/patient.html','apps/compass/static/app.css','apps/compass/web.py',
         'apps/tests/test_follow_up.py','memory/sessions/S17I01.md','memory/STATE.json',
         'memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json',
         'docs/architecture/service-path.md','START_HERE.md','plan/ROADMAP.md','plan/coverage.json','plan/COVERAGE.md','plan/slices/S17I01.md'}
changed=set(git('diff','--name-only',baseline['base_commit']).splitlines())
created=set(git('ls-files','--others','--exclude-standard').splitlines())-set(baseline['untracked_sha256'])
for name in changed|created:
    assert name in allowed or name.startswith('evidence/S17I01/'),name
state=json.loads((root/'memory/STATE.json').read_text())
for sid in ('S17','S17D','S17I'):assert state['slices'][sid]['status']=='blocked',sid
assert json.loads((root/'evidence/S17I01/browser.json').read_text())['status']=='PASS'
print(json.dumps({'status':'PASS','unchanged_preexisting_files':len(baseline['untracked_sha256']),
    'requirements':83,'subchecks':160,'requirement_texts_statuses_and_previous_evidence_preserved':True,
    'clinical_sources_rules_migrations_dependencies_and_optional_plan_unchanged':True,
    'scope_check':'PASS','clinical_blocks_retained':True,'changed_and_new_files':sorted(changed|created)},ensure_ascii=False,indent=2))
