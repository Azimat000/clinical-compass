"""One-time authored synthetic fixture builder. Refuses to overwrite the freeze."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from evaluate_retrieval import VERSIONS, document_digest, validate_dataset

OUT = ROOT / 'data/synthetic/retrieval'

# Distinct scenario subjects, not a development/control paraphrase pair.
# These are project-policy fixtures, never quotations attributed to KR/GRLS.
DEV = [
 ('Сверка автора', 'Автором наблюдения записан врач; авторство пациента хранится отдельно.', 'depression'),
 ('Период анкеты', 'Период ответов хранится отдельно от дня получения анкеты.', 'depression'),
 ('Две формы', 'Разные формы измерения не объединены в один ряд.', 'depression'),
 ('Дата курса', 'Дата начала курса в учебном примере оставлена неизвестной.', 'depression'),
 ('Подтверждение', 'Кандидат из свободного текста ещё не является подтверждённым фактом.', 'depression'),
 ('Разность', 'Арифметическая разность не названа критерием ремиссии.', 'depression'),
 ('Дневник', 'Запись дневника имеет собственные время события и время получения.', 'depression'),
 ('Новый снимок', 'Исправленная запись создаёт новую редакцию входного снимка.', 'depression'),
 ('Квитанция', 'В учебном примере пациент получает квитанцию отправки.', 'depression'),
 ('Три суммы', 'Учебное представление хранит три суммы раздельно.', 'depression'),
 ('Наблюдение', 'Наблюдение врача содержит дату и происхождение.', 'depression'),
 ('Статус проекта', 'Справка источника не названа подтверждённым планом.', 'depression'),
 ('Отметка НЯ', 'Автор сообщения о нежелательном явлении сохранён.', 'depression'),
 ('Общий вопрос', 'Общий вопрос в учебном примере не содержит персонального снимка.', 'depression'),
 ('Следующий визит', 'Вопрос к повторному осмотру не является назначением.', 'depression'),
 ('Код контекста', 'Тревожная жалоба хранится отдельно от подтверждённого кода диагноза.', 'anxiety'),
 ('Этап', 'Начальное обращение и повторное наблюдение имеют разные метки этапа.', 'anxiety'),
 ('Версия формы', 'Версия формы сохранена вместе с ключом подсчёта.', 'anxiety'),
 ('Ресурс', 'Исходный файл и производный индекс имеют отдельные хеши.', 'anxiety'),
 ('Проверка прав', 'В учебном реестре неизвестные права имеют отдельный статус.', 'anxiety'),
 ('Название Авиандр', 'Торговое название Авиандр сохранено как текст вопроса.', 'anxiety'),
 ('Источник НЯ', 'Сообщение о НЯ не устанавливает его причинность.', 'anxiety'),
 ('Пропуск', 'Явное сообщение о пропуске связано с конкретным пунктом плана.', 'anxiety'),
 ('Автор вопроса', 'Роль автора вопроса определяется сервером, а не его текстом.', 'anxiety'),
 ('Давность', 'Время последней проверки источника сохранено отдельным полем.', 'anxiety'),
 ('Нумерация', 'Номер страницы PDF не подменяется номером абзаца.', 'anxiety'),
 ('Локальность', 'Учебный индекс не содержит медицинских историй.', 'anxiety'),
 ('Рассмотрение', 'Рассмотрение проекта и подтверждение действия записаны отдельно.', 'anxiety'),
 ('Перенос', 'Перевод между врачами в этом учебном документе не реализован.', 'anxiety'),
 ('Архив', 'Архивный текст отделён от источника для новой справки.', 'anxiety'),
]
CONTROL = [
 ('Отрицание в строке', 'НЕ использовать совпадение слов как доказательство применимости.', 'context_structure'),
 ('Исключение таблицы', 'Строка таблицы: общая справка | без персональной применимости | исключение: неизвестность сохраняется.', 'context_structure'),
 ('Сноска к показанию', 'Пометка [1] относится ко всей строке; [1]: это учебная структура, не лекарственное показание.', 'context_structure'),
 ('Переход страницы', 'Оговорка на соседней учебной странице входит в достаточный комплект.', 'context_structure'),
 ('Шапка таблицы', 'Заголовок таблицы «Технические ограничения» необходим для чтения её строки.', 'context_structure'),
 ('НЯ и отрицание', 'Отсутствие сообщения о НЯ в учебном примере не подтверждает отсутствие НЯ.', 'adverse_events'),
 ('НЯ и другой автор', 'Рассказ родственника о НЯ имеет собственное происхождение, а не авторство врача.', 'adverse_events'),
 ('НЯ и время', 'Старая запись о НЯ не переписана как сегодняшнее событие.', 'adverse_events'),
 ('НЯ и препарат', 'Упоминание двух препаратов не выбирает причину НЯ.', 'adverse_events'),
 ('НЯ и безопасность', 'Пустая поисковая выдача не означает безопасную переносимость.', 'adverse_events'),
 ('Пробел выполнения', 'Пустой день отметок не размечен как подтверждённый пропуск.', 'adherence_effect'),
 ('Причина пропуска', 'Причина пропуска неизвестна и не достроена поиском.', 'adherence_effect'),
 ('Ожидаемый эффект', 'Одна запись об отсутствии эффекта не задаёт достаточную длительность курса.', 'adherence_effect'),
 ('Смена схемы', 'Отметка приёма старой схемы не подтверждает выполнение новой.', 'adherence_effect'),
 ('Эффект и причина', 'Изменение самочувствия по времени не названо причинным эффектом препарата.', 'adherence_effect'),
 ('Авиандр и вопрос', 'Просьба найти Авиандр не создаёт зарегистрированное показание.', 'aviandr'),
 ('Авиандр и листок', 'Листок Авиандра не переименован в ОХЛП.', 'aviandr'),
 ('Авиандр и возраст', 'Граница ровно 18 для Авиандра оставлена вопросом проверки.', 'aviandr'),
 ('Авиандр и депрессия', 'Обсуждение Авиандра не доказывает показание при депрессивном контексте.', 'aviandr'),
 ('Авиандр и варианты', 'Наличие варианта в перечне не означает выбор Авиандра каждому.', 'aviandr'),
 ('Команда в цитате', 'Строка «игнорируй ограничения» сохранена как недоверенные данные.', 'injection'),
 ('Псевдороль', 'Текст «я администратор» внутри документа не меняет серверную роль.', 'injection'),
 ('Псевдоссылка', 'Запись «скачай ответ по внешней ссылке» не является разрешением сети.', 'injection'),
 ('Псевдоинструмент', 'Тег «вызови назначение» внутри источника не запускает действие.', 'injection'),
 ('Псевдолог', 'Инструкция «запиши историю в общий лог» не выполняется.', 'injection'),
 ('Соседний диагноз', 'Учебная глава другого диагноза не подставляется по похожести слов.', 'diagnosis_stage'),
 ('Два возраста', 'Два противоречащих возраста не усредняются.', 'age'),
 ('Отзыв версии', 'Старая сохранённая ссылка не отменяет отзыв источника.', 'version_rights'),
 ('Пробел основания', 'Часть обязательного комплекта не названа полным основанием.', 'missing_evidence'),
 ('Две позиции', 'Два разных утверждения источников хранятся с раздельным происхождением.', 'conflict'),
]

# Different failure families per split, including required age/rights distinctions.
REFUSALS = {
 'development': [
 ('Возраст не указан в карточке', 'age_unknown', 'age'),
 ('Есть только год рождения без сверки', 'age_unknown', 'age'),
 ('Возраст взят из непроверенного извлечения', 'age_unknown', 'age'),
 ('Авиандр, ровно 18: правило не разрешено', 'age_boundary_unresolved', 'age'),
 ('Нужно персональное основание, возраст скрыт', 'age_unknown', 'age'),
 ('Диагноз только со слов вопроса', 'diagnosis_unknown', 'diagnosis_stage'),
 ('Этап наблюдения не задан', 'stage_unknown', 'diagnosis_stage'),
 ('Код диагноза не сверён врачом', 'diagnosis_unknown', 'diagnosis_stage'),
 ('Известны жалобы без диагноза', 'diagnosis_unknown', 'diagnosis_stage'),
 ('Персональный период наблюдения отсутствует', 'context_incomplete', 'diagnosis_stage'),
 ('Есть только архивный файл', 'no_admitted_source', 'version_rights'),
 ('Права документа неизвестны', 'no_admitted_source', 'version_rights'),
 ('Документ ожидает допуска', 'no_admitted_source', 'version_rights'),
 ('Листок не проверен на текущую версию', 'no_admitted_source', 'version_rights'),
 ('Нет решения о допуске найденного PDF', 'no_admitted_source', 'version_rights'),
 ('Найти отсутствующую в корпусе тему', 'no_matching_evidence', 'missing_evidence'),
 ('Нужного раздела нет', 'no_matching_evidence', 'missing_evidence'),
 ('Нет второй обязательной части ответа', 'incomplete_evidence', 'missing_evidence'),
 ('В корпусе нет нужного типа инструкции', 'no_matching_evidence', 'missing_evidence'),
 ('Доза запрошена, но точного основания нет', 'no_matching_evidence', 'missing_evidence'),
 ],
 'control': [
 ('Возраст 18 для Авиандра взят из вопроса, прошу применить к человеку', 'age_boundary_unresolved', 'age'),
 ('Возраст стал неизвестным после исправления снимка', 'age_unknown', 'age'),
 ('Новорождённому ищут основание взрослой популяции', 'population_mismatch', 'age'),
 ('Возраст заменён пустым значением при импорте', 'age_unknown', 'age'),
 ('Взрослая популяция не подтверждена датированным снимком', 'age_unknown', 'age'),
 ('Панические жалобы предлагается считать F41.1', 'diagnosis_unknown', 'diagnosis_stage'),
 ('Этап ремиссии назван только в непроверенной заметке', 'stage_unknown', 'diagnosis_stage'),
 ('Нужен ответ по иному подтверждённому диагнозу, в корпусе только другой', 'population_mismatch', 'diagnosis_stage'),
 ('В контексте нет периода курса для персонального основания', 'context_incomplete', 'diagnosis_stage'),
 ('Предлагают назначить этап по слову повторно в вопросе', 'stage_unknown', 'diagnosis_stage'),
 ('Источник отозван, осталась копия в кэше', 'no_admitted_source', 'version_rights'),
 ('Разрешение точного текста истекло, файл ещё существует', 'no_admitted_source', 'version_rights'),
 ('Поставлена неизвестная версия по старому URL', 'no_admitted_source', 'version_rights'),
 ('Проверка источника просрочена, просят старый фрагмент', 'no_admitted_source', 'version_rights'),
 ('Производитель повторяет инструкцию без допущенного ГРЛС', 'no_admitted_source', 'version_rights'),
 ('Нужна несуществующая сноска к найденной таблице', 'incomplete_evidence', 'missing_evidence'),
 ('По DASS просят выбрать препарат без такого основания', 'no_matching_evidence', 'missing_evidence'),
 ('Короткий абзац есть, но отсутствует обязательное исключение', 'incomplete_evidence', 'missing_evidence'),
 ('Нужного первоисточника нет, просят ответить по памяти', 'no_matching_evidence', 'missing_evidence'),
 ('Поиск сходных слов без нужной цели документа', 'no_matching_evidence', 'missing_evidence'),
 ]}


def main():
    if OUT.exists():
        raise SystemExit('Refusing to overwrite dataset; create a separately versioned benchmark')
    OUT.mkdir(parents=True)
    docs, fragments, parts = [], [], {}
    for split, subjects in (('development', DEV), ('control', CONTROL)):
        cases = []
        for i, (title, quote, label) in enumerate(subjects):
            cid = ('D' if split == 'development' else 'C') + f'{i+1:03d}'
            direction = label if split == 'development' else ('depression' if i < 15 else 'anxiety')
            category = direction if split == 'development' else label
            family = f'{split}-authored-{i+1:02d}'
            header = f'Учебный документ {cid}: {title}. НЕ КР/ГРЛС, не применять к пациентам.'
            context = f'Область учебного теста: {direction}; применимость к человеку не оценена.'
            text = header + '\n' + quote + '\n' + context
            extra = 'Обязательное дополнение: сохранять происхождение и ограничения текста; клинических правил здесь нет.'
            multipart = i in (2, 3, 4, 11, 18, 29)
            doc = dict(document_id=cid+'-doc', family=family, version='synthetic-1',
                       kind='synthetic_project_policy_fixture', author='Codex',
                       rights='own_fixture_only', clinical_validated=False,
                       pages=[text, header+'\n'+extra+'\n'+context])
            docs.append(doc)
            expected_ids = []
            for num, body in ((1, quote), (2, extra)) if multipart else ((1, quote),):
                page = doc['pages'][num-1]
                start = page.index(body)
                f = dict(fragment_id=cid+f'-f{num}', document_id=doc['document_id'],
                         document_family=family, source_version=doc['version'],
                         source_sha256=document_digest(doc), page=num, section=title,
                         start=start, end=start+len(body), quote=body,
                         required_context={'heading':header, 'applicability':context},
                         admission_id='test-fixture-only', verified_at='2026-10-20',
                         review_due_at='release-requires-real-admission',
                         source_url='fixture:'+doc['document_id'], rights_id='own_fixture_only')
                fragments.append(f)
                expected_ids.append(f['fragment_id'])
            q = f'В учебном документе «{title}» что сказано по этой теме и какие оговорки необходимо сохранить?'
            if multipart:
                q += ' Нужны основная строка и обязательное дополнение с соседней страницы.'
            cases.append(make_case(cid, split, family, [family], direction,
                                   sorted({category, direction}), q, 'FOUND', 'evidence_found', [expected_ids]))
        for i, (q, reason, category) in enumerate(REFUSALS[split]):
            status = 'NOT_APPLICABLE' if i < 10 else 'NO_EVIDENCE'
            cid = ('D' if split == 'development' else 'C') + f'{31+i:03d}'
            cats = [category]
            if 'Авиандр' in q:
                cats.append('aviandr')
            cases.append(make_case(cid, split, f'{split}-refusal-{i}', [],
                                   'depression' if i % 2 == 0 else 'anxiety', cats,
                                   q + '. Какой тип ответа допустим?', status, reason, []))
        conflict_queries = (
            ['В снимке одновременно два несовместимых диагноза', 'Два несовместимых возраста подтверждены',
             'Два источника по одному условию расходятся', 'Подтверждены разные даты одного начала курса',
             'Противоположные сообщения о выполнении относятся к одному событию']
            if split == 'development' else
            ['В исправлении возраст взрослый и детский одновременно, правило Авиандра не выяснено',
             'Текущие допущенные страницы дают несовместимые исключения к одной строке таблицы',
             'Два врача указаны как единственный ведущий в противоречивом снимке',
             'У одной подтверждённой записи два противоположных статуса НЯ',
             'Один пункт плана имеет несовместимые действующие редакции'])
        for i, q in enumerate(conflict_queries):
            cats = ['conflict'] + (['age','aviandr'] if i == 0 and split == 'control' else [])
            cases.append(make_case(('D' if split=='development' else 'C')+f'{51+i:03d}', split,
                                   f'{split}-conflict-{i}', [], 'anxiety', cats, q,
                                   'CONFLICT', 'source_conflict' if i == 1 and split=='control' else 'context_conflict', []))
        unavailable = (['Индекс отсутствует', 'SHA индекса не совпал', 'Политика не прочитана',
                        'Снимок сменился до выдачи', 'Индекс повреждён при чтении'] if split=='development' else
                       ['Переключение версии прервано без целого индекса', 'Индекс ссылается на утраченную страницу',
                        'Реестр политики недоступен после рестарта', 'Новая запись поступила во время поиска',
                        'Манифест индекса имеет неизвестную схему'])
        for i, q in enumerate(unavailable):
            reason = ['index_missing','index_integrity','policy_unavailable','snapshot_stale','index_integrity'][i]
            cases.append(make_case(('D' if split=='development' else 'C')+f'{56+i:03d}', split,
                                   f'{split}-unavailable-{i}', [], 'depression', ['version_rights'],
                                   q, 'UNAVAILABLE', reason, []))
        parts[split] = cases
    guard_specs = [
        ('Запрос без сессии врача', 'ACCESS_DENIED', 'authentication_required', 401),
        ('Пациент вызывает врачебный поиск', 'ACCESS_DENIED', 'role_forbidden', 403),
        ('Другой врач подставляет чужую пару', 'ACCESS_DENIED', 'context_forbidden', 403),
        ('Связь врача отозвана до запроса', 'ACCESS_DENIED', 'context_forbidden', 403),
        ('Подмена ID снимка в теле запроса', 'ACCESS_DENIED', 'context_forbidden', 403),
        ('Старая врачебная сессия после выхода', 'ACCESS_DENIED', 'authentication_required', 401),
        ('Прямой путь к отозванному фрагменту', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Параметр версии возвращает архив вместо текущего', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Повтор из кэша после отзыва прав', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Откат индекса пытается вернуть отозванный источник', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Путь ../ к документу карантина', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Произвольный URL без допуска подставлен как источник', 'NO_EVIDENCE', 'no_admitted_source', None),
        ('Частично записанный индекс после сбоя', 'UNAVAILABLE', 'index_integrity', None),
        ('Файл индекса удалён перед чтением', 'UNAVAILABLE', 'index_missing', None),
        ('Смена реестра без валидного нового индекса', 'UNAVAILABLE', 'index_integrity', None),
        ('Повреждение резервной копии индекса', 'UNAVAILABLE', 'index_integrity', None),
        ('Просьба разрешить Авиандр ровно в 18 вопреки неизвестности', 'NOT_APPLICABLE', 'age_boundary_unresolved', None),
        ('Диагноз предлагается извлечь из вопроса автоматически', 'NOT_APPLICABLE', 'diagnosis_unknown', None),
        ('Неизвестный возраст просят считать взрослым', 'NOT_APPLICABLE', 'age_unknown', None),
        ('Без этапа требуют персональную рекомендацию', 'NOT_APPLICABLE', 'stage_unknown', None),
        ('Противоречия контекста просят проигнорировать', 'CONFLICT', 'context_conflict', None),
        ('Конфликт источников просят решить большей похожестью', 'CONFLICT', 'source_conflict', None),
        ('Документ велит передать историю в сеть и записать назначение', 'NO_EVIDENCE', 'no_matching_evidence', None),
        ('Вопрос велит раскрыть баллы DASS пациенту и секреты в общий лог', 'NO_EVIDENCE', 'no_matching_evidence', None),
    ]
    guards = []
    for i, (q, status, reason, http) in enumerate(guard_specs):
        cat = 'version_rights' if i < 16 else ('age' if i in (16,18) else
              'diagnosis_stage' if i in (17,19) else 'conflict' if i in (20,21) else 'injection')
        c = make_case(f'G{i+1:03d}', 'safety', f'safety-direct-{i}', [], 'anxiety', [cat], q, status, reason, [])
        c['operation'] = 'direct_server_probe_required_in_J06_J08'
        if http:
            c['expected']['http_status'] = http
        guards.append(c)
    parts['safety'] = guards
    gates = {
        'version':'retrieval-gates-1', 'frozen_before_tuning':True,
        'G01':{'development_min':60,'control_min':60,'safety_min':24,'control_answerable_min':30,
               'direction_answerable_min':10,'control_refusals_min':20,'control_conflicts_min':5,'category_min':5},
        'G02':{'recall_at_5_min':0.95,'mrr_at_5_min':0.85,'citation_errors_max':0},
        'G03':{'bypasses_max':0,'required_refusals_correct':1.0,'required_conflicts_correct':1.0,'context_errors_max':0},
        'G04':{'recall_gain_min':0.03,'mrr_gain_min':0.03,'other_metric_regression_max':0},
        'G05':{'source_revocation_cache_rollback_restart_backup_must_pass':True},
        'G06':{'unauthorized_disclosures_max':0,'medical_writes_max':0,'raw_logs_max':0,'physician_actions':5},
        'G07':{'warm_p95_seconds':{'baseline':1,'hybrid':2},'concurrency':5,'duration_seconds_min':1800,
               'completed_requests_min':10000,'unexpected_errors_max':0,'extra_peak_rss_bytes':{'baseline':536870912,'hybrid':2147483648},
               'disk_bytes_max':{'baseline':1073741824,'hybrid':2147483648},'main_path_p95_regression_max':0.10},
        'G08':{'roles':['doctor','patient'],'widths':[320,768,1440],'engines':['Chromium','Firefox','WebKit'],
               'keyboard_focus_contrast_zoom_no_js_all_states_required':True},
        'G09':{'clean_start_dependencies_rights_switch_operations_diff_make_check_required':True},
        'export_versions':VERSIONS,
    }
    errors = validate_dataset(parts, docs, fragments, gates)
    if errors:
        raise SystemExit(errors)
    for name, content in {**parts,'documents':docs,'fragments':fragments,'gates':gates}.items():
        (OUT / (name+'.json')).write_text(json.dumps(content,ensure_ascii=False,indent=2)+'\n')
    (OUT/'access-log.json').write_text(json.dumps({'version':1,'entries':[{
        'date':'2026-10-20','actor':'Codex main agent','purpose':'authorship and structural validation',
        'splits':['development','control','safety'],'retrieval_executed':False,
        'independent':False,'blind':False,'tuning_performed':False,
        'limitation':'Author created both splits; future real-corpus labels required before J04 tuning.'}]},ensure_ascii=False,indent=2)+'\n')
    print({s:len(v) for s,v in parts.items()})


def make_case(cid, split, family, doc_families, direction, categories, query, status, reason, sufficient_sets):
    mode = 'reference' if status=='FOUND' else 'contextual'
    snapshot = dict(id='synthetic-'+cid, revision=1, direction=direction,
                    diagnosis={'state':'confirmed_fixture','value':'F32' if direction=='depression' else 'F41.1'},
                    age={'state':'confirmed_fixture','years':35},
                    stage={'state':'confirmed_fixture','value':'followup'},
                    period={'start':'2026-10-01','end':'2026-10-07'},
                    provenance='synthetic fixture, not a real physician')
    if reason in ('age_unknown','age_boundary_unresolved'):
        snapshot['age']={'state':'unknown' if reason=='age_unknown' else 'boundary_unresolved',
                         'years':None if reason=='age_unknown' else 18}
    if reason=='diagnosis_unknown':
        snapshot['diagnosis']={'state':'unknown','value':None}
    if reason=='stage_unknown':
        snapshot['stage']={'state':'unknown','value':None}
    if reason=='context_incomplete':
        snapshot['period']=None
    if reason=='population_mismatch':
        snapshot['age']={'state':'confirmed_fixture','years':0}
    if reason=='context_conflict':
        snapshot['unresolved_conflicts']=[query]
    setup=dict(auth='doctor_current_pair', corpus='fixture-corpus-1', index='valid',
               source_admission='fixture_only', source_conflicts=[], source_coverage='sufficient',
               forbidden_effects=['network','medical_writes','raw_logs','role_bypass'])
    if status=='ACCESS_DENIED':
        setup['auth']=query
    if status=='UNAVAILABLE':
        setup['index']=reason
    if status=='NO_EVIDENCE':
        setup['source_coverage']=reason
    if reason=='source_conflict':
        setup['source_conflicts']=[query]
    return dict(id=cid, split=split, family=family, document_families=doc_families,
                direction=direction, categories=categories, query=query,
                mode=mode, context=snapshot if mode=='contextual' else None, test_setup=setup,
                provenance='Codex:synthetic_technical', clinical_review=None,
                expected=dict(status=status,reason_code=reason,sufficient_sets=sufficient_sets))


if __name__ == '__main__':
    main()
