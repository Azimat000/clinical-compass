"""Retain every requirement and verify exact scope of service changes."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
def read(p):
    return json.loads((root / p).read_text())
def save(p, value):
    (root / p).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
baseline = read('evidence/S17G/baseline.json')
original = json.loads(subprocess.check_output(['git', 'show', baseline['head'] + ':plan/coverage.json'], cwd=root))
current = read('plan/coverage.json')
original_manifest = json.loads(subprocess.check_output(['git', 'show', baseline['head'] + ':plan/manifest.json'], cwd=root))
for oldcard, newcard in zip(original_manifest['slices'], read('plan/manifest.json')['slices']):
    if oldcard['id'] != 'S17G':
        assert oldcard == newcard, oldcard['id']
    else:
        for key in ('id', 'depends_on', 'requirement_ids'):
            assert oldcard[key] == newcard[key], key
assert len(original['items']) == len(current['items']) == 83
assert sum(len(x['subchecks']) for x in current['items']) == 160
reviews = []
for before, after in zip(original['items'], current['items']):
    assert {k:v for k,v in before.items() if k != 'actual_evidence'} == {k:v for k,v in after.items() if k != 'actual_evidence'}
    assert set(before.get('actual_evidence', [])) <= set(after.get('actual_evidence', []))
    selected = 'S17G' in after['verification_slices']
    reviews.append({'id': after['id'], 'text': after['text'], 'subchecks': after['subchecks'],
                    'fulfilment_status': after['fulfilment_status'], 'S17G_assigned': selected,
                    'review': ('Сервисный сценарий/границы, организационная часть отложена пользователем; общее выполнение не повышено, клинические и внешние доказательства не получены.' if selected else 'Сохранено без изменения; вне приёмки подготовки показа.'),
                    'evidence': ['docs/demo/psychiatrist-patient-walkthrough.md', 'evidence/S17G/acceptance.md'] if selected else []})
save('evidence/S17G/requirements-review.json', {'requirements':83, 'subchecks':160, 'status_changes':[], 'items':reviews})
curator = read('plan/curator-followup.json')
mapping = {
  1:'Сервисный сценарий наблюдения, без чисел эффективности.',
  2:'Индивидуальные профили/вклад не установлены; внешний пробел сохранён.',
  3:'Сценарий шаги 1–8: кто, где входит, какие связанные аккаунты.',
  4:'Сценарий сервиса: психиатр и самостоятельный пациент центральны.',
  5:'Существующая справка: Авиандр рассматривается, названия из аудио не нормализуются в правила.',
  6:'Профессиональные ограничения не подтверждены этой подготовкой; вопрос источников/проверки.',
  7:'Дополнительный вход терапевта/F08 сохранён, обязательный терапевтический этап не добавлен.',
  8:'Справка/неизвестность и ручной проект, автоматического допуска нет.',
  9:'Две сессии, 42 ответа, три суммы врачу и квитанция пациенту проверены.',
 10:'Дополнительный первый приём без диагноза, новые ветви не активированы.',
 11:'Система не объявлена знающей больше врача; независимый клинический допуск открыт.',
 12:'Существующий первый приём со сведениями/источниками, S17E не переоткрыт.',
 13:'Направление/категории не диагноз и не постановка на учёт.',
 14:'Первый приём и явные неизвестности сохранены, новый скрининг не заявлен.',
 15:'Переход между врачами явно будущий, обмен не имитируется.',
 16:'Соматическую оценку выполняет врач; новая автоматическая ветвь не активна.',
 17:'Шаги 1/5: карточка, собственное решение, отдельное подтверждение.',
 18:'Одна ведущая пара, совместный доступ врачей не реализован.',
 19:'Фактические дневник/выполнение/причина/сообщение и просмотр врача.',
 20:'Два независимых браузерных контекста, заранее созданные связанные аккаунты.',
 21:'Фактический самостоятельный ввод DASS пациентом в двух циклах.',
 22:'Вопросы доступны пациенту; вычисленные баллы и интерпретация не выдаются.',
 23:'DASS врачу и субъективный дневник раздельно; короткий инструмент не готов.',
 24:'Точная существующая DASS42 сохранена; новые формы не выбирались/не активировались.',
 25:'Шаг 9: разрыв рекомендаций явно остаётся в S17H/I.',
 26:'Ручной проект и отдельное подтверждение врача проверены.',
 27:'ИИ не объявлен обязательным, не включён и не клинический эталон.',
 28:'Решение об алгоритмах/ИИ — будущий S17H, без загрузки модели/API.',
 29:'Возможность агента не выдаётся за доказанную пользу; будущий S17H.',
 30:'Депрессивное/тревожное направления остаются S17H/I, текущие суммы не диагноз.',
 31:'Примеры терапии не превращены в обязательный каталог или назначения.',
 32:'Источниковая спецификация рекомендаций и независимая проверка ещё предстоят.',
 33:'По позднейшему прямому поручению презентация/организация отложены; принимается только сервисный прогон.',
 34:'Только сервисный S17G: срок анкеты; модели/зависимости/клинические правила не добавлены.',
 35:'Неоднозначность 32:24 не отменяет F02/M03; организационное уточнение отложено.',
 36:'Предоставленный текст использован, аудио не сверено, модель не устанавливалась.',
 37:'Историческая дата по тексту сохранена в исходном реестре; подготовка встречи/проверка календаря отложена пользователем.',
 38:'Служебные подробности первой встречи не доказывают состав/реальные вклады.',
 39:'Личности Speaker не установлены; приватный оригинал не скопирован в слайды.',
 40:'Две однодневные точки и просмотр записей, без причинности; новые рекомендации будущие.'
}
assert len(curator['items']) == len(mapping) == 40
save('evidence/S17G/curator-review.json', {'items': [{'id':x['id'], 'source_meaning':x['meaning'], 'disposition':mapping[int(x['id'][1:])]} for x in curator['items']]})
allowed = {'memory/STATE.json','memory/DECISIONS.md','memory/BLOCKERS.md','memory/EXTERNAL.md',
           'memory/BUDGET.json','memory/sessions/S17G.md','START_HERE.md','plan/coverage.json','plan/COVERAGE.md',
           'AGENTS.md','plan/manifest.json','plan/slices/S17G.md','plan/ROADMAP.md','docs/product/psychiatrist-followup-plan.md',
           'apps/compass/assessments.py','apps/compass/templates/assessment_form.html','apps/compass/templates/assessments_panel.html','apps/tests/test_assessments.py'}
changed = []
for name, digest in baseline['tracked'].items():
    p = root / name
    assert p.is_file(), name
    if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        assert name in allowed, name
        changed.append(name)
preserved_untracked=[]
for name,digest in baseline['untracked'].items():
    if name.startswith('evidence/S17G/'):
        continue  # Own baseline artefact, not a pre-existing user change.
    assert hashlib.sha256((root/name).read_bytes()).hexdigest() == digest, name
    preserved_untracked.append(name)
newfiles = subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
for name in filter(None,newfiles):
    assert name in baseline['untracked'] or name.startswith(('evidence/S17G/','deliverables/curator-preview/')) or name in {'docs/demo/psychiatrist-patient-walkthrough.md','memory/sessions/S17G.md'},name
oldstate = json.loads(subprocess.check_output(['git','show',baseline['head']+':memory/STATE.json'],cwd=root))
state = read('memory/STATE.json')
for sid,v in oldstate['slices'].items():
    if sid != 'S17G':
        assert state['slices'][sid] == v,sid
budget=read('memory/BUDGET.json')
assert budget['spent'] == budget['commitments'] == 0 and budget['limit'] == 5000
assert read('evidence/S17G/browser-results.json')['status'] == 'PASS'
assert read('memory/STATE.json')['work_policy']['services_only'] is True
save('evidence/S17G/preservation.json', {'status':'PASS','tracked_files_checked':len(baseline['tracked']),
     'changed_tracked':changed,'preserved_preexisting_untracked':preserved_untracked,
     'clinical_resources_migrations_dependencies':'unchanged SHA-256', 'runtime_changes':'deadline label only; four inspected files','requirements':83,'subchecks':160,
     'requirement_statuses':'unchanged','other_slice_states':'unchanged','budget':'0 / 5000 RUB'})
print('PASS: 83/160, K01–K40, exact resources/migrations/dependencies, other slices and pre-existing files preserved')
