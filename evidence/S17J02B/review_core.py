"""Document each frozen aspect without turning policy or dossier gaps into sources."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import digest,sha
from tools.check_retrieval_coverage import scope

def write(path,obj):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
# Values explicitly select clinical facts for each direction. Empty = no KR evidence.
MAP={
'context':{'diagnosis_and_population':([6],[6]),'exclusions':([9,10],[8,9,10])},
'identity':{},
'symptoms':{'symptoms':([5,8],[7]),'functioning':([7,16,20],[20]),'observation_period':([11],[7])},
'trajectory':{'no_diagnosis_from_score':([8],[12,15])},
'effect':{'course_duration_context':([12],[16]),'effect_and_tolerability':([5,11],[3,14]),'adherence':([5,11],[5,17])},
'no_effect':{'adequacy_of_course':([13],[16]),'adherence_and_adverse_events':([5,13],[5,14,17]),'alternative_causes':([9,14],[8,10]),'physician_review':([3,13],[16])},
'remission':{'source_definition':([15],[15]),'maintenance_context':([16,17],[4,17]),'recurrence_monitoring':([17],[5,17])},
'relapse':{'recurrence_context':([17],[5,17]),'functioning':([7,16],[20])},
'adverse':{'documented_adverse_reactions':([22],[14])},
 'tolerability':{'tolerability':([4,5,22],[3,14]),'effect':([3,5],[3,15]),'confounders':([9,14,21],[8,10,22]),'physician_review':([3,4],[3,13])},
'contraindications':{'precautions':([21,22],[13,22]),'population':([6],[6])},
'special_groups':{},'interactions':{},'uncertain_combination':{},
'adherence':{},'missed_dose':{},
'discontinuation':{'documented_discontinuation':([18],[18]),'withdrawal_if_documented':([18],[18])},
'critical':{'critical_information_source':([2],[11])},'no_answer':{},
'differential':{'other_disorders_including_bipolar_psychotic_and_panic':([],[8,9,10]),'somatic_causes':([9,21],[10,22]),'physician_assessment':([1,9,10],[1,8,9])},
'substances':{'substances_and_alcohol':([9],[8,10,21]),'coexisting_conditions':([9,21],[8,10])},
'psychotherapy':{'documented_options':([19],[19]),'indications_and_limits':([19,20],[13,19])},
'non_medical_followup':{'followup_measures':([19,20],[20,21]),'functioning':([7,16,20],[20]),'evidence_limits':([19],[19])},
'review':{'review_timing_with_context':([11],[3,17]),'course_stage':([11,12],[17]),'effect_tolerability_adherence':([5,11],[5,14,17])},
'monitoring':{'clinical_monitoring':([11,21,22],[3,14,22]),'laboratory_if_documented':([22],[]),'source_version_and_context':([6,11],[6,14])},
'updates':{},'scale_identity':{},'scale_interpretation':{},'FU08':{}
}
POLICY={
'missing_data':'docs/product/psychiatrist-followup-plan.md',
'comparable_measurements':'docs/architecture/assessments.md','time_overlap':'docs/clinical/followup-recommendation-spec.md',
'patient_and_physician_provenance':'docs/clinical/followup-recommendation-spec.md',
'no_automatic_failure_threshold':'docs/clinical/followup-recommendation-spec.md',
'no_DASS_threshold':'docs/architecture/assessments.md','no_causality_or_severity_inference':'docs/clinical/followup-recommendation-spec.md',
'absence_not_exclusion':'docs/clinical/followup-recommendation-spec.md',
'no_class_substitution':'docs/architecture/retrieval-coverage-contract.md',
'unknown_requires_review':'docs/architecture/retrieval-coverage-contract.md',
'not_comprehensive_pair_checker':'docs/architecture/retrieval-coverage-contract.md',
'unknown_co_medication':'docs/architecture/retrieval-coverage-contract.md','coverage_limits':'docs/architecture/retrieval-coverage-contract.md',
'no_absence_of_risk_claim':'docs/architecture/retrieval-coverage-contract.md',
'unknown_or_conflicting_context':'docs/architecture/retrieval-coverage-contract.md',
'confirmed_course_and_dates':'docs/clinical/followup-recommendation-spec.md',
'course_and_dates':'docs/clinical/followup-recommendation-spec.md',
'explicit_patient_record':'docs/product/psychiatrist-followup-plan.md',
'course_linkage':'docs/clinical/followup-recommendation-spec.md','reasons_and_dates':'docs/product/psychiatrist-followup-plan.md',
'missing_not_missed':'docs/product/psychiatrist-followup-plan.md',
'no_compensating_dose_from_search':'docs/architecture/retrieval-coverage-contract.md',
'physician_confirmation':'docs/clinical/followup-recommendation-spec.md','no_automatic_taper':'docs/architecture/retrieval-coverage-contract.md',
'independent_safety_path':'docs/architecture/rag-corpus-strategy.md','no_urgency_from_RAG':'docs/architecture/rag-corpus-strategy.md',
'search_must_not_delay_existing_response':'docs/architecture/rag-corpus-strategy.md',
'missing_not_no_risk':'docs/architecture/retrieval-coverage-contract.md',
'explicit_unavailability':'docs/architecture/retrieval-reference-contract.md','no_model_or_network_fallback':'docs/architecture/rag-corpus-strategy.md',
'no_diagnosis_from_question':'docs/architecture/retrieval-coverage-contract.md',
'uncertainty':'docs/architecture/retrieval-coverage-contract.md','no_cross_diagnosis_transfer':'docs/architecture/retrieval-coverage-contract.md',
'physician_confirmed_plan':'docs/clinical/followup-recommendation-spec.md','no_unapproved_protocol':'docs/clinical/followup-recommendation-spec.md',
'no_invented_window':'docs/clinical/followup-recommendation-spec.md',
'withdraw_affected_material':'docs/architecture/retrieval-coverage-contract.md'
}
REASONS={
'exact_age_boundary':'Официальный API подтверждает только adult=true/child=false. Числовой рубеж ровно18 не установлен.',
'exact_Russian_form_and_key':'DASS42-RU-FG-2024-demo-v1 сохранена в S07, но отдельный первичный источник/ключ не допущен в RAG.',
'validation_population':'Цепочка S07/статья2025 есть, но точный первичный источник и его SHA не допущены в RAG.',
'age_boundary':'FAQ и пределы HAC/неизвестный возраст русской выборки различаются; допустимой DASS-записи RAG нет.',
'recall_period':'Период DASS — прошлая неделя; источник инструмента не допущен в RAG.',
 'text_rights_separately':'Права формы S07 и самостоятельных метаданных не дают автоматического допуска статьи/инструмента в RAG.'
}

def build():
 frozen,matrix,meds,units=scope(ROOT)
 bundles={d:json.loads((ROOT/f'data/retrieval/packages/J02B/{d}.json').read_text()) for d in ['KR301_3','KR457_3']}
 registry=json.loads((ROOT/'data/retrieval/packages/J02B/registry.json').read_text())
 sources={i['document_id']:i for i in registry['sources']}
 counts={'required_cells':len(matrix['cells']),'source_supported_aspects':0,'project_policy_only_aspects':0,'uncovered_aspects':0,'total_aspects':0,'sufficient_cells':0}
 cells=[]
 for c in matrix['cells']:
  doc='KR301_3' if c['direction']=='depression' else 'KR457_3';di=0 if doc=='KR301_3' else 1
  cards={f['fragment_id']:f for f in bundles[doc]['fragments']};item=sources[doc]
  suffix=c['id'].split('-',2)[-1];aspects={}
  for aspect in c['required_aspects']:
   counts['total_aspects']+=1
   ids=MAP.get(suffix,{}).get(aspect,([],[]))[di]
   refs=[]
   for num in ids:
    f=cards[f'{doc}-F{num:02}']
    refs.append(dict(document_id=doc,fragment_id=f['fragment_id'],page=f['page'],section=f['section'],source_version=item['source_version'],source_sha256=item['sha256'],artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(f)))
   if refs:
    counts['source_supported_aspects']+=1
    aspects[aspect]={'status':'clinical_context_only' if c['requires_dossiers'] else 'source_support_reviewed','references':refs,'limitation':'Только конкретный клинический контекст/явно помеченная граница HAC; не достаточность персональной справки и не медицинский эталон.'}
   elif aspect in POLICY:
    counts['project_policy_only_aspects']+=1
    path=POLICY[aspect];aspects[aspect]={'status':'project_policy_only','references':[],'policy_path':path,'policy_sha256':sha((ROOT/path).read_bytes()),'limitation':'Собственное ограничение HAC, не утверждение КР и не допущенный медицинский источник; формальное покрытие этим не закрыто.'}
   else:
    counts['uncovered_aspects']+=1
    reason=REASONS.get(aspect)
    if not reason:
     if suffix.startswith('scale_'):reason='Требуется отдельный допуск точных DASS-источников и отделённая проверка политики HAC; КР это не подтверждает.'
     elif c['requires_dossiers']:reason='Нет достаточного точного профессионального досье/основания выбранного лекарства; обязательство J02C сохраняется. Общая КР или отказ не закрывают аспект.'
     else:reason='Нынешние допущенные карточки не образуют достаточный проверенный комплект для этого аспекта.'
    aspects[aspect]={'status':'gap','references':[],'reason':reason}
  cells.append(dict(unit_id=c['id'],requirement_sha256=digest(c),direction=c['direction'],requires_dossiers=c['requires_dossiers'],verdict='gap',aspects=aspects,reason='Полный достаточный комплект не принят: политика не заменяет источниковое основание; частичное покрытие не равно sufficient.'))
 report=dict(schema_version=1,slice='S17J02B',scope_version=frozen['scope_version'],scope_sha256=digest(frozen),status='NOT_READY',independent_clinical_validation=False,counts=counts,cells=cells,remaining_dossier_sections=frozen['required_dossier_sections'],dass_report='evidence/S17J02B/scales-research.md',limitation='Разобраны все58ячеек и всеаспекты. Ссылки — фактический вклад корпуса; ни одна неполная ячейка не помечена достаточной. Frozen scope и COVERAGE-1 не ослаблены.')
 write('evidence/S17J02B/core-coverage.json',report)
 print(json.dumps(counts,ensure_ascii=False))
if __name__=='__main__':build()
