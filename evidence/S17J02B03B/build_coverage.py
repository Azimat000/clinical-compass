"""Add one exact differential bundle; keep all other evidence/history unchanged."""
import copy,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import build_manifest,digest,moment,publish_snapshot,sha
from apps.compass.retrieval_packages import package_registry
from tools.check_retrieval_coverage import assess,card_catalog,scope,validate_review
E='evidence/S17J02B03B/'
def save(path,obj):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def main():
 at=datetime.now(timezone.utc).isoformat();frozen,matrix,meds,units=scope(ROOT)
 registry,originals,cards=package_registry(ROOT);manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards);snapshot,_=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
 catalog,elig=card_catalog(snapshot,registry,moment(at),ROOT);assert len(elig['admitted'])==11 and len(catalog)==63 and not elig['refused']
 def ref(doc,fid):
  item,f=catalog[doc,fid]
  return dict(document_id=doc,fragment_id=fid,page=f['page'],section=f['section'],source_version=item['source_version'],source_sha256=item['sha256'],artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(f))
 core=json.loads((ROOT/'evidence/S17J02B03A/core-coverage.json').read_text());core.update(slice='S17J02B03B',checked_at=at,status='PARTIAL_CORE_NOT_ACCEPTED')
 uid='D09-depression-differential';aspect='other_disorders_including_bipolar_psychotic_and_panic';row=next(c for c in core['cells'] if c['unit_id']==uid)
 row['aspects'][aspect].update(status='source_evidence_reviewed',source_references=[ref('KR301_3','KR301_3-F10'),ref('KR456_3','KR456_3-F01'),ref('KR451_3','KR451_3-F01')],reason=None)
 row.update(verdict='sufficient_reference_bundle',unresolved_aspects=[],content_review='Составная граница оценки депрессивных симптомов: КР301 F10 требует выяснять манию/гипоманию/смешанные эпизоды для исключения БАР; КР456 F01 рассматривает панические проявления в контексте депрессии/БАР, без автоматического отдельного панического диагноза; КР451 F01 ограничена хронологией G1.1/G1.2 при F20.0–F20.3 и аффективном эпизоде. Наличие паники/психотического проявления не создаёт диагноз из анкеты и не переносит основания лечения. Соматические причины и оценка врача поддержаны прежними КР301 F09/F21/F01/F10; no_diagnosis_from_question — отдельная политика HAC. Комплект не устанавливает числовой возраст КР, персональную применимость или клиническое одобрение.')
 aspects={a:{k:p[k] for k in ['source_references','policy_references']} for a,p in row['aspects'].items()}
 dues=[]
 for proof in aspects.values():
  for r in proof['source_references']:dues.append(moment(catalog[r['document_id'],r['fragment_id']][0]['review_due_at']))
  for p in proof['policy_references']:
   record=json.loads((ROOT/('data/retrieval/policy-evidence/'+p['policy_id']+'.json')).read_text());dues.append(moment(record['review_due_at']))
 review=dict(schema_version=2,scope_version=frozen['scope_version'],unit_id=uid,requirement_sha256=digest(units[uid]['requirement']),verdict='sufficient',reviewer='Codex main agent, technical content review; not an independent clinician',origin='HAC_TECHNICAL_REFERENCE_CONTENT_REVIEW_NOT_CLINICAL_APPROVAL',sufficiency_explanation=row['content_review'],checked_at=at,review_due_at=min(dues).isoformat(),aspects=aspects)
 path='data/retrieval/coverage-reviews/S17J02B03B/'+uid+'.json';save(path,review);pointer=dict(review_path=path,review_sha256=sha((ROOT/path).read_bytes()));validate_review(ROOT,uid,units[uid],pointer,catalog,frozen,moment(at))
 row['review_pointer']=pointer;core['counts'].update(source_supported_aspects=99,unresolved_clinical_aspects=45,sufficient_cells=18);core['remaining_non_dossier_gap_cells']=['D12-depression-scale_identity','D12-generalized_anxiety_disorder-scale_identity'];core['dependency_audit']=E+'dependency-audit.json'
 # Do not rewrite or extend any of the seventeen accepted A reviews.
 evidence=json.loads((ROOT/'data/retrieval/coverage-evidence.json').read_text());evidence['units'][uid]=pointer;save('data/retrieval/coverage-evidence.json',evidence)
 gate=assess(ROOT,snapshot,at);assert gate['status']=='NOT_READY' and not gate['errors'] and gate['counts']['cells']['complete']==18 and len(gate['gaps'])==130
 save('evidence/S17J02B03/core-coverage.json',core);save(E+'coverage-readiness.json',gate);save(E+'corpus-manifest.json',manifest)
 print('18/58 technical bundles;11sources/63cards;45clinicalaspectgaps;0/90sections;B03B/B03/B NOT_ACCEPTED')
if __name__=='__main__':main()
