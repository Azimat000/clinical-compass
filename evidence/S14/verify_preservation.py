"""Compare final workspace to the retained baseline; never reset unexpected edits."""
from pathlib import Path
import hashlib
import json
import subprocess
ROOT=Path(__file__).resolve().parents[2]
base=json.loads((ROOT/'evidence/S14/baseline.json').read_text())
owned={'.gitignore','apps/compass/access.py','apps/compass/db.py','apps/compass/web.py',
       'apps/compass/templates/error.html','apps/tests/test_security.py','docs/RUNBOOK.md',
       'docs/compliance/data-map.md','docs/compliance/third-party.md','memory/STATE.json',
       'memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md','memory/BUDGET.json',
       'memory/sessions/S14.md','plan/coverage.json','plan/COVERAGE.md'}
changed=subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).splitlines()
new=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
unexpected=[p for p in changed+new if p not in owned and not p.startswith('evidence/S14/')]
unchanged=[]; altered=[]
for name,digest in base['sha256'].items():
    if name in owned:continue
    p=ROOT/name
    (unchanged if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==digest else altered).append(name)
original=json.loads(subprocess.check_output(['git','show',base['base_commit']+':plan/coverage.json'],cwd=ROOT,text=True))
current=json.loads((ROOT/'plan/coverage.json').read_text())
def structure(x):
    if isinstance(x,dict):return {k:structure(v) for k,v in x.items() if k not in ('fulfilment_status','actual_evidence','updated_on')}
    if isinstance(x,list):return [structure(v) for v in x]
    return x
assert structure(original)==structure(current),'Requirement text, IDs, subchecks or slice bindings changed'
result={'base_commit':base['base_commit'],'baseline_clean':not base['status'],
        'changed_paths':changed,'new_paths':new,'unexpected_paths':unexpected,
        'unchanged_preexisting_files':len(unchanged),'unexpected_alterations':altered,
        'all_requirements_and_subchecks_preserved':True,
        'limits':'Allowed files reviewed separately in actual git diff; no reset/revert performed.'}
(ROOT/'evidence/S14/preservation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
assert not unexpected and not altered
print('PASS: baseline and requirement structure preserved; modified paths within S14 ownership')
