"""Read-only checks of original requirements, sources, fixtures and migration preservation."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]
baseline=json.loads((ROOT/'evidence/S08A/baseline.json').read_text())
assert baseline['status']=='', 'Initial workspace was not clean'
def old_json(path):
    return json.loads(subprocess.check_output(['git','show',baseline['head']+':'+path],cwd=ROOT,text=True))
old=old_json('plan/coverage.json')['items']
new=json.loads((ROOT/'plan/coverage.json').read_text())['items']
assert len(old)==len(new)==83
assert [(r['id'],r['text'],r['subchecks'],r['primary_slice']) for r in old]==[(r['id'],r['text'],r['subchecks'],r['primary_slice']) for r in new]
original=json.loads((ROOT/'evidence/S08A/original-S08.json').read_text())
manifest=json.loads((ROOT/'plan/manifest.json').read_text())['slices']
current=next(r for r in manifest if r['id']=='S08')
assert current=={**original,'depends_on':original['depends_on']+['S08A']}
protected=[]
for path,sha in baseline['tracked_sha256'].items():
    if path.startswith(('research/','evidence/','data/')) or path in ('apps/requirements.lock','AGENTS.md','START_HERE.md') or path.startswith('apps/compass/migrations/'):
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha, path
        protected.append(path)
adr=subprocess.check_output(['git','show',baseline['head']+':docs/architecture/decisions.md'],cwd=ROOT,text=True)
assert (ROOT/'docs/architecture/decisions.md').read_text().startswith(adr)
report={'requirements':len(new),'subchecks':sum(len(r['subchecks']) for r in new),'original_S08_criteria':'preserved','protected_files_unchanged':len(protected),'old_architecture_preserved':True,'baseline_clean':True,'changes':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).splitlines()}
print(json.dumps(report,ensure_ascii=False,indent=2))
