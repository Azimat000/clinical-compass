"""Build a clean local roster; copy only unchanged source metadata, never people.

All people, historical dates and physician confirmations are fictional fixtures.
The provenance remains in an append-only audit record, separate from clinical text.
The running service must be stopped before switching its database to this result.
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
from apps.compass import decisions, events, first_visits, records

DATASET = ROOT / 'data/fictional/clinic-20261023.json'
SOURCE_TABLES = ('source_versions', 'catalog_versions', 'assessment_form_releases')


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


def load_dataset():
    dataset = json.loads(DATASET.read_text())
    assert dataset['provenance'] == {
        'synthetic': True, 'simulated_dates': True,
        'clinical_review': False, 'real_user_trial': False}
    doctors = {d['id'] for d in dataset['doctors']}
    people = dataset['patients']
    assert len(doctors) == 3 and len(people) == 8
    assert len({p['id'] for p in people}) == len(people)
    assert len(doctors | {p['login'] for p in people}) == len(doctors) + len(people)
    for p in people:
        assert p['doctor'] in doctors and 18 <= p['age'] <= 120
        assert all(len(p[f]) == 7 for f in ('diary', 'wellbeing', 'replies'))
        assert len(p['visits']) == len(p['levels']) == 3
        assert len(p['plans']) == 2 and len(p['outcomes']) == 6
        for index, outcome in enumerate(p['outcomes']):
            assert outcome in communication.LABELS
            note = p.get('outcome_notes', {}).get(str(index))
            assert note is None or isinstance(note, str) and 1 <= len(note.strip()) <= 1000
            assert outcome == 'taken' or note, 'Non-completion needs an explicit, coherent explanation'
    return dataset


def adherence_reason(profile, index):
    note = profile.get('outcome_notes', {}).get(str(index))
    if note:
        return note
    if profile['outcomes'][index] != 'taken':
        raise ValueError('An incomplete fictional task needs an authored explanation')
    return 'Самоотчёт за этот день отправлен.'


def copy_sources(source, target):
    # Any reviewed catalog requiring an old user needs a separate migration plan.
    if source.execute('SELECT 1 FROM catalog_versions WHERE reviewed_by IS NOT NULL').fetchone():
        raise ValueError('Source has person-bound catalog reviews; refusing to rewrite their provenance')
    with database.transaction(target):
        for table in SOURCE_TABLES:
            rows = source.execute('SELECT * FROM ' + table).fetchall()
            for row in rows:
                target.execute('INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in row) + ')', tuple(row))
    # Verifies the installed definition without changing its exact release record.
    assessments.install_form(target)


def confirm_plan(db, doctor, pid, content, basis):
    proposal = decisions.draft(db, doctor, pid, {
        'request_key': key(), 'kind': 'plan_change', 'content': content,
        'basis': basis,
        'uncertainties': 'Недостающие сведения обсуждаются на следующем приёме. Причины жалоб по дневнику не установлены.',
    })
    version = db.execute('SELECT version FROM proposals WHERE id=?', (proposal,)).fetchone()[0]
    confirmation = decisions.confirm(db, doctor, pid, proposal, {
        'version': str(version), 'decision': 'approved', 'reviewed': 'yes',
        'rationale': 'План наблюдения обсуждён на приёме; учтены записи и вопросы пациента.',
    })
    return db.execute('SELECT id FROM care_actions WHERE confirmation_id=?', (confirmation,)).fetchone()[0]


def answer_values(profile, visit):
    form = assessments.definition()
    # Distinct item responses, with the per-person/subscale course explicitly authored.
    groups = {n: index for index, group in enumerate(form['subscales'].values()) for n in group['items']}
    values = {}
    for n in range(1, 43):
        base = profile['levels'][visit][groups[n]]
        variation = (n + visit + int(profile['id'][1:])) % 7
        values[f'answer_{n}'] = str(max(0, min(3, base + (-1 if variation == 0 else 1 if variation == 1 else 0))))
    if profile.get('incomplete_visit') == visit:
        values['answer_17'] = ''
        values['answer_38'] = ''
    return values


def seed_patient(db, profile, days, today):
    p = profile
    pid = p['id']
    doctor = {'id': p['doctor'], 'role': 'doctor'}
    patient = {'id': p['login'], 'role': 'patient'}
    age = {'age_status': 'known', 'age_years': str(p['age'])}
    with fictional_day(days[0], 8) as stamp:
        db.execute('''INSERT INTO patients(id,user_id,code,age_years,age_status,synthetic,created_at)
                      VALUES(?,?,?,?,'known',1,?)''', (pid, p['login'], p['name'], p['age'], stamp))
        assert access.accept_invite(db, p['login'], access.invite(db, p['doctor'], pid))
    task = None
    action = None
    for index, day in enumerate(days):
        adverse = index >= p.get('adverse_from', 99)
        status = 'conflicting' if p.get('conflicting_last') and index == 6 else 'known'
        with fictional_day(day):
            records.save(db, patient, pid, 'self_report', {
                'request_key': key(), 'observed_on': day.isoformat(), **age,
                'wellbeing': p['wellbeing'][index], 'complaints_status': 'known',
                'complaints_text': p['diary'][index], 'summary': p['diary'][index],
                'adverse_events_status': 'known' if adverse else 'unknown',
                'adverse_events_text': p.get('adverse_text', '') if adverse else '',
            })
            if task:
                outcome = p['outcomes'][index - 1]
                reason = adherence_reason(p, index - 1)
                communication.report(db, patient, pid, task, {'request_key': key(), 'outcome': outcome, 'reason': reason})
        if index in (0, 3, 6):
            visit = index // 3
            with fictional_day(day, 12):
                values = {
                    'request_key': key(), 'base_revision': '0', 'state': 'completed',
                    'visit_kind': 'first' if index == 0 else 'repeat', 'observed_on': day.isoformat(),
                    **age, 'age_source': 'patient', 'age_basis': 'Возраст указан пациентом на приёме.',
                    'complaints_status': status,
                    'complaints_text': p['visits'][visit] if status == 'conflicting' else p['diary'][index],
                    'complaints_basis': 'Беседа на приёме и записи пациента.',
                    'course_status': 'known', 'course_text': p['course'], 'course_basis': 'Со слов пациента на первом приёме.',
                    'history_status': 'known', 'history_text': p['history'], 'history_basis': 'Со слов пациента; документами не подтверждено.',
                    'impact_status': 'known', 'impact_text': p['impact'], 'impact_basis': 'Описание повседневных трудностей пациентом.',
                    'followup_status': 'unknown' if index == 0 else status,
                    'followup_text': '' if index == 0 else p['visits'][visit],
                    'followup_basis': '' if index == 0 else 'Беседа и сопоставление дневника с предыдущим приёмом.',
                    'action_draft': p['plans'][0 if index == 0 else 1],
                }
                first_visits.save(db, doctor, pid, 'new', values)
                # The doctor's observation is also in the common record timeline.
                records.save(db, doctor, pid, 'visit', {
                    'request_key': key(), 'observed_on': day.isoformat(), **age,
                    'complaints_status': status,
                    'complaints_text': p['visits'][visit] if status == 'conflicting' else p['diary'][index],
                    'summary': p['visits'][visit],
                    'adverse_events_status': 'known' if adverse else 'unknown',
                    'adverse_events_text': p.get('adverse_text', '') if adverse else '',
                })
                form_id = assessments.definition()['id']
                request = assessments.assign(db, doctor, pid, {
                    'assignment_key': key(), 'form_version_id': form_id, **age,
                    'age_basis': 'Возраст сверён с карточкой и сообщением пациента на приёме.',
                })
            with fictional_day(day, 13):
                assessments.submit(db, patient, request, {'form_version_id': form_id, **answer_values(p, visit)})
            if index in (0, 6):
                with fictional_day(day, 14):
                    action = confirm_plan(db, doctor, pid, p['plans'][0 if index == 0 else 1], p['visits'][visit])
        with fictional_day(day, 15):
            if index < 6:
                task = communication.schedule(db, doctor, pid, {
                    'request_key': key(), 'action_id': action, 'label': p['task'],
                    'due_at': days[index + 1].isoformat() + 'T08:00:00+00:00', 'reviewed': 'yes',
                })
        with fictional_day(day, 16):
            communication.send(db, patient, pid, {'request_key': key(), 'body': p['diary'][index]})
        with fictional_day(day, 17):
            communication.send(db, doctor, pid, {'request_key': key(), 'body': p['replies'][index]})
    # Current tasks use the real clock; no future fictional replies or expired form.
    communication.schedule(db, doctor, pid, {
        'request_key': key(), 'action_id': action, 'label': p['task'],
        'due_at': today.isoformat() + 'T20:00:00+03:00', 'reviewed': 'yes',
    })
    assessments.assign(db, doctor, pid, {
        'assignment_key': key(), 'form_version_id': assessments.definition()['id'], **age,
        'age_basis': 'Возраст в карточке и последнем приёме согласован.',
    })


def build(source_path, target_path, credentials_path):
    source_path, target_path, credentials_path = (Path(p).resolve() for p in (source_path, target_path, credentials_path))
    if not source_path.is_file() or len({source_path, target_path, credentials_path}) != 3:
        raise ValueError('Source, new database and new credentials must be different files')
    if target_path.exists() or credentials_path.exists():
        raise FileExistsError('Refusing to overwrite database or credentials')
    dataset = load_dataset()
    today = records.today()
    days = [today - timedelta(days=n) for n in (42, 35, 28, 21, 14, 7, 1)]
    credentials = []
    target_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    target_created = credentials_created = False
    try:
        target_path.touch(mode=0o600, exist_ok=False)
        target_created = True
        with closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as source, closing(database.connect(target_path)) as db:
            if source.execute('SELECT 1 FROM patients WHERE synthetic<>1').fetchone():
                raise ValueError('Only an entirely synthetic source is supported')
            database.migrate(db)
            copy_sources(source, db)
            identities = [(d['id'], 'doctor', d['name']) for d in dataset['doctors']]
            identities += [(p['login'], 'patient', p['name']) for p in dataset['patients']]
            with database.transaction(db):
                for uid, role, name in identities:
                    password = secrets.token_urlsafe(18)
                    db.execute('INSERT INTO users VALUES(?,?,?,?,0)',
                               (uid, role, name, generate_password_hash(password, method='scrypt:32768:8:1')))
                    credentials.append({'login': uid, 'role': role, 'name': name, 'password': password})
            for profile in dataset['patients']:
                seed_patient(db, profile, days, today)
            provenance = {**dataset['provenance'], 'dataset_version': dataset['version'],
                          'dataset_sha256': hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                          'actual_generated_at': database.now(), 'observation_start': days[0].isoformat(),
                          'observation_end': days[-1].isoformat(),
                          'patient_ids': [p['id'] for p in dataset['patients']]}
            db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                       ('fictional.roster_loaded', dataset['version'], database.now(), json.dumps(provenance, ensure_ascii=False)))
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            # No old identities, records, sessions or search index fragments were copied.
            old_users = {r[0] for r in source.execute('SELECT id FROM users')}
            old_patients = {r[0] for r in source.execute('SELECT id FROM patients')}
            assert old_users.isdisjoint(uid for uid, _, _ in identities)
            assert old_patients.isdisjoint(p['id'] for p in dataset['patients'])
        descriptor = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        credentials_created = True
        with os.fdopen(descriptor, 'w') as handle:
            json.dump({'url': 'http://127.0.0.1:8000', 'accounts': credentials}, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    except BaseException:
        if target_created:
            target_path.unlink(missing_ok=True)
        if credentials_created:
            credentials_path.unlink(missing_ok=True)
        raise
    return {**provenance, 'database': str(target_path), 'credentials_file': str(credentials_path),
            'doctors': len(dataset['doctors']), 'patients': len(dataset['patients'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.credentials), ensure_ascii=False, indent=2))
