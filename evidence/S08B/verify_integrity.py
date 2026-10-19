"""Check immutable inputs and preserved requirements against the recorded baseline."""
from pathlib import Path
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[2]
baseline=json.loads((ROOT/'evidence/S08B/baseline.json').read_text());base=baseline['head']
protected=[p for p in baseline['sha256'] if p.startswith(('data/','research/','apps/compass/resources/')) or p.startswith('apps/compass/migrations/') or p in ('AGENTS.md','START_HERE.md','apps/requirements.lock','Dockerfile','compose.yaml')]
for path in protected:assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==baseline['sha256'][path],path
old=json.loads(subprocess.check_output(['git','show',base+':plan/coverage.json'],cwd=ROOT));new=json.loads((ROOT/'plan/coverage.json').read_text())
assert [i['id'] for i in old['items']]==[i['id'] for i in new['items']]
for a,b in zip(old['items'],new['items']):
    for key in ('id','text','source','kind','subchecks','primary_slice','fulfilment_status'):assert a[key]==b[key],(a['id'],key)
    assert set(a['verification_slices'])<=set(b['verification_slices'])
s08=json.loads((ROOT/'evidence/S08B/original-S08.json').read_text());manifest=json.loads((ROOT/'plan/manifest.json').read_text());actual=next(c for c in manifest['slices'] if c['id']=='S08')
for key in s08:
    if key=='depends_on':assert actual[key]==s08[key]+['S08B']
    else:assert actual[key]==s08[key],key
print(json.dumps({'protected_files_unchanged':len(protected),'requirement_groups':len(old['items']),'subchecks':sum(len(i['subchecks']) for i in old['items']),'S08_original_preserved':True,'fulfilment_statuses_unchanged':True},indent=2))
