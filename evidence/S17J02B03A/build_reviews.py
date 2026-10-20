"""Integrate reviewed source/policy origins; never infer sufficiency from counts."""
import json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import build_manifest,digest,moment,publish_snapshot,sha
from apps.compass.retrieval_packages import package_registry
from apps.compass.retrieval_policies import aspect_mode,REGISTRY,validate_policy_reference
from tools.check_retrieval_coverage import scope,card_catalog,validate_review,assess
E=ROOT/'evidence/S17J02B03A'
def save(path,data):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
# Explicitly selected facts, based on B01 original review + B03A direct review.
# Each mapping is content evidence, not a count-based sufficiency rule.
DASS={
 'exact_Russian_form_and_key':['DASS42_RU_FORM-F01','DASS42_EN_KEY-F01','DASS42_RU_TRANSLATION-F01'],
 'validation_population':['DASS42_RU_VALIDATION_2025-F01','DASS42_RU_VALIDATION_2025-F02'],
 'text_rights_separately':['DASS42_GUIDANCE-F01','DASS42_DOWNLOAD_TERMS-F01'],
 'recall_period':['DASS42_RU_FORM-F02'],
 'age_boundary':['DASS42_GUIDANCE-F02','DASS42_RU_VALIDATION_2025-F01'],
 'three_separate_scores_for_physician':['DASS42_EN_KEY-F01','DASS42_EN_KEY-F02','DASS42_GUIDANCE-F04'],
 'no_diagnostic_or_medication_threshold':['DASS42_GUIDANCE-F03'],
 'no_diagnosis_from_score':['DASS42_GUIDANCE-F03']}
REVIEW={
 'symptoms':'КР описывает наблюдение симптомов вместе с функционированием. Для депрессии F05/F08 задают наблюдение и оценку динамики, F07/F16/F20 — работу/социальные контакты и неполное восстановление. F11 ограничена острой фазой с наблюдением не реже раза в неделю: это контекст этапа, не универсальное окно сравнения. Для ГТР F07 требует выяснять длительность и устойчивость жалоб, F20 отделяет социальное восстановление от тревоги. Период записи и пропуски данных сохраняются явно; универсального срока или диагноза не выводится.',
 'trajectory':'Сопоставимость одной формы, периодов и происхождение записей — отдельные ограничения HAC. FAQ DASS F03 отделяет размерные симптомы от категориального диагноза. Смешанный аспект имеет оба происхождения; КР не выдаётся за валидацию DASS. Комплект объясняет пределы сравнения, не доказывает валидность русской шкалы для конкретного возраста.',
 'critical':'Точная карточка КР подтверждает необходимость врачебной оценки суицидального риска в соответствующем направлении. Остальные аспекты — независимость существующего пути безопасности, отсутствие определения срочности поиском и недопустимость задержки — собственные ограничения HAC. Это достаточные справочные границы вопроса; проверка поведения будущего поиска и клинический протокол не засчитаны.',
 'no_answer':'Вопрос полностью о поведении HAC при отсутствии данных/источника: неизвестность не означает отсутствие риска, недоступность явна, сетевого или модельного запасного ответа нет. Все три аспекта имеют отдельные проектные основания. Это полнота документированных ограничений, не медицинский вывод и не проверка runtime.',
 'differential':'Для ГТР F08/F09/F10 различают депрессивные/биполярные, панические и психотические/органические состояния; F10/F22 — соматические причины; F01/F08/F09 — врачебная дифференциальная оценка. Политика запрещает вывод диагноза из вопроса. Для депрессии F10 поддерживает только БАР; полного перечня frozen-аспекта нет и эта ячейка не принимается.',
 'substances':'Карточки соответствующего направления явно учитывают вещества, лекарства и сопутствующую соматическую/психическую патологию. Для депрессии F09 описывает ПАВ и лекарственные причины; F21 — соматический контекст. Для ГТР F08/F10/F21 описывают зависимость, вещества/отмену/лекарства и ограничение алкоголя. Политики сохраняют неизвестность и запрещают перенос оснований между диагнозами. Лекарственное взаимодействие и индивидуальная причинность этим не установлены.',
 'psychotherapy':'Допущенные карточки перечисляют методы и их границы: для депрессии F19/F20 — КПТ/ИПТ/ПДТ, различия доказательств и обстоятельства выбора; для ГТР F13/F19 — стратегия, релаксация/КПТ, ограничения участия и сочетания. Подтверждённый врачом индивидуальный план — отдельная политика. Комплект отвечает о вариантах, не назначает курс.',
 'non_medical_followup':'Для депрессии F19/F20 допускают психотерапию на этапах лечения и социальное функционирование; F07/F16 отделяют функционирование и остаточные трудности от симптомов. Для ГТР F20/F21 задают реабилитационный/профилактический контекст, F19 — варианты и ограничения методов. Политика запрещает автоматический неподтверждённый протокол. Это сведения для поддерживающего наблюдения, не индивидуальные частоты или назначения.',
 'scale_interpretation':'Точный английский ключ даёт три шкалы по14пунктов и отделяет множитель DASS-21. FAQ отделяет размерные баллы от диагноза и ограничивает выдачу вычисленных результатов клиницистом/исследователем. HAC отдельно требует ту же полную форму, учёт пересечения периодов, три суммы только врачу и отсутствие диагностического/лекарственного порога. Технические ограничения подсчёта не подтверждают возрастную применимость русской валидации и не дают медицинской интерпретации.',
 'scale_identity':'Форма/английский ключ/страница перевода дают точную DASS-42; бланк — прошлую неделю; статья — фактическую выборку без её возраста; FAQ/условия — отдельные права. Возраст14+ из FAQ не заменяет неизвестный возраст русской выборки и18–120 из политики HAC. age_boundary остаётся содержательным пробелом, даже при наличии всех требуемых source-ID.'}

def main():
 at=datetime.now(timezone.utc).isoformat()
 frozen,matrix,meds,units=scope(ROOT)
 registry,originals,cards=package_registry(ROOT)
 manifest,blobs=build_manifest(ROOT,registry,at,allowlist=originals,reference_allowlist=cards)
 snapshot,_=publish_snapshot(ROOT/'var/retrieval',manifest,blobs)
 catalog,elig=card_catalog(snapshot,registry,moment(at),ROOT)
 assert len(elig['admitted'])==9 and not elig['refused']
 byid={fragment['fragment_id']:(item,fragment) for item,fragment in catalog.values()}
 def reference(fid):
  item,f=byid[fid]
  return dict(document_id=item['document_id'],fragment_id=fid,page=f['page'],section=f['section'],source_version=item['source_version'],source_sha256=item['sha256'],artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(f))
 policies={p['policy_id']:p for p in json.loads((ROOT/REGISTRY).read_text())['policies']}
 old=json.loads((ROOT/'evidence/S17J02B/core-coverage.json').read_text());oldcells={c['unit_id']:c for c in old['cells']}
 cells=[];evidence=dict(schema_version=1,scope_version=frozen['scope_version'],units={},clinical_approval='NOT_OBTAINED')
 counts=dict(required_cells=58,total_aspects=0,clinical_aspects=0,policy_aspects=0,mixed_aspects=0,source_supported_aspects=0,policy_supported_aspects=0,unresolved_clinical_aspects=0,non_dossier_cells=20,sufficient_cells=0)
 for c in matrix['cells']:
  uid=c['id'];unit=units[uid];suffix=uid.split('-',2)[-1];aspects={};review_aspects={};dues=[];gaps=[]
  for a in c['required_aspects']:
   counts['total_aspects']+=1;mode=aspect_mode(unit,a);counts[{'clinical':'clinical_aspects','policy':'policy_aspects','mixed':'mixed_aspects'}[mode]]+=1
   previous=oldcells[uid]['aspects'][a];refs=[] if mode=='policy' else previous['references']
   if c['domain']=='D12' or a=='no_diagnosis_from_score':
    if a in DASS:refs=[reference(f) for f in DASS[a]]
   # A partial existing fact is retained as context, never promoted to the full list.
   if uid=='D09-depression-differential' and a=='other_disorders_including_bipolar_psychotic_and_panic':refs=[reference('KR301_3-F10')]
   ps=[];assurance=None
   if mode!='clinical':
    pin=policies[a];ps=[dict(policy_id=a,record_sha256=pin['record_sha256'])]
    record=validate_policy_reference(ROOT,ps[0],uid,unit,a,frozen,moment(at));assurance=record['assurance'];dues.append(moment(record['review_due_at']))
    counts['policy_supported_aspects']+=1
   # Retain earlier exact source coordinates, and recheck them against the live catalog.
   for ref in refs:
    assert reference(ref['fragment_id'])==ref
    dues.append(moment(byid[ref['fragment_id']][0]['review_due_at']))
   gap=(mode!='policy' and not refs)
   reason=previous.get('reason') if gap else None
   if c['domain']=='D12' and a=='age_boundary':gap=True;reason='Возраст русской валидационной выборки неизвестен; FAQ14+ и политика18–120 не подтверждают возрастную применимость точной русской формы.'
   if uid=='D09-depression-differential' and a=='other_disorders_including_bipolar_psychotic_and_panic':gap=True;reason='F10 подтверждает только БАР. Психотическое/паническое расстройства как полный замороженный перечень этой КР не подтверждены.'
   if gap:
    counts['unresolved_clinical_aspects']+=1;gaps.append(a)
   elif mode!='policy':counts['source_supported_aspects']+=1
   status='gap_with_context' if gap and refs else 'gap' if gap else 'policy_evidence_reviewed' if mode=='policy' else 'mixed_evidence_reviewed' if mode=='mixed' else 'source_context_reviewed' if c['requires_dossiers'] else 'source_evidence_reviewed'
   aspects[a]=dict(mode=mode,status=status,source_references=refs,policy_references=ps,policy_assurance=assurance,reason=reason,prior_status=previous['status'])
   review_aspects[a]=dict(source_references=refs,policy_references=ps)
  # Only these independently reviewed non-dossier bundles have a sufficient verdict.
  sufficient=not c['requires_dossiers'] and not gaps
  explanation=REVIEW.get(suffix,'Только контекст имеющихся КР/политик. Точный лекарственный комплект и все разделы досье не приняты; тематическая ссылка не закрывает индивидуальную справку.')
  row=dict(unit_id=uid,requirement_sha256=digest(c),direction=c['direction'],requires_dossiers=c['requires_dossiers'],verdict='sufficient_reference_bundle' if sufficient else 'gap',aspects=aspects,unresolved_aspects=gaps,content_review=explanation,limitations=['Техническая достаточность справочных оснований; не независимый клинический допуск, не персональная применимость, не работающий RAG.','Числовой возраст КР/русской выборки не выведен; лекарственные аспекты не закрыты источниками DASS.'])
  if c['requires_dossiers']:row['dossier_prerequisite']='NOT_READY; все9досье/90разделов остаются обязательными J02C; без обхода зависимости B.'
  if sufficient:
   assert suffix in REVIEW and dues
   review=dict(schema_version=2,scope_version=frozen['scope_version'],unit_id=uid,requirement_sha256=digest(c),verdict='sufficient',reviewer='Codex main agent, technical content review; not an independent clinician',origin='HAC_TECHNICAL_REFERENCE_CONTENT_REVIEW_NOT_CLINICAL_APPROVAL',sufficiency_explanation=explanation+' Популяция и стадия ограничены точным frozen-вопросом; источниковый/правовой допуск взят из B01/B02 без продления сроков. '+row['limitations'][0],checked_at=at,review_due_at=min(dues).isoformat(),aspects=review_aspects)
   path='data/retrieval/coverage-reviews/S17J02B03A/'+uid+'.json';save(path,review)
   pointer=dict(review_path=path,review_sha256=sha((ROOT/path).read_bytes()))
   validate_review(ROOT,uid,unit,pointer,catalog,frozen,moment(at))
   evidence['units'][uid]=pointer;row['review_pointer']=pointer;counts['sufficient_cells']+=1
  cells.append(row)
 assert counts['total_aspects']==224 and counts['sufficient_cells']==17,counts
 save('data/retrieval/coverage-evidence.json',evidence)
 gate=assess(ROOT,snapshot,at)
 assert gate['status']=='NOT_READY' and not gate['errors'] and gate['counts']['cells']['complete']==17 and len(gate['gaps'])==131,gate
 save('evidence/S17J02B03A/core-coverage.json',dict(schema_version=2,slice='S17J02B03A',scope_version=frozen['scope_version'],scope_sha256=digest(frozen),status='PARTIAL_CORE_NOT_PARENT_ACCEPTANCE',checked_at=at,counts=counts,cells=cells,independent_clinical_validation=False,refusal_behavior_tested=False,dossier_sections_complete=0,dossier_sections_required=90))
 save('evidence/S17J02B03A/coverage-readiness.json',gate)
 save('evidence/S17J02B03A/corpus-manifest.json',manifest)
 save('evidence/S17J02B03A/import.json',dict(snapshot=str(snapshot.relative_to(ROOT)),corpus_version=manifest['corpus_version'],admitted_sources=9,indexable_cards=len(catalog),new_sources=0,new_cards=0,sources_reverified_or_extended=False))
 print(json.dumps(counts,ensure_ascii=False));print('COVERAGE-1 NOT_READY:17/58 cells,0/90 sections,0/9 dossiers;131gaps')
if __name__=='__main__':main()
