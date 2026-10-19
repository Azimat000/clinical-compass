"""Compare actual files and requirement definitions with the saved clean baseline."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
baseline=json.loads((ROOT/'evidence/S15/baseline.json').read_text())
allowed={'docs/RUNBOOK.md','memory/STATE.json','memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json','plan/coverage.json','plan/COVERAGE.md'}
changed=[]
for name,digest in baseline['sha256'].items():
    path=ROOT/name
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:changed.append(name)
assert set(changed)<=allowed,changed
new=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
assert all(p in {'apps/compass/backup.py','apps/tests/test_backup.py','docs/operations/recovery.md','memory/sessions/S15.md'} or p.startswith('evidence/S15/') for p in new),new
before=json.loads(subprocess.check_output(['git','show',baseline['commit']+':plan/coverage.json'],cwd=ROOT))
after=json.loads((ROOT/'plan/coverage.json').read_text())
def contract(data):return [{k:v for k,v in item.items() if k not in ('actual_evidence','fulfilment_status')} for item in data['items']]
assert contract(before)==contract(after)
assert all(i['fulfilment_status'] not in ('fulfilled','not_applicable') for i in after['items'])
print(json.dumps({'baseline':baseline['commit'],'preexisting_changes':[], 'changed_tracked':changed,'new_files':new,'all_other_tracked_sha_preserved':True,'all_requirements_subchecks_links_preserved':True},ensure_ascii=False,indent=2))
