"""Build a separate, synthetic walkthrough DB; never modify the source DB.

Historical clocks below belong only to fictional fixtures in this offline process.
They are not elapsed clinical observation, physician review, or source validation.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from datetime import timedelta
import json
from pathlib import Path
import secrets
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from werkzeug.security import generate_password_hash
from apps.compass import access, ages, assessments, clinical_rules, communication
from apps.compass import db as database
from apps.compass import decisions, events, first_visits, records

LABEL = 'УЧЕБНЫЙ ПРИМЕР'
PASSWORD = 'synthetic-test-password-2026'
PROFILES = [
    ('anna', 'Анна', 34, 'Постепенно лучше',
     ['Долго засыпаю, вечером прокручиваю рабочие дела.',
      'Две ночи удалось заснуть раньше, но утром ещё тяжело вставать.',
      'Стала реже просыпаться. По вечерам беспокойство ещё бывает.',
      'Вернулась к прогулкам. Сил на обычные дела стало больше.',
      'Последнюю неделю чаще высыпаюсь. Хочу обсудить дальнейшее наблюдение.'],
     ['worse', 'same', 'better', 'better', 'better'], [2, 1, 0]),
    ('mikhail', 'Михаил', 46, 'Пока без изменений',
     ['Сон прерывистый, постоянно возвращаюсь мыслями к работе.',
      'Особых изменений не заметил. Дневник заполнял не каждый день.',
      'По-прежнему устаю к середине дня, ночью просыпаюсь.',
      'Беспокойство и усталость сохраняются. Хочу задать вопросы на приёме.',
      'Самочувствие примерно прежнее. Не знаю, с чем это связано.'],
     ['same'] * 5, [2, 2, 2]),
    ('elena', 'Елена', 57, 'Ухудшение и новое НЯ',
     ['Мало сил, трудно сосредоточиться на домашних делах.',
      'Стала хуже спать. Больше устаю после обычной прогулки.',
      'В последние дни появилась тошнота. Причину не знаю.',
      'Тошнота повторялась. Самочувствие хуже, записала вопрос врачу.',
      'Хочу обсудить ухудшение и новые ощущения на повторном приёме.'],
     ['same', 'worse', 'worse', 'worse', 'worse'], [1, 2, 2]),
    ('sergey', 'Сергей', 29, 'Пропуски и уточнения',
     ['Тревожусь перед рабочими встречами, отвлекаюсь и забываю записи.',
      'На неделе пропустил дневник: был в поездке.',
      'Отметил выполнение, но потом вспомнил, что записал не все дни.',
      'Снова веду дневник. Два дня не помню, поэтому оставляю «нет сведений».',
      'Хочу вместе с врачом уточнить отметки, а не считать все дни выполненными.'],
     ['same', 'same', 'unknown', 'better', 'same'], [1, None, 1]),
    ('irina', 'Ирина', None, 'Возраст ещё не уточнён',
     ['Плохо сплю и быстро устаю. Возраст в учебной карточке пока не указан.',
      'Записала, как спала последние несколько дней. Возраст ещё не уточнён.',
      'Самочувствие меняется. Не все вопросы смогла заполнить.',
      'Есть новые записи дневника, но данных для взрослой анкеты пока недостаточно.',
      'На повторном приёме нужно уточнить возраст и пропущенные сведения.'],
     ['unknown', 'same', 'unknown', 'same', 'same'], []),
]


@contextmanager
def fictional_day(day, hour=9):
    stamp = day.isoformat() + f'T{hour:02}:00:00.000000+00:00'
    with ExitStack() as stack:
        for module in (database, access, ages, assessments, clinical_rules,
                       communication, decisions, events, first_visits, records):
            if hasattr(module, 'now'):
                stack.enter_context(patch.object(module, 'now', return_value=stamp))
        stack.enter_context(patch.object(records, 'today', return_value=day))
        yield stamp


def key():
    return secrets.token_hex(16)


def plan(db, doctor, pid, content, approve=True):
    proposal = decisions.draft(db, doctor, pid, {
        'request_key': key(), 'kind': 'plan_change',
        'content': LABEL + '. ' + content,
        'basis': 'Смоделированная беседа и учебный дневник; не клинический эталон.',
        'uncertainties': 'Лекарственное лечение не задано. Независимой клинической проверки нет.',
    })
    if not approve:
        return None
    version = db.execute('SELECT version FROM proposals WHERE id=?', (proposal,)).fetchone()[0]
    confirmation = decisions.confirm(db, doctor, pid, proposal, {
        'version': str(version), 'decision': 'approved', 'reviewed': 'yes',
        'rationale': LABEL + ': смоделировано отдельное подтверждение врача; реального врача не было.',
    })
    return db.execute('SELECT id FROM care_actions WHERE confirmation_id=?', (confirmation,)).fetchone()[0]


def seed(db, doctor_id):
    doctor = {'id': doctor_id, 'role': 'doctor'}
    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='doctor' AND disabled=0", (doctor_id,)).fetchone():
        raise ValueError('An existing enabled demo doctor is required')
    if db.execute("SELECT 1 FROM patients WHERE synthetic<>1").fetchone():
        raise ValueError('Only entirely synthetic databases are supported')
    ids = [f'WD{i:02}' for i in range(1, 6)]
    if db.execute('SELECT 1 FROM patients WHERE id IN (?,?,?,?,?)', ids).fetchone():
        raise ValueError('Walkthrough already exists; refusing duplicate/partial seed')
    if any(db.execute('SELECT 1 FROM users WHERE id=?', ('demo-' + p[0],)).fetchone() for p in PROFILES):
        raise ValueError('Walkthrough login already exists')
    today = records.today()
    days = [today - timedelta(days=n) for n in (28, 21, 14, 7, 1)]
    hashed = generate_password_hash(PASSWORD, method='scrypt:32768:8:1')
    result = []
    for number, (slug, name, age, title, texts, trajectory, scores) in enumerate(PROFILES, 1):
        pid, uid = f'WD{number:02}', 'demo-' + slug
        patient = {'id': uid, 'role': 'patient'}
        age_fields = {'age_status': 'unknown' if age is None else 'known'}
        if age is not None:
            age_fields['age_years'] = str(age)
        with fictional_day(days[0], 8) as stamp:
            db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (uid, 'patient', f'{LABEL} · {name}', hashed))
            db.execute('''INSERT INTO patients(id,user_id,code,birth_date,age_years,age_status,synthetic,created_at)
                          VALUES(?,?,?,NULL,?,?,1,?)''',
                       (pid, uid, f'Учебный {number:02} · {name} — {title}', age, age_fields['age_status'], stamp))
            access.accept_invite(db, uid, access.invite(db, doctor_id, pid))
        action, task = None, None
        for index, day in enumerate(days):
            with fictional_day(day):
                adverse = slug == 'elena' and index >= 2
                records.save(db, patient, pid, 'self_report', {
                    'request_key': key(), 'observed_on': day.isoformat(), **age_fields,
                    'wellbeing': trajectory[index], 'complaints_status': 'known',
                    'complaints_text': texts[index],
                    'adverse_events_status': 'known' if adverse else 'unknown',
                    'adverse_events_text': 'Учебная запись: тошнота. Связь с препаратом не установлена.' if adverse else '',
                    'summary': f'{LABEL}. Неделя {index + 1}. {texts[index]}',
                })
                if task is not None:
                    outcome = ['taken', 'missed', 'unknown', 'conflicting'][index - 1] if slug == 'sergey' else 'taken'
                    communication.report(db, patient, pid, task, {
                        'request_key': key(), 'outcome': outcome,
                        'reason': LABEL + ': был в поездке / часть дней не помню.' if slug == 'sergey' else 'Учебная отметка дневника.',
                    })
                if index in (0, 2, 4):
                    first_visits.save(db, doctor, pid, 'new', {
                        'request_key': key(), 'base_revision': '0', 'state': 'completed',
                        'visit_kind': 'first' if index == 0 else 'repeat', 'observed_on': day.isoformat(),
                        **age_fields, 'age_source': 'patient', 'age_basis': 'Вымышленный профиль.' if age is not None else '',
                        'complaints_status': 'known', 'complaints_text': texts[index],
                        'complaints_basis': LABEL + ': смоделированная беседа.',
                        'course_status': 'known', 'course_text': 'Наблюдение в учебной истории в течение нескольких недель.',
                        'course_basis': 'Даты смоделированы при загрузке примеров.',
                        'impact_status': 'known', 'impact_text': 'Сон, утомляемость и обычные дела со слов вымышленного пациента.',
                        'impact_basis': 'Учебная беседа, не реальная оценка врача.',
                        'followup_status': 'unknown' if index == 0 else 'known',
                        'followup_text': '' if index == 0 else texts[index],
                        'followup_basis': '' if index == 0 else 'Сопоставление вымышленных записей.',
                        'action_draft': LABEL + '. Обсудить дневник и уточнить недостающие сведения. Это не назначение.',
                    })
                    if age is not None:
                        form = assessments.definition()
                        request = assessments.assign(db, doctor, pid, {
                            'assignment_key': key(), 'form_version_id': form['id'],
                            **age_fields, 'age_basis': 'Вымышленный профиль: возраст согласован между записями.',
                        })
                        value = scores[index // 2]
                        answers = {f'answer_{n}': str(value if value is not None else 1) for n in range(1, 43)}
                        if value is None:
                            answers['answer_42'] = ''
                        assessments.submit(db, patient, request, {'form_version_id': form['id'], **answers})
                if index in (0, 4):
                    action = plan(db, doctor, pid,
                        ('Вести дневник самочувствия и записывать вопросы для следующего приёма.' if index == 0 else
                         'Продолжить учебный дневник. На следующем приёме обсудить изменения, пропуски и новые жалобы.'))
                if index < 4:
                    task = communication.schedule(db, doctor, pid, {
                        'request_key': key(), 'action_id': action,
                        'label': LABEL + ': записать самочувствие и вопросы к следующему приёму',
                        'due_at': days[index + 1].isoformat() + 'T08:00:00+00:00', 'reviewed': 'yes',
                    })
            with fictional_day(day, 10):
                communication.send(db, patient, pid, {'request_key': key(), 'body': LABEL + '. ' + texts[index]})
            with fictional_day(day, 11):
                communication.send(db, doctor, pid, {'request_key': key(),
                    'body': LABEL + '. Запись получена в смоделированном диалоге. Обсудим изменения и вопросы на повторном приёме.'})
        with fictional_day(today):
            communication.schedule(db, doctor, pid, {
                'request_key': key(), 'action_id': action, 'label': LABEL + ': сегодня добавить запись дневника',
                'due_at': today.isoformat() + 'T00:00:00+00:00', 'reviewed': 'yes',
            })
            if age is not None:
                form = assessments.definition()
                assessments.assign(db, doctor, pid, {'assignment_key': key(), 'form_version_id': form['id'],
                    **age_fields, 'age_basis': 'Вымышленный возраст для самостоятельной проверки анкеты.'})
            else:
                try:
                    assessments.assign(db, doctor, pid, {'assignment_key': key(), 'form_version_id': assessments.definition()['id'],
                        **age_fields, 'age_basis': 'Возраст не указан.'})
                except assessments.AssessmentError:
                    pass
                else:
                    raise AssertionError('Unknown age must not authorize an adult questionnaire')
            if slug == 'elena':
                plan(db, doctor, pid, 'Черновик: уточнить новое нежелательное явление. Не подтверждён и не меняет план.', approve=False)
            if slug == 'sergey':
                records.save(db, doctor, pid, 'visit', {
                    'request_key': key(), 'observed_on': today.isoformat(), **age_fields,
                    'complaints_status': 'conflicting',
                    'complaints_text': 'Учебное противоречие: в сообщении отмечено улучшение, в беседе — без изменений. Требует уточнения.',
                    'summary': LABEL + ': противоречия не разрешены автоматически.',
                })
        result.append({'patient_id': pid, 'login': uid, 'name': name, 'story': title,
                       'url': '/demo/' + pid, 'summary_url': '/patients/' + pid + '/follow-up'})
    # Deliberately leave the existing patients' queues untouched.
    db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
        ('demo.walkthrough_loaded', 'walkthrough-v1', database.now(), json.dumps({
            'synthetic': True, 'simulated_dates': True, 'clinical_review': False,
            'patient_ids': ids, 'actual_generated_at': database.now()}, ensure_ascii=False)))
    return {'synthetic': True, 'simulated_dates': True, 'generated_at': database.now(),
            'doctor_login': doctor_id, 'patients': result}


def build(source, target, doctor_id='doc-a'):
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_file() or source == target:
        raise ValueError('Source must exist; target must be a different new file')
    # Exclusive creation is essential: never overwrite manual work or a previous demo.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(mode=0o600, exist_ok=False)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, \
                closing(database.connect(target)) as db:
            original.backup(db)
            report = seed(db, doctor_id)
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--doctor', default='doc-a')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.doctor), ensure_ascii=False, indent=2))
