"""Pin documented HAC constraints separately from medical source assertions."""
import json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from apps.compass.retrieval_corpus import sha,digest
from apps.compass.retrieval_policies import REGISTRY,RECORD_PREFIX,SPEC,POLICY_IDS,aspect_mode
from tools.check_retrieval_coverage import scope
E='evidence/S17J02B02/'
STATEMENTS={
'confirmed_course_and_dates':'Для персональной лекарственной справки нужны подтверждённый врачом курс и его даты. Поиск не достраивает их из предположений.',
'unknown_or_conflicting_context':'Неизвестные или противоречивые сведения о контексте не выбираются автоматически; требуется уточнение.',
'missing_data':'Пустое поле не означает отсутствия симптома или риска. Для пропущенного ответа нельзя подставлять ноль.',
'comparable_measurements':'Сопоставляют только измерения одной точной формы, версии, ключа и источника. Разные серии не объединяются автоматически.',
'time_overlap':'Пересекающиеся периоды самоотчётов ограничивают сравнение. Близкие даты заполнения не доказывают независимость наблюдений.',
'patient_and_physician_provenance':'Автор, роль, дата наблюдения и время получения сведений различаются и сохраняются отдельно.',
'no_automatic_failure_threshold':'Недостаточный эффект не определяется программным порогом DASS или таймером без врачебного контекста.',
'no_DASS_threshold':'Сумма DASS не устанавливает ремиссию и не задаёт порог изменения терапии.',
'course_and_dates':'Возвращение жалоб сопоставляют с датами курса и прежними наблюдениями, не восстанавливая отсутствующие даты.',
'absence_not_exclusion':'Отсутствие сообщения о нежелательном явлении не признаётся доказательством его отсутствия.',
'no_causality_or_severity_inference':'Совпадение жалобы и приёма по времени не становится автоматической оценкой причинности или тяжести.',
'no_class_substitution':'Сведения о классе лекарств не заменяют инструкцию точной формы, дозировки и регистрационного удостоверения.',
'unknown_requires_review':'Неизвестная применимость в особой группе требует врачебной проверки; отсутствие сведений не даёт разрешения.',
'not_comprehensive_pair_checker':'Справка не обещает полной проверки любых лекарственных сочетаний.',
'unknown_co_medication':'Неизвестные сопутствующие лекарства не заменяются утверждением, что пациент ничего не принимает.',
'coverage_limits':'Область справки явно ограничена проверенными источниками и точными лекарственными идентичностями.',
'no_absence_of_risk_claim':'Пустой результат поиска взаимодействий не означает отсутствия риска.',
'explicit_patient_record':'Выполнение или пропуск приёма фиксируется явной записью, а не выводится из молчания.',
'course_linkage':'Запись о приёме относится к конкретному подтверждённому курсу, без автоматического переноса на другой курс.',
'reasons_and_dates':'Сохраняются дата события и сообщённая причина пропуска; неизвестное не дописывается.',
'missing_not_missed':'Отсутствие записи не равно пропущенному приёму.',
'no_compensating_dose_from_search':'Поиск не рассчитывает компенсирующую дозу после пропуска.',
'physician_confirmation':'Существующие клинические действия требуют отдельного подтверждения врача. Текст в корпусе не создаёт назначения или отмены.',
'no_automatic_taper':'Поиск не формирует персональную схему снижения дозы или прекращения курса.',
'independent_safety_path':'Путь реагирования на критические сведения проектируется независимо от поиска. Эта запись не доказывает реализацию будущего RAG-пути.',
'no_urgency_from_RAG':'RAG не определяет срочность клинической ситуации.',
'search_must_not_delay_existing_response':'Ожидание результата поиска не должно задерживать действующее реагирование на критические сведения; проверка будущей интеграции остаётся отдельной.',
'missing_not_no_risk':'Нет подходящего основания — нет ответа из корпуса, а не вывод об отсутствии риска.',
'explicit_unavailability':'Недоступность или отсутствие допустимого основания показывается явно.',
'no_model_or_network_fallback':'Отсутствующий ответ не достраивается из памяти модели или произвольного сетевого источника.',
'no_diagnosis_from_question':'Формулировка вопроса пациента сама по себе не подтверждает диагноз.',
'uncertainty':'Неопределённость и пробелы сохраняются явно, без замены наиболее вероятным вариантом.',
'no_cross_diagnosis_transfer':'Основание для одного диагноза не переносится автоматически на другое расстройство.',
'physician_confirmed_plan':'Существующее изменение лечебного плана требует подтверждения врача. Психотерапевтический вариант в справке сам по себе план не создаёт.',
'no_unapproved_protocol':'Перечень немедикаментозных подходов не превращается в автоматически назначенный психологический протокол.',
'no_invented_window':'Источник сроков и этап наблюдения должны быть указаны; универсальное окно осмотра не выдумывается.',
'withdraw_affected_material':'Отзыв прав, срока или источника исключает затронутый материал из допустимой выдачи до повторной проверки.',
'complete_same_form':'Для сравнения результатов нужны завершённые измерения одной точной формы; пропуски не заполняются предположениями.',
'overlapping_periods':'Пересечение недельных периодов DASS обозначает ограничение сравнения, а не самостоятельные независимые изменения.',
'patient_no_computed_scores':'В существующем сервисе пациенту выдаётся квитанция без вычисленных сумм DASS и автоматической интерпретации; результаты доступны врачу.',
'no_diagnosis_from_score':'Сервис не устанавливает диагноз из балла шкалы. Фактическая недиагностичность DASS требует отдельного первичного источника.',
 'three_separate_scores_for_physician':'Существующий сервис показывает врачу три отдельные суммы DASS. Свойства трёх шкал подтверждаются отдельно первоисточником инструмента.',
'no_diagnostic_or_medication_threshold':'В HAC нет диагностического или лекарственного порога из DASS. Свойства измерения подтверждаются отдельно FAQ, а запрет назначения — политикой сервиса.',
'age_boundary':'Политика синтетического демо HAC: сверенный возраст18–120. Это собственная граница проекта, не возраст русской валидационной выборки; общую рекомендациюFAQ нельзя подменять ею.',
'text_rights_separately':'Правила использования точной формы, публикации валидации и самостоятельных справочных карточек проверяются раздельно. Разрешение на бланк не лицензирует всю статью или полный корпус.'}
assert set(STATEMENTS)==set(POLICY_IDS)
CONTROLS={
'patient_no_computed_scores':('apps/compass/assessments.py','def history(', 'apps/tests/test_assessments.py','test_full_patient_submission_doctor_results_and_patient_receipt_only'),
 'three_separate_scores_for_physician':('apps/compass/assessments.py','def score_answers(', 'apps/tests/test_assessments.py','test_full_patient_submission_doctor_results_and_patient_receipt_only'),
'physician_confirmation':('apps/compass/decisions.py','def confirm(', 'apps/tests/test_decisions.py','test_five_actions_draft_separate_review_and_patient_projection'),
'physician_confirmed_plan':('apps/compass/decisions.py','def confirm(', 'apps/tests/test_decisions.py','test_five_actions_draft_separate_review_and_patient_projection')}

def write(path,obj):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def build():
 frozen,matrix,meds,units=scope(ROOT)
 checked=datetime.now(timezone.utc);due=checked+timedelta(days=1)
 logpath=E+'policy-control-tests.log';log=(ROOT/logpath).read_text();assert log.endswith('OK\n') and 'Ran 2 tests' in log
 runpath=E+'policy-control-tests.json'
 write(runpath,dict(status='PASS',exit_code=0,checked_at=datetime.fromtimestamp((ROOT/logpath).stat().st_mtime,timezone.utc).isoformat(),command='PYTHONPATH=apps/tests .venv/bin/python -m unittest apps.tests.test_assessments.AssessmentsTests.test_full_patient_submission_doctor_results_and_patient_receipt_only apps.tests.test_decisions.DecisionTests.test_five_actions_draft_separate_review_and_patient_projection -v',
    tests=sorted({c[2]+'::'+c[3] for c in CONTROLS.values()}),log_path=logpath,log_sha256=sha((ROOT/logpath).read_bytes()),limitation='Only two existing controls tested; not RAG integration, independent clinical validation, or overall coverage readiness.'))
 text='''# Отдельные доказательства ограничений HAC

Это собственные ограничения проекта, а не рекомендации Минздрава и не результаты психометрической валидации.
Каждое утверждение связано с неизменённой ячейкой/аспектом замороженной матрицы.
Контрольная сумма этого документа защищает точную редакцию; изменение требует повторной проверки записей.

`documented_constraint` означает закреплённое ограничение. Оно не доказывает работающий программный барьер.
`tested_existing_control` относится только к указанному существующему действию сервиса и фактически выполненному тесту.
Новый RAG, его отказы, критический путь и клинические правила этим не активируются и не принимаются.
Наличие политики не заменяет клинический первоисточник, инструкцию лекарства, неизвестный возраст или доказательство прав.
Смешанный аспект требует обоих видов доказательств. Политики не индексируются как медицинские карточки.

Исходные документы: docs/architecture/retrieval-coverage-contract.md,
docs/clinical/followup-recommendation-spec.md, docs/architecture/assessments.md,
docs/product/psychiatrist-followup-plan.md. Их сведения сохранены; этот реестр отдельно закрепляет происхождение.

'''
 for pid in sorted(POLICY_IDS):
  text+='## policy:'+pid+'\n\n'+STATEMENTS[pid]+'\n\n'
  text+=('Проверен существующий контроль, указанный в записи. Это не проверка будущей интеграции RAG.\n\n' if pid in CONTROLS else 'Статус: документированное ограничение; поведение будущего RAG здесь не проверялось.\n\n')
 (ROOT/SPEC).write_text(text.rstrip()+'\n')
 pins=[];counts={'policies':len(POLICY_IDS),'bindings':0,'tested_existing_controls':len(CONTROLS),'documented_constraints':len(POLICY_IDS)-len(CONTROLS)}
 for pid in sorted(POLICY_IDS):
  bindings=[dict(unit_id=uid,aspect=pid,requirement_sha256=digest(unit['requirement'])) for uid,unit in units.items() if pid in unit['aspects'] and aspect_mode(unit,pid)!='clinical']
  assert bindings,pid;counts['bindings']+=len(bindings)
  support=[dict(path=SPEC,sha256=sha((ROOT/SPEC).read_bytes()),locator='## policy:'+pid)];verification=None
  if pid in CONTROLS:
   code,locator,test,name=CONTROLS[pid]
   support.append(dict(path=code,sha256=sha((ROOT/code).read_bytes()),locator=locator))
   verification=dict(test_path=test,test_sha256=sha((ROOT/test).read_bytes()),test_name=name,run_path=runpath,run_sha256=sha((ROOT/runpath).read_bytes()))
  record=dict(schema_version=1,policy_id=pid,scope_version=frozen['scope_version'],statement=STATEMENTS[pid],origin='HAC_PROJECT_POLICY',reviewer='Codex main agent: source/code/test inspection; no independent clinical approval',checked_at=checked.isoformat(),review_due_at=due.isoformat(),assurance='tested_existing_control' if pid in CONTROLS else 'documented_constraint',bindings=bindings,support=support,verification=verification)
  path=RECORD_PREFIX+pid+'.json';write(path,record)
  pins.append(dict(policy_id=pid,record_path=path,record_sha256=sha((ROOT/path).read_bytes()),status='approved'))
 write(REGISTRY,dict(schema_version=1,scope_version=frozen['scope_version'],policies=pins));write(E+'policy-summary.json',counts)
 print(json.dumps(counts,ensure_ascii=False))
if __name__=='__main__':build()
