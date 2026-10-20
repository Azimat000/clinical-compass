"""Main-agent acceptance audit: real supplement, preserved baseline, honest failure."""
import copy,json,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import (admission_reasons,build_manifest,digest,eligible_sources,indexable_cards,load_snapshot,moment,publish_snapshot,sha)
from apps.compass.retrieval_packages import package_registry
from apps.compass.retrieval_primary import GUIDELINE_IDENTITIES,GUIDELINE_POLICY,validate_primary
from apps.compass.retrieval_policies import validate_policy_reference
from tools import check_retrieval_coverage as coverage
E=ROOT/'evidence/S17J02B03B'
def save(name,data):(E/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def main():
 at=datetime.now(timezone.utc).isoformat();baseline=json.loads((E/'baseline.json').read_text());base=baseline['head']
 registry,originals,cards=package_registry(ROOT)
 prior=json.loads((ROOT/'evidence/S17J02B03A/corpus-manifest.json').read_text());old_path=ROOT/'var/retrieval'/prior['corpus_version'];old_hashes={p.name:sha(p.read_bytes()) for p in old_path.iterdir()}
 old_items={r['document_id']:r['source'] for r in prior['sources']}
 with patch('socket.socket',side_effect=AssertionError('No network in import/coverage')):
  manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards);snapshot,_=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
  assert all(s['disposition']=='admitted' for s in manifest['sources']) and len(manifest['sources'])==11
  assert not publish_snapshot(ROOT/'var/retrieval',manifest,blobs)[1]
  exported=indexable_cards(snapshot,registry,at);assert len(exported['cards'])==63 and not exported['refused']
  assert load_snapshot(old_path)==prior and old_hashes=={p.name:sha(p.read_bytes()) for p in old_path.iterdir()}
  assert len(eligible_sources(old_path,registry,at)['admitted'])==9
 for item in registry['sources']:
  if item['document_id'] in old_items:assert item==old_items[item['document_id']]
  else:
   assert item['document_id'] in GUIDELINE_IDENTITIES and item['document_type']=='clinical_guideline'
   assert item['rights']['index_fields']==['paraphrase'] and not admission_reasons(item,moment(at),evidence_root=ROOT)
   validate_primary(item,ROOT)
 assert len(list(snapshot.glob('*.json')))==12 and not list(snapshot.glob('*.pdf'))
 new=json.loads((ROOT/'data/retrieval/packages/J02B03B/registry.json').read_text())
 for item in new['sources']:
  artifact=json.loads((ROOT/item['artifact_path']).read_text());assert len(artifact['fragments'])==1
  f=artifact['fragments'][0];assert f['claim_type']=='fact' and f['quote'] is None and not f['required_context']
  assert f['page']==(17 if item['document_id']=='KR456_3' else 16)
 frozen,matrix,meds,units=coverage.scope(ROOT);catalog,elig=coverage.card_catalog(snapshot,registry,moment(at),ROOT)
 core=json.loads((ROOT/'evidence/S17J02B03/core-coverage.json').read_text());assert len(core['cells'])==58
 assert core['counts']['total_aspects']==224 and core['counts']['unresolved_clinical_aspects']==45
 count=0;bindings=0
 for row in core['cells']:
  unit=units[row['unit_id']];assert row['requirement_sha256']==digest(unit['requirement']) and set(row['aspects'])==set(unit['aspects'])
  for aspect,proof in row['aspects'].items():
   count+=1
   for r in proof['source_references']:
    item,f=catalog[r['document_id'],r['fragment_id']]
    assert r==dict(document_id=item['document_id'],fragment_id=f['fragment_id'],page=f['page'],section=f['section'],source_version=item['source_version'],source_sha256=item['sha256'],artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(f))
   for p in proof['policy_references']:
    validate_policy_reference(ROOT,p,row['unit_id'],unit,aspect,frozen,moment(at));bindings+=1
 assert count==224 and bindings==90
 evidence=json.loads((ROOT/coverage.EVIDENCE).read_text());old_evidence=json.loads(subprocess.check_output(['git','show',base+':'+coverage.EVIDENCE],cwd=ROOT))
 uid='D09-depression-differential'
 assert set(evidence['units'])==set(old_evidence['units'])|{uid} and len(evidence['units'])==18
 for key,p in old_evidence['units'].items():assert evidence['units'][key]==p
 for unit_id,pointer in evidence['units'].items():coverage.validate_review(ROOT,unit_id,units[unit_id],pointer,catalog,frozen,moment(at))
 review=json.loads((ROOT/evidence['units'][uid]['review_path']).read_text());required={'KR301_3-F10','KR456_3-F01','KR451_3-F01'}
 assert {r['fragment_id'] for r in review['aspects']['other_disorders_including_bipolar_psychotic_and_panic']['source_references']}==required
 for gap_uid in ['D12-depression-scale_identity','D12-generalized_anxiety_disorder-scale_identity']:
  assert gap_uid not in evidence['units']
  row=next(r for r in core['cells'] if r['unit_id']==gap_uid)
  assert 'age_boundary' in row['unresolved_aspects']
 gate=coverage.assess(ROOT,snapshot,at);assert gate['status']=='NOT_READY' and not gate['errors'] and len(gate['gaps'])==130
 assert gate['counts']['cells']==dict(complete=18,required=58)
 assert gate['counts']['dossier_sections']==dict(complete=0,required=90) and gate['counts']['medications']==dict(complete=0,required=9)
 revoked=copy.deepcopy(registry);next(i for i in revoked['sources'] if i['document_id']=='KR451_3')['rights']['status']='revoked'
 with patch.object(coverage,'package_registry',return_value=(revoked,originals,cards)):
  withdrawn=coverage.assess(ROOT,snapshot,at)
 assert withdrawn['counts']['cells']['complete']==17 and 'KR451_3' in withdrawn['refused_sources']
 expired=coverage.assess(ROOT,snapshot,'2026-10-24T00:00:00+03:00');assert expired['counts']['cells']['complete']==0
 protected=['plan/manifest.json','plan/slices/S17J02B.md','plan/slices/S17J02B03.md','plan/slices/S17J02B03B.md','plan/slices/S17J02C.md','data/retrieval/coverage-freeze.json','data/retrieval/coverage-matrix.json','data/retrieval/planned-medications.json','data/retrieval/primary-source-policy.json','data/retrieval/source-registry.json','data/retrieval/hac-policy-registry.json','apps/requirements.lock','apps/compass/resources/dass42-ru-v1.json']
 for p in protected:assert sha((ROOT/p).read_bytes())==baseline['sha256'][p],p
 current=json.loads((ROOT/'memory/STATE.json').read_text());old_state=json.loads(subprocess.check_output(['git','show',base+':memory/STATE.json'],cwd=ROOT))
 for sid,entry in old_state['slices'].items():
  if sid!='S17J02B03B':assert current['slices'][sid]==entry,sid
 assert current['slices']['S17J02B03B']['status']!='accepted' and current['slices']['S17J02B03B']['commit_ref'] is None
 old_cover=json.loads(subprocess.check_output(['git','show',base+':plan/coverage.json'],cwd=ROOT));new_cover=json.loads((ROOT/'plan/coverage.json').read_text())
 assert len(new_cover['items'])==len(old_cover['items'])==83 and sum(len(i['subchecks']) for i in new_cover['items'])==160
 for old,current in zip(old_cover['items'],new_cover['items']):
  for key in old:
   if key not in ['actual_evidence']:assert current[key]==old[key],(old['id'],key)
  assert set(old['actual_evidence'])<=set(current['actual_evidence'])
 owned=json.loads((E/'ownership.json').read_text())['owned_paths']
 def owns(p):return any(p==v or v.endswith('/') and p.startswith(v) for v in owned)
 changed=subprocess.check_output(['git','diff','--name-only',base],cwd=ROOT).decode().splitlines();untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT).decode().splitlines();created=[p for p in untracked if p not in baseline['untracked']]
 assert all(owns(p) for p in changed+created),[p for p in changed+created if not owns(p)]
 assert not any(p.endswith(('.pdf','.html','.htm')) for p in created)
 for p,h in baseline['sha256'].items():
  if not owns(p):assert sha((ROOT/p).read_bytes())==h,p
 proposal=json.loads((E/'plan-amendment-proposal.json').read_text());assert proposal['status']=='PROPOSAL_ONLY_NOT_APPLIED' and proposal['verification']['proposed_graph_acyclic']
 save('coverage-readiness.json',gate)
 save('verification.json',dict(status='PASS_TECHNICAL_CHECKS_B03B_NOT_ACCEPTED',checked_at=at,new_sources=2,new_fact_cards=2,new_quotes=0,new_original_copies=0,corpus_sources=11,corpus_cards=63,technical_bundles=18,required_cells=58,clinical_aspect_gaps=45,checked_aspects=224,policy_bindings=90,remaining_scale_age_cells=2,remaining_dossier_cells=38,remaining_dossier_sections=90,source_revocation_withdraws_new_bundle=True,expired_material_withdrawn=True,repeat_offline=True,old_snapshot_and_9_source_records_preserved=True,old17reviews_byte_identical=True,frozen_requirements_83_160_and_all_criteria_preserved=True,preexisting_user_files_preserved=True,scope_compliance='PASS',clinical_approval=False,dependencies_changed=False,plan_proposal_applied=False))
 print('PASS:11sources/63facts;18of58bundles;224aspects/90policybindings;revocation/expiry/repeat/history/preservation;B03B NOT_ACCEPTED')
if __name__=='__main__':main()
