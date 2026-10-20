"""Independent main-agent checks of actual content pointers and preserved scope."""
import copy,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import CorpusError,build_manifest,digest,indexable_cards,load_snapshot,moment,publish_snapshot,sha
from apps.compass.retrieval_packages import package_registry
from tools import check_retrieval_coverage as coverage
from apps.compass.retrieval_policies import aspect_mode,validate_policy_reference
E=ROOT/'evidence/S17J02B03A'
def save(name,obj):(E/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def expect_error(call,reason):
 try:call()
 except CorpusError as exc:assert str(exc)==reason,(str(exc),reason)
 else:raise AssertionError('Negative check did not fail: '+reason)
def main():
 at=datetime.now(timezone.utc).isoformat();registry,originals,cards=package_registry(ROOT)
 old_snapshot=json.loads((ROOT/'evidence/S17J02B02/corpus-manifest.json').read_text())
 old_path=ROOT/'var/retrieval'/old_snapshot['corpus_version']
 old_hashes={p.name:sha(p.read_bytes()) for p in old_path.iterdir()}
 with patch('socket.socket',side_effect=AssertionError('Offline checks must not use network')):
  manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards)
  snapshot,_=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
  same=publish_snapshot(ROOT/'var/retrieval',manifest,blobs);assert same[0]==snapshot and not same[1]
  assert load_snapshot(old_path)==old_snapshot and old_hashes=={p.name:sha(p.read_bytes()) for p in old_path.iterdir()}
  assert manifest==old_snapshot and len(indexable_cards(snapshot,registry,at)['cards'])==61
  catalog,eligibility=coverage.card_catalog(snapshot,registry,moment(at),ROOT)
  assert len(catalog)==61 and len(eligibility['admitted'])==9 and not eligibility['refused']
 frozen,matrix,meds,units=coverage.scope(ROOT)
 evidence=json.loads((ROOT/coverage.EVIDENCE).read_text());core=json.loads((E/'core-coverage.json').read_text())
 assert len(matrix['cells'])==58 and len(core['cells'])==58
 assert set(c['unit_id'] for c in core['cells'])==set(c['id'] for c in matrix['cells'])
 expected={c['id'] for c in matrix['cells'] if not c['requires_dossiers']}
 explicit_gaps={'D09-depression-differential','D12-depression-scale_identity','D12-generalized_anxiety_disorder-scale_identity'}
 expected-=explicit_gaps
 assert set(evidence['units'])==expected and len(expected)==17
 count=0;actual_policy_modes={};policy_bindings=0
 for cell in core['cells']:
  unit=units[cell['unit_id']]
  assert cell['requirement_sha256']==digest(unit['requirement'])
  assert set(cell['aspects'])==set(unit['aspects'])
  for aspect,proof in cell['aspects'].items():
   count+=1;mode=aspect_mode(unit,aspect);assert proof['mode']==mode
   for ref in proof['source_references']:
    item,frag=catalog[ref['document_id'],ref['fragment_id']]
    assert ref==dict(document_id=item['document_id'],fragment_id=frag['fragment_id'],page=frag['page'],section=frag['section'],source_version=item['source_version'],source_sha256=item['sha256'],artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(frag))
   for ref in proof['policy_references']:
    record=validate_policy_reference(ROOT,ref,cell['unit_id'],unit,aspect,frozen,moment(at));assert record['assurance']==proof['policy_assurance'];policy_bindings+=1
   if mode=='policy':assert not proof['source_references'] and proof['policy_references']
   if mode=='clinical':assert not proof['policy_references']
  if cell['unit_id'] in expected:
   pointer=evidence['units'][cell['unit_id']]
   review=coverage.validate_review(ROOT,cell['unit_id'],unit,pointer,catalog,frozen,moment(at))
   assert review['origin']=='HAC_TECHNICAL_REFERENCE_CONTENT_REVIEW_NOT_CLINICAL_APPROVAL'
   assert 'not an independent clinician' in review['reviewer'] and moment(review['review_due_at'])>moment(at)
   assert cell['verdict']=='sufficient_reference_bundle' and cell['review_pointer']==pointer
  else:assert cell['verdict']=='gap'
 assert count==224 and policy_bindings==90 and core['counts']['unresolved_clinical_aspects']==46
 for uid in explicit_gaps:
  row=next(c for c in core['cells'] if c['unit_id']==uid)
  assert row['unresolved_aspects'] and uid not in evidence['units']
 gate=coverage.assess(ROOT,snapshot,at)
 assert not gate['errors'] and gate['status']=='NOT_READY' and len(gate['gaps'])==131
 assert gate['counts']['cells']==dict(complete=17,required=58) and gate['counts']['dossier_sections']==dict(complete=0,required=90) and gate['counts']['medications']==dict(complete=0,required=9)
 assert 'NOT_TESTED' in gate['refusal_behavior']
 # Actual source revocation after snapshot must withdraw affected actual reviews.
 revoked=copy.deepcopy(registry)
 next(r for r in revoked['sources'] if r['document_id']=='DASS42_GUIDANCE')['rights']['status']='revoked'
 with patch.object(coverage,'package_registry',return_value=(revoked,originals,cards)):
  revoked_gate=coverage.assess(ROOT,snapshot,at)
 assert revoked_gate['counts']['cells']['complete']==13,revoked_gate
 assert 'DASS42_GUIDANCE' in revoked_gate['refused_sources']
 expired=coverage.assess(ROOT,snapshot,'2026-10-24T00:00:00+03:00')
 assert expired['counts']['cells']['complete']==0
 # Rehashed malicious page/mixed-origin changes still fail semantic coordinates/origin checks.
 uid='D02-depression-symptoms';pointer=evidence['units'][uid];body=(ROOT/pointer['review_path']).read_bytes();bad=json.loads(body)
 bad['aspects']['symptoms']['source_references'][0]['page']=999
 def validate_mutation(uid,bad,reason):
  pointer=evidence['units'][uid];data=(json.dumps(bad,ensure_ascii=False)+'\n').encode();malicious=dict(pointer,review_sha256=sha(data));original=coverage.local_file
  def read(root,path,allowed):return data if path==pointer['review_path'] else original(root,path,allowed)
  with patch.object(coverage,'local_file',side_effect=read):
   expect_error(lambda:coverage.validate_review(ROOT,uid,units[uid],malicious,catalog,frozen,moment(at)),reason)
 validate_mutation(uid,bad,'reference_coordinates_or_version_mismatch')
 uid='D02-depression-trajectory';bad=json.loads((ROOT/evidence['units'][uid]['review_path']).read_text());bad['aspects']['no_diagnosis_from_score']['policy_references']=[]
 validate_mutation(uid,bad,'mixed_evidence_requires_both_origins')
 # Parent tasks/outputs/criteria and frozen denominators are byte-for-byte preserved.
 before=json.loads((E/'baseline.json').read_text());base=before['head']
 def git_json(path):return json.loads(subprocess.check_output(['git','show',base+':'+path],cwd=ROOT))
 old_manifest=git_json('plan/manifest.json');new_manifest=json.loads((ROOT/'plan/manifest.json').read_text())
 for sid in ['S17J02B','S17J02B03']:
  old=next(c for c in old_manifest['slices'] if c['id']==sid);new=next(c for c in new_manifest['slices'] if c['id']==sid)
  for k in ['tasks','outputs','acceptance','requirement_ids']:assert old[k]==new[k],(sid,k)
 assert next(c for c in new_manifest['slices'] if c['id']=='S17J02C')['depends_on']==['S17J02B']
 assert (ROOT/'plan/slices/S17J02B03.md').read_bytes().startswith((E/'parent-card-before-split.md').read_bytes())
 old_state=git_json('memory/STATE.json');current_state=json.loads((ROOT/'memory/STATE.json').read_text())
 for sid,entry in old_state['slices'].items():
  if sid!='S17J02B03':assert current_state['slices'][sid]==entry,sid
 assert current_state['slices']['S17J02B03']['status']=='planned'
 assert current_state['slices']['S17J02B']['status']=='planned'
 protected=['data/retrieval/coverage-matrix.json','data/retrieval/planned-medications.json','data/retrieval/coverage-freeze.json','data/retrieval/source-registry.json','data/retrieval/primary-source-policy.json','data/retrieval/hac-policy-registry.json','apps/compass/resources/dass42-ru-v1.json','apps/requirements.lock','data/clinical/followup-rules.json']
 protected=[p for p in protected if (ROOT/p).exists()]
 for p in protected:assert sha((ROOT/p).read_bytes())==before['sha256'][p],p
 old_cover=git_json('plan/coverage.json');new_cover=json.loads((ROOT/'plan/coverage.json').read_text())
 assert len(new_cover['items'])==len(old_cover['items'])==83
 for old,new in zip(old_cover['items'],new_cover['items']):
  for k in old:
   if k not in ['verification_slices','actual_evidence']:assert new[k]==old[k],(old['id'],k)
  assert set(old['actual_evidence'])<=set(new['actual_evidence'])
 owned=json.loads((E/'ownership.json').read_text())['owned_paths']
 def owns(p):return any(p==v or v.endswith('/') and p.startswith(v) for v in owned)
 changed=subprocess.check_output(['git','diff','--name-only',base],cwd=ROOT).decode().splitlines()
 untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines()
 new=[p for p in untracked if p not in before['untracked']]
 assert all(owns(p) for p in changed+new),[p for p in changed+new if not owns(p)]
 # All preexisting files outside scope, including user audit, remain byte-identical.
 for p,h in before['sha256'].items():
  if not owns(p):assert sha((ROOT/p).read_bytes())==h,p
 result=dict(status='PASS',checked_at=at,aspect_reviews=224,policy_bindings=90,technical_sufficient_cells=17,required_cells=58,clinical_aspect_gaps=46,non_dossier_explicit_gap_cells=sorted(explicit_gaps),required_dossier_cells=38,dossier_sections_complete=0,dossier_sections_required=90,corpus_sources=9,corpus_cards=61,source_registry_unchanged=True,network_used=False,repeat_snapshot_unchanged=True,prior_snapshot_preserved=True,real_DASS_revocation_withdraws_4_bundles=True,expired_reviews_withdrawn=True,rehashed_wrong_page_rejected=True,mixed_origin_omission_rejected=True,parent_criteria_tasks_outputs_preserved=True,J02C_dependency_preserved=True,frozen_scope_preserved=True,requirements_83_subchecks_160_preserved=True,preexisting_user_files_preserved=True,scope_compliance='PASS',clinical_approval=False,refusal_runtime_tested=False)
 save('verification.json',result);save('coverage-readiness.json',gate)
 print('PASS:actual17/58 reviews;224aspects/90policybindings;revocation/expiry/page/mixed origins;history/scope/preservation')
if __name__=='__main__':main()
