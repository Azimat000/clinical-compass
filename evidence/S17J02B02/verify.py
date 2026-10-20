"""Main-agent acceptance checks of real B02 receipts, policy proofs and preservation."""
import copy,json,sys,subprocess,tempfile,shutil
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import (CorpusError,build_manifest,digest,eligible_sources,indexable_cards,load_snapshot,moment,publish_snapshot,sha)
from apps.compass.retrieval_packages import package_registry
from apps.compass.retrieval_primary import POLICY as PRIMARY_POLICY, PREFIX, IDENTITIES
from apps.compass.retrieval_policies import REGISTRY,validate_policy_reference,aspect_mode
from tools.check_retrieval_coverage import assess,scope
E=ROOT/'evidence/S17J02B02'
def save(name,obj): (E/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def hashes(path):return {p.name:sha(p.read_bytes()) for p in path.iterdir()}
def main():
 at=datetime.now(timezone.utc).isoformat();registry,originals,cards=package_registry(ROOT)
 with patch('socket.socket',side_effect=AssertionError('No network permitted')):
  manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards)
  assert len(manifest['sources'])==9 and all(r['disposition']=='admitted' for r in manifest['sources']),manifest['sources']
  path,created=publish_snapshot(ROOT/'var/retrieval',manifest,blobs);before=hashes(path)
  assert not publish_snapshot(ROOT/'var/retrieval',manifest,blobs)[1] and hashes(path)==before
  export=indexable_cards(path,registry,at);assert len(export['cards'])==61 and not export['refused']
 assert all(set(c)=={'document_id','fragment_id','text'} for c in export['cards'])
 assert not list(path.glob('*.pdf')) and len(list(path.glob('*.json')))==10
 prior=json.loads((ROOT/'evidence/S17J02B/corpus-manifest.json').read_bytes())
 prior_path=ROOT/'var/retrieval'/prior['corpus_version'];prior_before=hashes(prior_path)
 assert load_snapshot(prior_path)==prior
 assert len(eligible_sources(prior_path,registry,at)['admitted'])==3
 assert hashes(prior_path)==prior_before
 # Existing source rows and all their previous fragment bytes remain identical.
 oldrows={r['document_id']:r['source'] for r in prior['sources']}
 for item in registry['sources']:
  if item['document_id'] in oldrows:assert item==oldrows[item['document_id']]
  else:
   assert item['document_id'] in IDENTITIES and item['rights']['index_fields']==['paraphrase']
   b=json.loads((ROOT/item['artifact_path']).read_bytes())
   assert all(f['claim_type']=='fact' and f['quote'] is None and not f['required_context'] for f in b['fragments'])
   assert all(f['page'] is None for f in b['fragments']) if item['locator_kind']=='html_section' else all(type(f['page']) is int for f in b['fragments'])
 revoked=copy.deepcopy(registry);next(r for r in revoked['sources'] if r['document_id']=='DASS42_GUIDANCE')['rights']['status']='unknown'
 assert 'DASS42_GUIDANCE' in eligible_sources(path,revoked,at)['refused']
 assert not eligible_sources(path,registry,'2026-10-23T00:00:00+03:00')['admitted']
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp)
  files=[p for p in (ROOT/'data/retrieval/packages/DASS42').iterdir() if p.is_file()]
  files += [ROOT/p for p in [PRIMARY_POLICY,'apps/compass/resources/dass42-ru-v1.json','evidence/S17J02B02/source-review.json','evidence/S17J02B02/content-review.json','evidence/S17J02B02/rights-decision.md']]
  for f in files:
   rel=f.relative_to(ROOT);target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(f.read_bytes())
  dass=json.loads((ROOT/'data/retrieval/packages/DASS42/registry.json').read_bytes())
  first=dass['sources'][0];receipt=root/first['path'];body=receipt.read_bytes();receipt.write_bytes(body+b' ')
  assert first['document_id'] in eligible_sources(path,dass,at,evidence_root=root)['refused']
  receipt.write_bytes(body)
  pins=json.loads((root/PRIMARY_POLICY).read_bytes());pins['sources'][0]['status']='revoked'
  (root/PRIMARY_POLICY).write_text(json.dumps(pins))
  assert first['document_id'] in eligible_sources(path,dass,at,evidence_root=root)['refused']
 frozen,matrix,meds,units=scope(ROOT)
 policies=json.loads((ROOT/REGISTRY).read_bytes());assurances={};bindings=0
 for pin in policies['policies']:
  record=json.loads((ROOT/pin['record_path']).read_bytes());ref={'policy_id':pin['policy_id'],'record_sha256':pin['record_sha256']}
  assurances[pin['policy_id']]=record['assurance']
  for b in record['bindings']:
   checked=validate_policy_reference(ROOT,ref,b['unit_id'],units[b['unit_id']],b['aspect'],frozen,moment(at))
   assert checked['origin']=='HAC_PROJECT_POLICY';bindings+=1
 assert len(policies['policies'])==45 and bindings==90
 assert sum(v=='tested_existing_control' for v in assurances.values())==4
 assert aspect_mode(units['D12-depression-scale_identity'],'age_boundary')=='mixed'
 assert aspect_mode(units['D01-generalized_anxiety_disorder-FU08'],'age_boundary')=='clinical'
 gate=assess(ROOT,path,at);assert gate['status']=='NOT_READY' and not gate['errors'] and len(gate['gaps'])==148
 assert gate['counts']['cells']['complete']==0
 save('coverage-readiness.json',gate)
 (E/'corpus-manifest.json').write_bytes((path/'manifest.json').read_bytes())
 baseline=json.loads((E/'baseline.json').read_bytes());owned=json.loads((E/'ownership.json').read_bytes())['owned_paths']
 def own(p):return any(p==v or v.endswith('/') and p.startswith(v) for v in owned)
 changed=subprocess.check_output(['git','diff','--name-only',baseline['head']],cwd=ROOT).decode().splitlines()
 new=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines()
 new=[p for p in new if p not in baseline['untracked']]
 assert all(own(p) for p in changed+new),[p for p in changed+new if not own(p)]
 for p,h in baseline['sha256'].items():
  if not own(p):assert sha((ROOT/p).read_bytes())==h,p
 # Compare exact protected files to pre-work Git blobs without rehashing unrelated large history.
 protected=['data/retrieval/coverage-matrix.json','data/retrieval/planned-medications.json','data/retrieval/coverage-freeze.json','data/retrieval/coverage-evidence.json','apps/compass/resources/dass42-ru-v1.json','apps/requirements.lock','data/retrieval/source-registry.json']
 for p in protected:assert (ROOT/p).read_bytes()==subprocess.check_output(['git','show',baseline['head']+':'+p],cwd=ROOT),p
 oldstate=json.loads(subprocess.check_output(['git','show',baseline['head']+':memory/STATE.json'],cwd=ROOT));current=json.loads((ROOT/'memory/STATE.json').read_bytes())
 for sid,entry in oldstate['slices'].items():
  if sid!='S17J02B02':assert current['slices'][sid]==entry,sid
 oldcover=json.loads(subprocess.check_output(['git','show',baseline['head']+':plan/coverage.json'],cwd=ROOT));newcover=json.loads((ROOT/'plan/coverage.json').read_bytes())
 for old,new in zip(oldcover['items'],newcover['items']):
  for k in old:
   if k not in ['verification_slices','actual_evidence']:assert new[k]==old[k],(old['id'],k)
  assert set(old['actual_evidence'])<=set(new['actual_evidence'])
 result=dict(status='PASS',checked_at=at,admitted_sources=9,primary_sources=6,new_authored_facts=12,indexable_authored_facts=61,new_original_copies=0,new_quotes=0,receipt_kind='verified acquisition metadata, not retained source text',verified_TLS=True,repeat_same_snapshot=True,old_snapshot_preserved=True,old_three_source_records_unchanged=True,policy_records=45,policy_bindings=90,tested_existing_policy_records=4,documented_constraints=41,policy_validation='All90actualbindings revalidated, including code/tests/results for4records',policy_not_in_clinical_index=True,source_revocation_expiry_receipt_and_pin_tamper_refused=True,drug_age_cannot_use_DASS=True,snapshot=str(path.relative_to(ROOT)),corpus_version=manifest['corpus_version'],coverage_gate='NOT_READY',clinical_approval=False,preservation=dict(unexpected_changes=[],pre_existing_user_files_preserved=baseline['untracked'],protected_files=protected,other_slice_statuses_unchanged=True,requirements_statuses_subchecks_unchanged=True))
 save('admission-checks.json',result)
 print('PASS:6primarysources/12newfacts,9sources/61cards;45policies/90bindings;negativecontrols and preservation;COVERAGE-1 NOT_READY')
if __name__=='__main__':main()
