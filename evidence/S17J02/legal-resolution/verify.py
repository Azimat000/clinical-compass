"""Independent acceptance/preservation audit for the scoped legal resolution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import (CorpusError,build_manifest,digest,eligible_sources,
    indexable_cards,load_snapshot,publish_snapshot)

def load(path):return json.loads((ROOT/path).read_text())
def sha(path):return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
def old(path):return json.loads(subprocess.check_output(['git','-C',str(ROOT),'show',baseline['head']+':'+path]))

baseline=load('evidence/S17J02/legal-resolution/baseline.json')
allowed={'START_HERE.md','memory/STATE.json','memory/DECISIONS.md','memory/BLOCKERS.md',
'memory/EXTERNAL.md','memory/BUDGET.json','memory/sessions/S17J02.md','plan/coverage.json',
'plan/COVERAGE.md','plan/slices/S17J02.md','apps/compass/retrieval_corpus.py',
'apps/tests/test_retrieval_corpus.py','tools/import_retrieval_corpus.py',
'data/retrieval/source-registry.json','docs/architecture/retrieval-corpus.md',
'docs/architecture/source-retrieval-contract.md','evidence/S17J02/corpus-manifest.json',
'evidence/S17J02/import-results.json','evidence/S17J02/acceptance.md',
'evidence/S17J02/checks.json','evidence/S17J02/requirements-review.json'}
changed=[p for p,h in baseline['sha256'].items() if not (ROOT/p).is_file() or sha(p)!=h]
assert set(changed)<=allowed,changed
before,after=old('plan/coverage.json')['items'],load('plan/coverage.json')['items']
assert len(before)==len(after)==83 and sum(len(i['subchecks']) for i in after)==160
for a,b in zip(before,after):
 for k in a:
  if k!='actual_evidence':assert a[k]==b[k],(a['id'],k)
 assert set(a['actual_evidence'])<=set(b['actual_evidence'])
for sid,entry in old('memory/STATE.json')['slices'].items():
 if sid!='S17J02':assert load('memory/STATE.json')['slices'][sid]==entry,sid
results=load('evidence/S17J02/import-results.json');at=results['evaluated_at']
registry=load('data/retrieval/source-registry.json');originals=old('data/retrieval/source-registry.json')
for a,b in zip(originals['sources'],registry['sources']):
 for key in ('document_id','document_family','path','sha256','source_url','source_version','document_type','verification','population','indications','official_status'):
  assert a[key]==b[key],(a['document_id'],key)
 assert sha(b['path'])==a['sha256']
 assert b['full_text_rights']['status']=='unknown'
manifest,blobs=build_manifest(ROOT,registry,at)
assert manifest==load('evidence/S17J02/corpus-manifest.json')
snapshot=ROOT/'evidence/S17J02/corpus'/manifest['corpus_version']
assert load_snapshot(snapshot)==manifest
assert len(blobs)==3 and not list(snapshot.glob('*.pdf'))
projection=indexable_cards(snapshot,registry,at)
assert projection['status']=='AVAILABLE' and len(projection['cards'])==15
quoted=[]
for item in registry['sources']:
 bundle=json.loads((snapshot/(item['artifact_sha256']+'.json')).read_bytes())
 assert len(bundle['fragments'])==5
 for f in bundle['fragments']:
  entry=next(c for c in projection['cards'] if c['fragment_id']==f['fragment_id'])
  assert entry['text']==f['paraphrase'] and set(entry)=={'document_id','fragment_id','text'}
  if f['quote']:
   text=subprocess.check_output(['pdftotext','-f',str(f['page']),'-l',str(f['page']),str(ROOT/item['path']),'-']).decode()
   assert f['quote'] in ' '.join(text.split())
   assert f['quote'] not in json.dumps(projection,ensure_ascii=False)
   quoted.append(f['fragment_id'])
  else:assert f['claim_type']=='fact' and not f['required_context']
assert len(quoted)==2
avi=registry['sources'][2]
assert avi['rights']['content_review']['quoted_characters']==0 and 'display_excerpt' not in avi['rights']['scopes']
negative={}
for label,operation in [
 ('revoked',lambda s:s.update(status='revoked')),
 ('rights_lost',lambda s:s['rights'].update(status='revoked')),
 ('scope_escalation_full_pdf',lambda s:s.update(representation='full_pdf')),
 ('scope_escalation_quote_index',lambda s:s['rights'].update(index_fields=['quote'])),
 ('stale_official_status',lambda s:s.update(official_status='withdrawn'))]:
 altered=deepcopy(registry)
 for source in altered['sources']:operation(source)
 assert not eligible_sources(snapshot,altered,at)['admitted']
 assert not indexable_cards(snapshot,altered,at)['cards']
 negative[label]='PASS'
assert not eligible_sources(snapshot,registry,registry['sources'][0]['review_due_at'])['admitted']
negative['expiry_exact_boundary']='PASS'
with tempfile.TemporaryDirectory() as temp:
 target,created=publish_snapshot(temp,manifest,blobs)
 assert created and not publish_snapshot(temp,manifest,blobs)[1]
 am,ab=build_manifest(ROOT,registry,at,archive=True)
 archive,_=publish_snapshot(temp,am,ab)
 assert not list(archive.glob('*.pdf')) and not eligible_sources(archive,registry,at)['admitted']
 bad=target/(registry['sources'][0]['artifact_sha256']+'.json');bad.write_text('{}')
 try:eligible_sources(target,registry,at)
 except CorpusError:negative['snapshot_corruption']='PASS'
 else:raise AssertionError('corruption not detected')
 assert negative.get('snapshot_corruption')=='PASS'
assert load('memory/BUDGET.json')['spent']==load('memory/BUDGET.json')['commitments']==0
print(json.dumps(dict(status='PASS',baseline_files=len(baseline['sha256']),changed_original_paths=changed,
requirements=83,subchecks=160,all_other_slices_preserved=True,originals_scales_dependencies_and_audit_files_preserved=True,
corpus_version=manifest['corpus_version'],admitted_representations=3,cards=15,quoted_fragments=quoted,
full_pdf_copies_in_snapshot=0,quote_text_in_index=False,negative_checks=negative,
archive_ineligible=True,repeat_without_duplicates=True,clinical_validation=False),ensure_ascii=False,indent=2))
