"""S55: isolated, authored fictional longitudinal roster; no startup mutations.

Build a new private database, preserving only exact source/form metadata. Historical
actors and times are simulated and recorded as such. Never enables clinical rules.
Medicine labels are deliberately neutral: no verified GRLS release is available.
"""
import argparse
from contextlib import ExitStack, closing, contextmanager
from datetime import timedelta
import hashlib
import json
import os
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
from apps.compass import decisions, events, extraction, first_visits, medications
from apps.compass import plan_tasks, records, report_drafts, routing
from tools.replace_roster import copy_sources, SOURCE_TABLES

DATASET = ROOT / 'data/fictional/clinic-20261026.json'
OFFSETS = (0, 7, 14, 21, 28, 35, 41)
MEDICINES = ('Препарат А, таблетки', 'Препарат Б, таблетки')


def key():
    return secrets.token_hex(16)


@contextmanager
def day_at(day, hour):
    stamp = day.isoformat() + f'T{hour:02}:00:00.000000+00:00'
    with ExitStack() as stack:
        for module in (database, access, ages, assessments, clinical_rules,
                       communication, decisions, events, extraction, first_visits,
                       medications, report_drafts):
            if hasattr(module, 'now'):
                stack.enter_context(patch.object(module, 'now', return_value=stamp))
        stack.enter_context(patch.object(records, 'today', return_value=day))
        yield stamp


def dataset():
    data = json.loads(DATASET.read_text())
    assert data['provenance'] == dict(synthetic=True, simulated_dates=True,
                                    clinical_review=False, real_user_trial=False)
    assert len(data['doctors']) == 2 and len(data['patients']) == 10
    identities = [d['id'] for d in data['doctors']] + [p['login'] for p in data['patients']]
    assert len(set(identities)) == 12
    assert len({p['id'] for p in data['patients']}) == 10
    for p in data['patients']:
        assert p['doctor'] in identities[:2] and 18 <= p['age'] <= 90
        assert len(p['diary']) == len(p['wellbeing']) == 7
        assert len(p['visits']) == len(p['levels']) == 3
        assert p['outcome'] in communication.LABELS and p['reason']
        assert p['medication'] in (None, 0, 1)
        for field in ('course', 'history', 'life_history', 'family_history', 'somatic',
                      'allergies', 'impact', 'plan', 'task', 'question', 'reply'):
            assert p[field].strip()
    return data


def decision(db, doctor, p, day, kind, content, *, replace=False, stop=False,
             approve=True, parent='', basis=None):
    form = dict(request_key=key(), kind=kind, content=content,
                basis=basis or p['visits'][2],
                uncertainties='Причина жалоб и вклад отдельных обстоятельств не установлены. '
                              'Полнота сведений и переносимость требуют очного уточнения.', parent_id=parent)
    if kind.startswith('therapy_'):
        form.update(therapy_reference=decisions.reference()['version'],
                    aviandr_conclusion='insufficient_data',
                    aviandr_basis='Данных для индивидуального выбора Авиандра недостаточно; препарат не выбран.')
        for area in decisions.reference()['review_areas']:
            form['review_' + area['id']] = 'unknown'
            form['note_' + area['id']] = 'Полного источникового основания для индивидуального выбора нет; требуется отдельная проверка.'
    if replace:
        form.update(med_change='replace', med_reviewed='yes', med_base=medications.base_id(db, p['id']))
        if not stop:
            index = 1 - p['medication'] if p['scenario'] == 'adverse_and_change' and kind == 'therapy_change' else p['medication']
            form.update(med_0_name=MEDICINES[index], med_0_start=(day + timedelta(days=1)).isoformat(),
                        med_0_days='60', med_0_0_time='08:00', med_0_0_qty='4')
    if kind == 'referral':
        form.update(routing_reference=routing.reference()['version'],
                    route_category='desirable', route_urgency='planned',
                    route_severity_status='known', route_population_status='known',
                    route_age_years=str(p['age']), route_specialty='Психиатр',
                    route_severity='Жалобы сохраняются, повседневная активность ограничена; запись врача, без автоматической категории.',
                    route_population='Совершеннолетний пациент; возраст указан в карточке и приёмах.',
                    route_evidence=p['visits'][1],
                    route_unavailable='Полного соматического обследования и независимой оценки в карточке нет.')
    proposal = decisions.draft(db, doctor, p['id'], form)
    if approve is None:
        return proposal, None
    version = db.execute('SELECT version FROM proposals WHERE id=?', (proposal,)).fetchone()[0]
    confirmation = decisions.confirm(db, doctor, p['id'], proposal,
        dict(version=str(version), decision='approved' if approve else 'rejected', reviewed='yes',
             rationale='Обсуждено на приёме с учётом исходных записей и вопросов пациента.' if approve else
                       'Проект отклонён: сначала уточнить обстоятельства и фактические отметки, изменения не применены.'))
    row = db.execute('SELECT id FROM care_actions WHERE confirmation_id=?', (confirmation,)).fetchone()
    return proposal, row['id'] if row else None


def visit(db, doctor, p, day, index):
    values = first_visits.initial_values(db, doctor, p['id']) if index else {}
    values.update(request_key=key(), base_revision='0', state='draft',
                  note_schema=first_visits.NOTE_SCHEMA, editor_mode=first_visits.TEXT_EDITOR,
                  visit_kind='first' if index == 0 else 'repeat', observed_on=day.isoformat(),
                  age_status='known', age_years=str(p['age']), age_source='patient',
                  age_basis='Возраст указан пациентом на приёме.',
                  wellbeing='unknown' if index == 0 else p['wellbeing'][3 if index == 1 else 6])
    fields = {name: p[name] for name in (*first_visits.STATIC_FIELDS, 'course', 'impact')}
    fields.update(complaints=p['diary'][index * 3], followup=p['visits'][index],
                  mental_status='Контакт поддерживает, на вопросы отвечает по существу, описывает переживания и затруднения. '
                                'Речь последовательная, ориентирован в ситуации встречи.',
                  physical_status='Очный соматический осмотр и инструментальные измерения на этой встрече не проводились. '
                                  'Приведены только сообщённые сведения и представленные записи.',
                  other_states='Иные проявления обсуждены в беседе; дополнительных подтверждённых сведений в записи нет.',
                  safety='В беседе текущих намерений причинить себе вред не сообщает. Запись относится к этой встрече; '
                         'будущее состояние и отсутствие риска из неё не выводятся.',
                  acute='Новых внезапных телесных жалоб в ходе встречи не сообщает; сведения за другие дни отражены в дневнике.',
                  conclusion=p['visits'][index])
    if index == 0:
        fields['followup'] = 'Первый приём в текущей истории; сравнение с предыдущим приёмом невозможно.'
    for code, detail in fields.items():
        if index and code in first_visits.STATIC_FIELDS:
            continue  # Carry the exact version/date/source through the public editor contract.
        values[code + '_text'] = detail
        values[code + '_status'] = 'auto'
    vid = first_visits.save(db, doctor, p['id'], 'new', values)
    first_visits.save_documents(db, doctor, p['id'], vid, dict(
        request_key=key(), base_revision='1',
        documented_facts='Представлена запись от ' + day.isoformat() + ': ' + p['visits'][index],
        document_basis='Текст записи, представленный на встрече; сведения сверены с исходником в разделе «Документы».'))
    values.update(request_key=key(), base_revision='2', state='completed')
    first_visits.save(db, doctor, p['id'], vid, values)
    return vid


def import_document(db, doctor, p, day):
    source = f"Запись от {day:%d.%m.%Y}. {p['age']} лет. Жалобы: {p['diary'][0]}\n" + p['somatic']
    iid = extraction.save_import(db, doctor, p['id'], source, key())
    candidates = extraction.history(db, p['id'])[0]['result']['candidates']
    for candidate in candidates[:2]:
        extraction.review(db, doctor, p['id'], iid, dict(
            request_key=key(), candidate_id=candidate['id'], field=candidate['field'],
            assertion=candidate['assertion'], value=extraction.canonical(candidate['value']),
            quote=candidate['quote'], disposition='accept', reason='Цитата и значение сверены с полным исходным текстом.'))
    if p['scenario'] == 'conflict_and_correction':
        quote = p['somatic']
        extraction.review(db, doctor, p['id'], iid, dict(
            request_key=key(), candidate_id='', field='adherence', assertion='conflicting',
            value='В исходнике даты приёма и дневника различались.', quote=quote, disposition='add',
            reason='Добавлено вручную по точному фрагменту. Позднейшее уточнение не стирает исходное расхождение.'))


def questionnaires(db, doctor, patient, p, index):
    for form in assessments.definitions():
        request = assessments.assign(db, doctor, p['id'], dict(assignment_key=key(), form_version_id=form['id']))
        level = p['levels'][index]
        answers = {}
        for number, item in enumerate(form['items'], 1):
            # Vary items without reversing the authored longitudinal course.
            value = max(0, level - (1 if (number + int(p['id'][1:])) % 5 == 0 else 0))
            if form['code'] == 'PHQ-9' and number == 9:
                value = 0  # Consistent with the authored encounter safety statement.
            answers[f'answer_{number}'] = str(value)
        if p['scenario'] == 'incomplete_assessment' and index == 1 and form['code'] == 'GAD-7':
            answers['answer_3'] = answers['answer_6'] = ''
        assessments.submit(db, patient, request, dict(form_version_id=form['id'], **answers))


def mark_doses(db, patient, p, day, offset):
    for dose in medications.occurrences(db, p['id'], day, day):
        if dose['future']:
            continue
        # Deliberate absence is never represented by a fabricated missed mark.
        if p['scenario'] == 'stop_and_gaps' and offset in (13, 14):
            continue
        if p['scenario'] == 'conflict_and_correction' and offset == 14:
            mode = 'unknown'
        elif p['scenario'] == 'missed_and_partial' and offset == 35:
            mode = 'missed'
        elif p['scenario'] == 'missed_and_partial' and offset == 36:
            mode = 'quantity'
        else:
            mode = 'taken'
        form = dict(request_key=key(), proposal_id=dose['proposal_id'], med_index=str(dose['med_index']),
                    slot_index=str(dose['slot_index']), dose_on=day.isoformat(), revision=dose['revision'],
                    outcome=mode, actual_quarters='2',
                    reason='Был в дороге, вечернюю отметку не внёс вовремя.' if mode == 'missed' else
                           'Приняла половину вместо целой таблетки; сообщила врачу, самостоятельно продолжать так не планирую.' if mode == 'quantity' else
                           'Не могу сейчас подтвердить по записям.' if mode == 'unknown' else 'Отметил фактический приём.')
        medications.report(db, patient, p['id'], form)
    if p['scenario'] == 'missed_and_partial' and offset == 41:
        yesterday = day - timedelta(days=1)
        for mode in ('unknown', 'taken'):
            dose = medications.occurrences(db, p['id'], yesterday, yesterday)[0]
            medications.report(db, patient, p['id'], dict(request_key=key(), proposal_id=dose['proposal_id'],
                med_index='0', slot_index='0', dose_on=yesterday.isoformat(), outcome=mode, revision=dose['revision']))


def seed_patient(db, p, start, today):
    pid = p['id']
    doctor, patient = dict(id=p['doctor'], role='doctor'), dict(id=p['login'], role='patient')
    with day_at(start, 7) as stamp:
        db.execute("INSERT INTO patients(id,user_id,code,age_years,age_status,synthetic,created_at) VALUES(?,?,?,?,'known',1,?)",
                   (pid, p['login'], p['name'], p['age'], stamp))
        access.accept_invite(db, p['login'], access.invite(db, p['doctor'], pid))
        import_document(db, doctor, p, start)
    last_task = action = None
    for offset in range(42):
        day = start + timedelta(days=offset)
        with day_at(day, 9):
            mark_doses(db, patient, p, day, offset)
        if offset not in OFFSETS:
            continue
        i = OFFSETS.index(offset)
        with day_at(day, 10):
            form = dict(request_key=key(), observed_on=day.isoformat(), age_status='known', age_years=str(p['age']),
                        wellbeing=p['wellbeing'][i], complaints_status='known', complaints_text=p['diary'][i], summary=p['diary'][i])
            meds = medications.approved(db, pid)
            if meds and meds[-1]['medications']:
                response = 'no_effect' if p['scenario'] in ('variable', 'missed_and_partial') else 'effect'
                if p['scenario'] in ('adverse_and_change', 'stop_and_gaps') and i in (2, 3):
                    response = 'adverse'
                if p['scenario'] in ('adverse_and_change', 'stop_and_gaps') and response != 'adverse':
                    detail = 'Устойчивый эффект пока оценить не могу; самочувствие меняется по дням.'
                    response = 'no_effect'
                else:
                    detail = p['feedback']
                form.update(medication_feedback_version='medication-feedback-v1', medication_feedback_plan=meds[-1]['id'])
                form['feedback_0_' + response] = 'yes'
                form['feedback_0_' + response + '_text'] = detail
            entry = records.save(db, patient, pid, 'self_report', form)
        with day_at(day, 11):
            if last_task:
                reason = 'Запись самочувствия за этот день отправлена; обстоятельства описаны в дневнике.'
                communication.report(db, patient, pid, last_task,
                    dict(request_key=key(), outcome='taken', reason=reason, revision=''), patient_only=True)
            if p['scenario'] == 'conflict_and_correction' and i == 3:
                old_day = start + timedelta(days=14)
                dose = medications.occurrences(db, pid, old_day, old_day)[0]
                medications.report(db, patient, pid, dict(request_key=key(), proposal_id=dose['proposal_id'],
                    med_index='0', slot_index='0', dose_on=old_day.isoformat(), outcome='taken', revision=dose['revision'],
                    reason='Сверил с ежедневником: приём был, исходная отметка означала неопределённость.'))
        if i in (0, 3, 6):
            index = i // 3
            with day_at(day, 12):
                visit(db, doctor, p, day, index)
            with day_at(day, 13):
                questionnaires(db, doctor, patient, p, index)
            with day_at(day, 14):
                if i == 0:
                    kind = 'therapy_start' if p['medication'] is not None else 'plan_change'
                    _, action = decision(db, doctor, p, day, kind, p['plan'], replace=p['medication'] is not None, basis=p['visits'][0])
                elif i == 3:
                    kind = {'adverse_and_change': 'therapy_change', 'stop_and_gaps': 'therapy_stop', 'referral': 'referral'}.get(p['scenario'], 'plan_change')
                    extra = ' Текущий состав препаратов отменён; продолжается наблюдение.' if kind == 'therapy_stop' else ' Новое расписание действует только после подтверждения.' if kind == 'therapy_change' else ''
                    _, action = decision(db, doctor, p, day, kind, p['plan'] + extra,
                        replace=kind in ('therapy_change', 'therapy_stop'), stop=kind == 'therapy_stop', basis=p['visits'][1])
                    if kind == 'therapy_stop':
                        _, action = decision(db, doctor, p, day, 'plan_change', p['plan'] +
                            ' Текущий состав отменён отдельным подтверждением; продолжается дневник без этого препарата.', basis=p['visits'][1])
                else:
                    _, action = decision(db, doctor, p, day, 'plan_change', p['plan'] + ' Сопоставить последние записи с предыдущим приёмом.')
        with day_at(day, 15):
            if i == 0:
                plan_tasks.schedule(db, doctor, pid, dict(request_key=key(), action_id=action,
                    label=p['task'], due_on=(today + timedelta(days=2)).isoformat(), reviewed='yes'))
            due = start + timedelta(days=OFFSETS[i + 1]) if i < 6 else day
            last_task = plan_tasks.schedule(db, doctor, pid, dict(request_key=key(), action_id=action,
                label=p['task'] if i == 6 else 'Записать самочувствие и обстоятельства дня',
                due_on=due.isoformat(), reviewed='yes'))
        with day_at(day, 16):
            mid = communication.send(db, patient, pid, dict(request_key=key(), body=p['question'] if i == 6 else p['diary'][i], entry_id=entry))
        with day_at(day, 17):
            communication.receipt(db, doctor, pid, mid, 'read')
            reply = [
                'Запись получена. На встрече разберём начало трудностей и влияние на обычные дела.',
                'Отметьте, чем этот день отличался от предыдущего: нагрузка, сон и помощь близких.',
                'Вижу эту запись. Подготовьте к приёму даты и обстоятельства, которые хотите уточнить.',
                'Сегодня сопоставили записи на приёме. Подтверждённые решения и отдельные пункты доступны в плане.',
                'Сохраните и этот день в дневнике. Сравним его с записями до повторного приёма.',
                'Перед следующей встречей подготовьте вопросы и проверьте фактические отметки по своим записям.',
                p['reply'],
            ][i]
            mid = communication.send(db, doctor, pid, dict(request_key=key(), body=reply, entry_id=entry))
        with day_at(day, 18):
            communication.receipt(db, patient, pid, mid, 'read')
        if i == 6:
            with day_at(day, 19):
                rid = communication.report(db, patient, pid, last_task, dict(request_key=key(), revision='',
                    outcome=p['outcome'], reason=p['reason']), patient_only=True)
                if p['scenario'] == 'conflict_and_correction':
                    communication.report(db, patient, pid, last_task, dict(request_key=key(), revision=rid,
                        outcome='taken', reason='Уточнил формулировку: сверены календарь и ежедневник, исправление сохранено.'), patient_only=True)
    # A current future task and pending questionnaires use the actual clock.
    plan_tasks.schedule(db, doctor, pid, dict(request_key=key(), action_id=action, label='Подготовить вопросы к следующему приёму',
        due_on=(today + timedelta(days=2)).isoformat(), reviewed='yes'))
    if p['scenario'] == 'pending_drafts':
        values = first_visits.initial_values(db, doctor, pid)
        values.update(request_key=key(), base_revision='0', state='draft', note_schema=first_visits.NOTE_SCHEMA,
                      editor_mode=first_visits.TEXT_EDITOR, observed_on=today.isoformat(), visit_kind='repeat',
                      complaints_text='Подготовлены вопросы о границах рабочего дня; запись ещё не завершена.')
        first_visits.save(db, doctor, pid, 'new', values)
        report_drafts.save(db, patient, pid, dict(request_key=key(), draft_revision='0', observed_on=today.isoformat(),
            wellbeing='same', complaints_status='known', complaints_text='Вчера закончил работу в девять. Хочу дописать, как спал.',
            summary='Вопросы к следующей встрече пока дописываю.'))
        decision(db, doctor, p, today, 'plan_change', 'Обсудить дополнительную встречу после уточнения рабочего графика.', approve=None)
    if p['scenario'] == 'stable_no_medication':
        rejected, _ = decision(db, doctor, p, today, 'plan_change', 'Увеличить частоту записей без уточнения нагрузки.', approve=False)
        decision(db, doctor, p, today, 'plan_change', 'Сохранить прежний объём дневника, уточнить трудные рабочие ситуации.', approve=None, parent=rejected)
    # New age evidence from a physician draft must precede the age-bound request.
    for form in assessments.definitions():
        assessments.assign(db, doctor, pid, dict(assignment_key=key(), form_version_id=form['id']))


def build(source_path, target_path, credentials_path):
    source_path, target_path, credentials_path = [Path(p).resolve() for p in (source_path, target_path, credentials_path)]
    if not source_path.is_file() or len({source_path, target_path, credentials_path}) != 3:
        raise ValueError('Source, output and access file must be distinct')
    if target_path.exists() or credentials_path.exists():
        raise FileExistsError('Refusing to overwrite existing output or access file')
    data = dataset()
    today = records.today()
    start = today - timedelta(days=42)
    accounts = []
    target_created = credentials_created = False
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.touch(mode=0o600, exist_ok=False)
        target_created = True
        with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as source, closing(database.connect(target_path)) as db:
            if source.execute('SELECT 1 FROM patients WHERE synthetic<>1').fetchone():
                raise ValueError('Only an entirely synthetic source is supported')
            old_users = {r[0] for r in source.execute('SELECT id FROM users')}
            old_patients = {r[0] for r in source.execute('SELECT id FROM patients')}
            identities = [(d['id'], 'doctor', d['name']) for d in data['doctors']]
            identities += [(p['login'], 'patient', p['name']) for p in data['patients']]
            if old_users & {u[0] for u in identities} or old_patients & {p['id'] for p in data['patients']}:
                raise ValueError('New roster must not reuse old identities')
            database.migrate(db)
            copy_sources(source, db)
            with database.transaction(db):
                for uid, role, name in identities:
                    password = secrets.token_urlsafe(18)
                    db.execute('INSERT INTO users VALUES(?,?,?,?,0)', (uid, role, name, generate_password_hash(password)))
                    accounts.append(dict(login=uid, role=role, name=name, password=password))
            for p in data['patients']:
                seed_patient(db, p, start, today)
            provenance = dict(**data['provenance'], dataset_version=data['version'],
                neutral_medication_labels=True, medication_eligibility_established=False,
                dataset_sha256=hashlib.sha256(DATASET.read_bytes()).hexdigest(), actual_generated_at=database.now(),
                observation_start=start.isoformat(), observation_end=(today - timedelta(days=1)).isoformat())
            db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                       ('fictional.roster_loaded', data['version'], database.now(), json.dumps(provenance, ensure_ascii=False)))
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            dump = '\n'.join(db.iterdump())
            assert all("'" + uid.replace("'", "''") + "'" not in dump for uid in old_users | old_patients)
            for table in SOURCE_TABLES:
                assert [tuple(r) for r in source.execute('SELECT * FROM ' + table)] == [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
        fd = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        credentials_created = True
        with os.fdopen(fd, 'w') as handle:
            json.dump(dict(url='http://127.0.0.1:8000', accounts=accounts), handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    except BaseException:
        if target_created:
            target_path.unlink(missing_ok=True)
        if credentials_created:
            credentials_path.unlink(missing_ok=True)
        raise
    return dict(**provenance, doctors=2, patients=10, database=str(target_path), credentials_file=str(credentials_path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.credentials), ensure_ascii=False, indent=2))
