"""Read-only follow-up projection. No scoring, inference, deliveries or decisions."""
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo
from . import access, assessments, communication, decisions, first_visits, records
from .db import now

MOSCOW = ZoneInfo('Europe/Moscow')


def period(values):
    end = records.today()
    start = end - timedelta(days=29)
    try:
        # Both endpoints are required when an explicit interval is supplied.
        if 'start' in values or 'end' in values:
            raw_start, raw_end = values.get('start', ''), values.get('end', '')
            if len(raw_start) != 10 or len(raw_end) != 10:
                raise ValueError()
            start, end = date.fromisoformat(raw_start), date.fromisoformat(raw_end)
            if start.isoformat() != raw_start or end.isoformat() != raw_end:
                raise ValueError()
        if start.year < 1900 or start > end or end > records.today():
            raise ValueError()
    except (ValueError, TypeError):
        raise decisions.DecisionError('Укажите обе даты с 1900 года до сегодня; начало не должно быть позже конца.') from None
    return start.isoformat(), end.isoformat()


def local_day(stamp):
    """Observation dates stay dates; timestamps are selected by their Moscow day."""
    if len(stamp) == 10:
        return date.fromisoformat(stamp).isoformat()
    value = datetime.fromisoformat(stamp)
    if value.tzinfo is None:
        return None  # Do not invent a timezone for legacy data.
    return value.astimezone(MOSCOW).date().isoformat()


def view(db, user, patient_id, values):
    # A single read snapshot keeps the plan and its linked outcomes consistent.
    db.execute('SAVEPOINT follow_up_read')
    try:
        return _view(db, user, patient_id, values)
    finally:
        db.execute('ROLLBACK TO follow_up_read')
        db.execute('RELEASE follow_up_read')


def _view(db, user, patient_id, values):
    if user['role'] != 'doctor' or not db.execute(
            "SELECT 1 FROM users WHERE id=? AND role='doctor' AND disabled=0", (user['id'],)).fetchone():
        raise decisions.DecisionError('Сводка повторного приёма доступна врачу.', 403)
    patient = access.visible_patient(db, user, patient_id)
    if patient is None:
        raise decisions.DecisionError('Карточка недоступна.', 404)
    start, end = period(values)
    def includes(stamp):
        day = local_day(stamp)
        return day is not None and start <= day <= end

    authors = {r['id']: r['display_name'] for r in db.execute('SELECT id,display_name FROM users')}
    entries = [e for e in records.history(db, patient_id) if includes(e['observed_on'])]
    measured = [a for a in assessments.history(db, user, patient_id) if includes(a['observed_on'])]
    # Legacy encounters are separate sources, not duplicate representations of clinical entries.
    encounters = [dict(r) for r in db.execute('''SELECT e.*,u.display_name FROM encounters e
        LEFT JOIN users u ON u.id=e.author_id WHERE e.patient_id=?
        AND NOT EXISTS(SELECT 1 FROM clinical_entries c WHERE c.encounter_id=e.id)
        ORDER BY e.occurred_at DESC,e.id''', (patient_id,)) if includes(r['occurred_at'])]
    latest_visits = {}
    for v in first_visits.history(db, user, patient_id):
        latest_visits.setdefault(v['visit_id'], v)
    visits = [v for v in latest_visits.values() if includes(v['payload']['observed_on'])]

    # Carry the last confirmed decision before the interval forward, then show changes.
    actions = [dict(r) for r in db.execute('''SELECT a.*,p.id proposal_id,p.kind,p.version,p.payload_json,
        c.doctor_id,c.confirmed_at FROM care_actions a
        JOIN doctor_confirmations c ON c.id=a.confirmation_id JOIN proposals p ON p.id=c.proposal_id
        WHERE p.patient_id=? AND c.decision='approved' ORDER BY p.version''', (patient_id,))]
    before = [a for a in actions if local_day(a['effective_at']) and local_day(a['effective_at']) < start]
    plans = before[-1:] + [a for a in actions if includes(a['effective_at'])]
    for a in plans:
        a['payload'] = json.loads(a['payload_json'])
        a['carried'] = local_day(a['effective_at']) < start

    relationship = db.execute('''SELECT id FROM care_relationships WHERE patient_id=? AND doctor_id=?
        AND ends_at IS NULL AND starts_at<=?''', (patient_id, user['id'], now())).fetchone()
    tasks = []
    if relationship:
        for r in db.execute('''SELECT t.*,p.id proposal_id,p.version FROM adherence_tasks t
                JOIN care_actions a ON a.id=t.action_id JOIN doctor_confirmations c ON c.id=a.confirmation_id
                JOIN proposals p ON p.id=c.proposal_id WHERE t.relationship_id=? ORDER BY t.due_at,t.id''',
                (relationship['id'],)):
            if not includes(r['due_at']):
                continue
            task = dict(r)
            task['history'] = [dict(h) for h in db.execute(
                'SELECT * FROM adherence_entries WHERE task_id=? ORDER BY recorded_at,id', (task['id'],))]
            task['outcome'] = task['history'][-1]['outcome'] if task['history'] else 'unknown'
            task['diary_entries'] = [e for e in entries if e['kind'] == 'self_report'
                                     and e['observed_on'] == local_day(task['due_at'])]
            task['superseded'] = communication.superseded(db, task)
            task['future'] = task['due_at'] > now()
            tasks.append(task)

    days = {e['observed_on'] for e in entries if e['kind'] == 'self_report'}
    warnings = records.warnings(patient, entries)
    for v in visits:
        if v['payload']['age']['status'] == 'conflicting':
            warnings.append(f'{v["payload"]["observed_on"]}: противоречие возраста в приёме {v["visit_id"]}.')
        for code, field in v['payload']['fields'].items():
            if field['status'] == 'conflicting':
                warnings.append(f'{field["observed_on"]}: {first_visits.FIELDS[code][1]} — '
                                f'противоречивые сведения в приёме {v["visit_id"]}.')
    for task in tasks:
        if task['outcome'] == 'conflicting':
            warnings.append(f'Пункт «{task["label"]}»: последняя отметка — противоречие. '
                            'Все авторы и отметки сохранены в разделе выполнения.')
    return dict(start=start, end=end, generated_at=now(), entries=entries, measured=measured,
                encounters=encounters, visits=visits, plans=plans, tasks=tasks, authors=authors,
                warnings=warnings,
                missing_diary_days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1-len(days))
