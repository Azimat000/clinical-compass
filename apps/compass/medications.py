"""Physician-authored schedules and patient-reported quantities. No drug advice."""
from datetime import date, datetime, timedelta
import json
import re
from zoneinfo import ZoneInfo
from . import access, records
from .db import now, transaction

MOSCOW = ZoneInfo('Europe/Moscow')
MAX_MEDICATIONS = 8
MAX_SLOTS = 4
# Storage/UI limits, never clinical dose or course recommendations.
MAX_QUARTERS = 80
LABELS = {'taken': 'Принято', 'partial': 'Принято частично', 'missed': 'Пропущено', 'unknown': 'Нет отметки'}


def error(message, status=400):
    from .decisions import DecisionError
    return DecisionError(message, status)


def quantity(quarters):
    whole, part = divmod(quarters, 4)
    fraction = ('', '¼', '½', '¾')[part]
    return (str(whole) if whole else '') + fraction or '0'


def choices(maximum=MAX_QUARTERS):
    return [(str(n), quantity(n)) for n in range(1, maximum + 1)]


def approved(db, patient_id):
    """Only explicit approved schedule replacements; other decisions preserve them."""
    rows = db.execute('''SELECT p.id,p.payload_json,c.confirmed_at,p.version FROM proposals p
        JOIN doctor_confirmations c ON c.proposal_id=p.id
        JOIN care_actions a ON a.confirmation_id=c.id
        WHERE p.patient_id=? AND c.decision='approved' ORDER BY c.confirmed_at,p.version''', (patient_id,))
    return [{**dict(r), 'medications': json.loads(r['payload_json'])['medications'],
            'context': json.loads(r['payload_json']).get('medication_context', '')} for r in rows
            if 'medications' in json.loads(r['payload_json'])]


def base_id(db, patient_id):
    plans = approved(db, patient_id)
    return plans[-1]['id'] if plans else ''


def parse(form, kind):
    if form.get('med_change', 'preserve') == 'preserve':
        return None
    if form.get('med_change') != 'replace' or kind == 'referral':
        raise error('Состав препаратов можно менять только в лечебном плане, не в направлении.')
    if form.get('med_reviewed') != 'yes':
        raise error('Подтвердите проверку препаратов, дробления таблеток и расписания.')
    result = []
    for i in range(MAX_MEDICATIONS):
        prefix = f'med_{i}_'
        name = form.get(prefix + 'name', '').strip()
        values = [form.get(prefix + suffix, '').strip() for suffix in ('start', 'days')]
        slots = []
        for j in range(MAX_SLOTS):
            clock = form.get(f'{prefix}{j}_time', '').strip()
            amount = form.get(f'{prefix}{j}_qty', '').strip()
            if not clock and not amount:
                continue
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock) or not re.fullmatch(r'\d{1,2}', amount):
                raise error(f'Препарат {i+1}: у каждого приёма укажите время и количество таблеток.')
            quarters = int(amount)
            if not 1 <= quarters <= MAX_QUARTERS:
                raise error('Количество должно быть от ¼ до 20 таблеток на приём (предел формы).')
            slots.append({'time': clock, 'quarters': quarters})
        if not name and not any(values) and not slots:
            continue
        if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise error(f'Препарат {i+1}: укажите название и дозировку, до 200 символов.')
        try:
            start = date.fromisoformat(values[0])
            days = int(values[1])
            if not 1 <= days <= 366 or start < date(1900, 1, 1) or start > records.today() + timedelta(days=366):
                raise ValueError()
            end = start + timedelta(days=days-1)
        except (ValueError, OverflowError):
            raise error(f'Препарат {i+1}: проверьте дату начала и курс от 1 до 366 дней (предел формы).') from None
        if not slots or len({s['time'] for s in slots}) != len(slots):
            raise error(f'Препарат {i+1}: нужен хотя бы один приём; время приёмов не должно повторяться.')
        result.append({'name': name, 'start': start.isoformat(), 'end': end.isoformat(), 'days': days,
                       'slots': sorted(slots, key=lambda s: s['time'])})
    return result


def form_values(meds):
    result = {}
    for i, med in enumerate(meds):
        result.update({f'med_{i}_name': med['name'], f'med_{i}_start': med['start'], f'med_{i}_days': str(med['days'])})
        for j, slot in enumerate(med['slots']):
            result.update({f'med_{i}_{j}_time': slot['time'], f'med_{i}_{j}_qty': str(slot['quarters'])})
    return result


def occurrences(db, patient_id, start, end):
    """An approval activates only future scheduled instants, retaining earlier history."""
    plans = approved(db, patient_id)
    marks = {}
    for row in db.execute('''SELECT * FROM medication_marks WHERE patient_id=? AND dose_on BETWEEN ? AND ?
                            ORDER BY sequence''', (patient_id, start.isoformat(), end.isoformat())):
        marks.setdefault((row['proposal_id'], row['med_index'], row['slot_index'], row['dose_on']), []).append(dict(row))
    result = []
    for index, plan in enumerate(plans):
        active = datetime.fromisoformat(plan['confirmed_at'])
        cutoff = datetime.fromisoformat(plans[index+1]['confirmed_at']) if index+1 < len(plans) else None
        for mi, med in enumerate(plan['medications']):
            first, last = max(start, date.fromisoformat(med['start'])), min(end, date.fromisoformat(med['end']))
            for offset in range(max(0, (last-first).days + 1)):
                day = first + timedelta(days=offset)
                for si, slot in enumerate(med['slots']):
                    due = datetime.fromisoformat(day.isoformat() + 'T' + slot['time']).replace(tzinfo=MOSCOW)
                    if due < active or (cutoff and due >= cutoff):
                        continue
                    history = marks.get((plan['id'], mi, si, day.isoformat()), [])
                    last_mark = history[-1] if history else None
                    actual = last_mark['actual_quarters'] if last_mark else None
                    state = 'unknown' if actual is None else 'missed' if actual == 0 else 'taken' if actual == slot['quarters'] else 'partial'
                    result.append({'proposal_id': plan['id'], 'med_index': mi, 'slot_index': si, 'day': day.isoformat(),
                                   'name': med['name'], 'time': slot['time'], 'quarters': slot['quarters'],
                                   'amount': quantity(slot['quarters']), 'actual': actual,
                                   'actual_label': quantity(actual) if actual is not None else None,
                                   'state': state, 'label': LABELS[state], 'history': history,
                                   'revision': str(last_mark['sequence']) if last_mark else '',
                                   'future': due > datetime.fromisoformat(now()),
                                   'overdue': day < records.today() and state == 'unknown'})
    return sorted(result, key=lambda d: (d['day'], d['time'], d['name'], d['proposal_id'], d['med_index']))


def calendar(db, patient_id, day_text=None):
    try:
        selected = date.fromisoformat(day_text) if day_text else records.today()
        if not date(1900, 1, 8) <= selected <= date(9998, 12, 20):
            raise ValueError()
    except (ValueError, TypeError):
        raise error('Не удалось открыть день календаря. Выберите дату заново.') from None
    monday = selected - timedelta(days=selected.weekday())
    doses = occurrences(db, patient_id, monday, monday + timedelta(days=6))
    days = []
    for i in range(7):
        day = monday + timedelta(days=i)
        items = [d for d in doses if d['day'] == day.isoformat()]
        days.append({'date': day.isoformat(), 'number': day.day, 'weekday': ('Пн','Вт','Ср','Чт','Пт','Сб','Вс')[i],
                     'today': day == records.today(), 'selected': day == selected, 'total': len(items),
                     'taken': sum(d['state'] == 'taken' for d in items),
                     'missed': sum(d['state'] == 'missed' for d in items),
                     'partial': sum(d['state'] == 'partial' for d in items),
                     'unmarked': sum(d['overdue'] for d in items)})
    plans = approved(db, patient_id)
    # Six calendar weeks, with facts only: future doses never count as missing.
    recent_start = records.today() - timedelta(days=records.today().weekday()+35)
    recent_doses = occurrences(db, patient_id, recent_start, records.today())
    periods = []
    for offset in range(6):
        first = recent_start + timedelta(days=offset*7)
        last = min(first+timedelta(days=6), records.today())
        items = [d for d in recent_doses if first.isoformat() <= d['day'] <= last.isoformat() and not d['future']]
        gaps = [d for d in items if d['state'] in ('missed', 'partial') or d['overdue']]
        periods.append({'start': first.isoformat(), 'end': last.isoformat(), 'total': len(items),
                        'taken': sum(d['state']=='taken' for d in items),
                        'missed': sum(d['state']=='missed' for d in items),
                        'partial': sum(d['state']=='partial' for d in items),
                        'unknown': sum(d['state']=='unknown' for d in items),
                        'open_day': gaps[0]['day'] if gaps else first.isoformat()})
    return {'periods': periods, 'context': plans[-1]['context'] if plans else '', 'current_medications': plans[-1]['medications'] if plans else [], 'days': days, 'doses': [d for d in doses if d['day'] == selected.isoformat()],
            'selected': selected.isoformat(), 'start': monday.isoformat(), 'end': (monday+timedelta(days=6)).isoformat(),
            'prev': (selected-timedelta(days=7)).isoformat(), 'next': (selected+timedelta(days=7)).isoformat(),
            'today': records.today().isoformat(), 'counts': {k: sum(d['state'] == k for d in doses) for k in LABELS},
            'past_unmarked': sum(d['overdue'] for d in doses), 'has_plan': bool(plans)}


def report(db, user, patient_id, form):
    from . import communication
    token = communication.key(form)
    proposal = communication.text(form, 'proposal_id', 64)
    try:
        mi, si = int(form.get('med_index', '')), int(form.get('slot_index', ''))
        day = date.fromisoformat(form.get('dose_on', ''))
    except ValueError:
        raise error('Приём не найден. Обновите календарь.') from None
    mode = form.get('outcome')
    with transaction(db):
        r = communication.pair(db, user, patient_id)
        if user['role'] != 'patient' or r['user_id'] != user['id']:
            raise error('Отмечать приём может только сам пациент.', 403)
        dose = next((d for d in occurrences(db, patient_id, day, day)
                     if (d['proposal_id'], d['med_index'], d['slot_index']) == (proposal, mi, si)), None)
        if not dose:
            raise error('Назначение изменилось или этот приём не входит в курс. Обновите календарь.', 409)
        try:
            actual = dose['quarters'] if mode == 'taken' else 0 if mode == 'missed' else None if mode == 'unknown' else int(form.get('actual_quarters', '')) if mode == 'quantity' else -1
            if actual is not None and not 0 <= actual <= dose['quarters']:
                raise ValueError()
        except ValueError:
            raise error('Выберите фактически принятое количество из списка.') from None
        old = db.execute('SELECT * FROM medication_marks WHERE request_key=?', (token,)).fetchone()
        if old:
            if (old['patient_id'], old['actor_id'], old['proposal_id'], old['med_index'], old['slot_index'], old['dose_on'], old['actual_quarters']) != (patient_id, user['id'], proposal, mi, si, day.isoformat(), actual):
                raise error('Повторная отправка содержит другую отметку.', 409)
            return old['sequence']
        if dose['future']:
            raise error('Отметка доступна после назначенного времени по Москве.', 409)
        if form.get('revision', '') != dose['revision']:
            raise error('В другой вкладке уже есть новая отметка. Обновите календарь перед исправлением.', 409)
        cursor = db.execute('''INSERT INTO medication_marks
            (patient_id,proposal_id,med_index,slot_index,dose_on,actor_id,actual_quarters,recorded_at,request_key)
            VALUES(?,?,?,?,?,?,?,?,?)''', (patient_id, proposal, mi, si, day.isoformat(), user['id'], actual, now(), token))
        access.audit(db, user['id'], 'medication.reported', str(cursor.lastrowid))
        return cursor.lastrowid
