"""Independent local acceptance checks; never invokes an external model."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
ROOT=Path(__file__).resolve().parents[2]
os_paths=ROOT/'evidence/BE10A'
def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def load(p):return json.loads((ROOT/p).read_text())
b=load('evidence/BE10/baseline.json');live=load('evidence/BE10A/live-candidate.json')
s=live['input_snapshot'];report=live['report'];assert live['test_double'] is False
assert report['status']=='unreviewed' and report['clinical_ready'] is False
assert report['established_diagnosis'] is None and report['plan'] is None
assert report['model_metadata']['test_double'] is False
assert report['model_metadata']['returned_model']=='deepseek-flash'
assert report['catalog']['engine_sha256']==sha((ROOT/'apps/compass/backend_diagnoses.py').read_bytes())
cat=load('data/backend/diagnosis-domains-v1.json')
assert report['catalog']['catalog_sha256']==sha(canonical(cat).encode())
assert report['catalog']['evidence_sha256']==sha((ROOT/cat['evidence']).read_bytes())
assert report['snapshot_sha256']==sha(canonical(s).encode())
checked=0
c=report['candidates'];hypotheses=([c['leading']] if c['leading'] else [])+c['alternatives']
for h in hypotheses:
 assert h['diagnosis_code'] is None and h['interpretation']=='hypothesis_unreviewed'
 assert {i['id'] for i in h['criteria']}==set(cat['kinds'][h['kind']])
 for criterion in h['criteria']:
  for e in criterion['evidence']:
   meta=s['patient_history']['sources'][e['source_ref']]
   row=next(r for r in s[meta['table']] if r[meta['key']]==meta['id'])
   assert sha(canonical(row).encode())==meta['sha256']==e['source_sha256']
   value=row
   for token in e['path'].lstrip('/').split('/'):
    if isinstance(value,str):value=json.loads(value)
    key=token.replace('~1','/').replace('~0','~')
    value=value[int(key)] if isinstance(value,list) else value[key]
   if e['path'].endswith('_json') and isinstance(value,str):value=json.loads(value)
   text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True)
   assert text==e['text'] and text[e['start']:e['end']]==e['quote'];checked+=1
assert checked==live['citations_independently_verified']
assert all(sha((ROOT/p).read_bytes())==h for p,h in b['preserved_files'].items())
assert sha((ROOT/'var/clinic-20261026-access.md').read_bytes())==b['access_sha256']
with closing(sqlite3.connect('file:'+str(ROOT/'var/compass.sqlite3')+'?mode=ro',uri=True)) as db:
 def rows(t):return sorted(json.dumps(r,ensure_ascii=False,default=str) for r in db.execute('SELECT * FROM "'+t+'"'))
 after={r[0]:sha(json.dumps(rows(r[0]),ensure_ascii=False).encode()) for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 assert after==b['active_db_tables']
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
 patients=db.execute('SELECT count(*) FROM patients').fetchone()[0]
 schema=db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
with closing(sqlite3.connect(ROOT/'var/deepseek-budget.sqlite3')) as db:
 calls,amount=db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone()
assert (calls,amount)==tuple(live['ledger_after'][k] for k in ('calls','micro_usd'))
assert calls-live['ledger_before']['calls']==1 and amount<=100000
assert amount-live['ledger_before']['micro_usd']==report['model_metadata']['cost_ceiling_micro_usd']
old=json.loads(subprocess.check_output(['git','show',b['head']+':plan/coverage.json'],cwd=ROOT,text=True))
coverage=load('plan/coverage.json')
assert [(i['id'],i['subchecks'],i['fulfilment_status']) for i in old['items']]==[(i['id'],i['subchecks'],i['fulfilment_status']) for i in coverage['items']]
oldm=json.loads(subprocess.check_output(['git','show',b['head']+':plan/manifest.json'],cwd=ROOT,text=True))
m=load('plan/manifest.json')
assert next(i for i in m['slices'] if i['id']=='BE10')['acceptance']==next(i for i in oldm['slices'] if i['id']=='BE10')['acceptance']
assert next(i for i in m['slices'] if i['id']=='BE10B')['acceptance']==next(i for i in oldm['slices'] if i['id']=='BE10')['acceptance']
key=(ROOT/'var/deepseek-api-key').read_bytes().strip()
files=[ROOT/'apps/compass/backend_diagnoses.py',ROOT/'apps/tests/test_backend_diagnoses.py']+[p for p in (ROOT/'evidence/BE10A').rglob('*') if p.is_file()]
assert all(key not in p.read_bytes() for p in files)
result={'status':'PASS','verified_citations':checked,'active_tables_unchanged':len(after),'patients':patients,'schema':schema,
        'foreign_keys':'PASS','integrity':'ok','preserved_files':len(b['preserved_files']),'access_unchanged':True,
        'ledger_calls':calls,'ledger_micro_usd':amount,'cap_micro_usd':100000,'original_requirements':len(coverage['items']),
        'original_subchecks':sum(len(i['subchecks']) for i in coverage['items']),'fulfilment_unchanged':True,
        'parent_acceptance_unchanged':True,'secret_scan':'PASS','clinical_quality_verified':False}
print(json.dumps(result,ensure_ascii=False,indent=2))
