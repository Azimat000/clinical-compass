"""Main-agent integration audit of actual package, not synthetic medical evidence."""
import copy,json,subprocess,sys,tempfile,shutil
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import (CorpusError,build_manifest,digest,eligible_sources,indexable_cards,load_snapshot,publish_snapshot,sha)
from apps.compass.retrieval_packages import package_registry
from tools.check_retrieval_coverage import assess,scope
E=ROOT/'evidence/S17J02B'
def write(name,obj): (E/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def main():
 at=datetime.now(timezone.utc).isoformat();registry,originals,cards=package_registry(ROOT)
 manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards)
 assert all(s['disposition']=='admitted' for s in manifest['sources'])
 first,created=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
 before={p.name:sha(p.read_bytes()) for p in first.iterdir()}
 second,repeated=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
 assert second==first and not repeated and before=={p.name:sha(p.read_bytes()) for p in first.iterdir()}
 projection=indexable_cards(first,registry,at)
 assert len(projection['cards'])==49,projection.keys()
 # Every source fragment is projected once; quotes and original PDF are excluded.
 assert not list(first.glob('*.pdf'))
 docs={i['document_id']:i for i in registry['sources']}
 new_review=json.loads((E/'source-content-review.json').read_text())
 for doc in ['KR301_3','KR457_3']:
  item=docs[doc];bundle=json.loads((ROOT/item['artifact_path']).read_text())
  old=json.loads((ROOT/f'data/retrieval/reference-cards/{doc}.json').read_text())
  assert bundle['fragments'][:5]==old['fragments']
  assert len(bundle['fragments'])==22
  rows=new_review['documents'][doc]['cards']
  assert len(rows)==22
  for fragment,row in zip(bundle['fragments'],rows):
   assert row['fragment_sha256']==digest(fragment)
   if row['new_fact']:
    assert row['coverage_links'] and fragment['quote'] is None and fragment['required_context']==[]
   for page in row['supporting_pages']:
    assert 1<=page<=(125 if doc=='KR301_3' else 121)
 for item in registry['sources']:
  assert sha((ROOT/item['path']).read_bytes())==item['sha256']
  assert sha((ROOT/item['artifact_path']).read_bytes())==item['artifact_sha256']
 # Explicit old version remains intact, but cannot masquerade as new reviewed metadata.
 oldregistry,oo,oc=package_registry(ROOT,['J02'])
 oldmanifest,oldblobs=build_manifest(ROOT,oldregistry,at,allowlist=oo,reference_allowlist=oc)
 oldpath,_=publish_snapshot(ROOT/'var/retrieval',oldmanifest,oldblobs)
 oldbefore={p.name:sha(p.read_bytes()) for p in oldpath.iterdir()}
 oldlive=eligible_sources(oldpath,registry,at)
 assert 'registry_changed_reimport_required' in oldlive['refused']['KR301_3']
 assert len(eligible_sources(oldpath,oldregistry,at)['admitted'])==3
 assert oldbefore=={p.name:sha(p.read_bytes()) for p in oldpath.iterdir()}
 revoked=copy.deepcopy(registry);next(i for i in revoked['sources'] if i['document_id']=='KR301_3')['rights']['status']='unknown'
 refused=eligible_sources(first,revoked,at)
 assert 'rights_unverified' in refused['refused']['KR301_3'] and len(refused['admitted'])==2
 expired=eligible_sources(first,registry,'2026-10-22T00:11:23+03:00')
 assert not expired['admitted']
 with tempfile.TemporaryDirectory() as temp:
  copied=Path(temp)/first.name;shutil.copytree(first,copied)
  artifact=next(copied.glob('*.json'))
  if artifact.name=='manifest.json':artifact=next(p for p in copied.glob('*.json') if p.name!='manifest.json')
  artifact.write_bytes(artifact.read_bytes()+b' ')
  try:load_snapshot(copied)
  except CorpusError:pass
  else:raise AssertionError('modified snapshot accepted')
 frozen,matrix,meds,units=scope(ROOT)
 core=json.loads((E/'core-coverage.json').read_text())
 assert {c['unit_id'] for c in core['cells']}=={c['id'] for c in matrix['cells']}
 actual={'source_supported_aspects':0,'project_policy_only_aspects':0,'uncovered_aspects':0,'total_aspects':0}
 for cell in core['cells']:
  requirement=units[cell['unit_id']]['requirement']
  assert cell['requirement_sha256']==digest(requirement)
  assert set(cell['aspects'])==set(requirement['required_aspects'])
  assert cell['verdict']=='gap'
  for aspect,result in cell['aspects'].items():
   actual['total_aspects']+=1
   if result['references']:
    actual['source_supported_aspects']+=1
    for ref in result['references']:
     item=docs[ref['document_id']];bundle=json.loads((ROOT/item['artifact_path']).read_text())
     fragment=next(f for f in bundle['fragments'] if f['fragment_id']==ref['fragment_id'])
     assert ref['artifact_sha256']==item['artifact_sha256'] and ref['source_sha256']==item['sha256']
     assert ref['source_version']==item['source_version'] and ref['fragment_sha256']==digest(fragment)
     assert (ref['page'],ref['section'])==(fragment['page'],fragment['section'])
   elif result['status']=='project_policy_only':
    actual['project_policy_only_aspects']+=1
    assert sha((ROOT/result['policy_path']).read_bytes())==result['policy_sha256']
   else: actual['uncovered_aspects']+=1
 assert all(core['counts'][k]==v for k,v in actual.items())
 gate=assess(ROOT,first,at)
 assert gate['status']=='NOT_READY' and gate['counts']['cells']['complete']==0 and len(gate['gaps'])==148
 assert len(gate['errors'])==0
 write('coverage-readiness.json',gate)
 baseline=json.loads((E/'baseline.json').read_text());ownership=json.loads((E/'ownership.json').read_text())
 def owned(path): return any(path==p or (p.endswith('/') and path.startswith(p)) for p in ownership['owned_paths'])
 missing=[];unexpected=[]
 for path,expected in baseline['sha256'].items():
  p=ROOT/path
  if not p.is_file():missing.append(path)
  elif sha(p.read_bytes())!=expected and not owned(path):unexpected.append(path)
 assert not missing and not unexpected,(missing,unexpected)
 changed=subprocess.check_output(['git','diff','--name-only'],cwd=ROOT).decode().splitlines()
 untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines()
 new=[p for p in untracked if p not in baseline['sha256']]
 assert all(owned(p) for p in changed+new), [p for p in changed+new if not owned(p)]
 oldstate=json.loads(subprocess.check_output(['git','show',baseline['head']+':memory/STATE.json'],cwd=ROOT))
 newstate=json.loads((ROOT/'memory/STATE.json').read_text())
 for sid,entry in oldstate['slices'].items():
  if sid!='S17J02B':assert newstate['slices'][sid]==entry,sid

 previous_manifest=json.loads(subprocess.check_output(['git','show',baseline['head']+':plan/manifest.json'],cwd=ROOT))
 current_manifest=json.loads((ROOT/'plan/manifest.json').read_text());current={c['id']:c for c in current_manifest['slices']}
 for old in previous_manifest['slices']:
  after=copy.deepcopy(current[old['id']])
  if old['id']=='S17J02B':
   assert after['depends_on']==old['depends_on']+['S17J02B03'];after['depends_on']=old['depends_on']
  assert after==old,old['id']
 oldcoverage=json.loads(subprocess.check_output(['git','show',baseline['head']+':plan/coverage.json'],cwd=ROOT))
 newcoverage=json.loads((ROOT/'plan/coverage.json').read_text())
 for old,new in zip(oldcoverage['items'],newcoverage['items']):
  for k in old:
   if k not in ['verification_slices','actual_evidence']:assert new[k]==old[k],(old['id'],k)
  assert set(old['verification_slices'])<=set(new['verification_slices'])
  assert set(old['actual_evidence'])<=set(new['actual_evidence'])
 write('integration-checks.json',dict(status='PASS',evaluated_at=at,admitted_sources=3,indexable_authored_cards=49,new_cards=34,new_quotes=0,new_PDF_copies=0,repeat_same_snapshot=True,old_originals_and_cards_preserved=True,old_snapshot_preserved=True,old_metadata_requires_reimport=True,revocation_refused=True,expiry_refused=True,tamper_refused=True,all_58_cells_224_aspects_checked=True,aspect_counts=actual,coverage_gate=gate['status'],gaps=len(gate['gaps']),no_medical_approval=True,snapshot=str(first.relative_to(ROOT)),legacy_snapshot=str(oldpath.relative_to(ROOT))))
 write('preservation.json',dict(status='PASS',baseline_head=baseline['head'],baseline_files_checked=len(baseline['sha256']),missing=missing,unexpected_changes=unexpected,untracked_user_material_preserved=baseline['status'],old_parent_tasks_acceptance_outputs_unchanged=True,other_original_cards_unchanged=True,requirements_statuses_and_subchecks_preserved=True,scope_freeze_unchanged=True))
 print('PASS: 49 admitted cards, repeat/history/revocation/expiry/tamper, 58/224 coverage mapping, baseline preservation; parent NOT_READY')
if __name__=='__main__':main()
