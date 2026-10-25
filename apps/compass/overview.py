"""Read-only row summaries for the doctor's list. Only recorded facts; nothing is scored or inferred."""
import re
from datetime import date, timedelta
from . import decisions, follow_up, records, medications

def person(code):
    """'Учебный 03 · Елена — Ухудшение и новое НЯ' -> ('Елена', 'учебный 03'); other codes are shown as they are."""
    if ' · ' in code:
        ordinal, rest = code.split(' · ', 1)
        return rest.split(' — ', 1)[0].strip() or code, ordinal.strip().lower()
    return code, ''


def years_word(years):
    if 11 <= years % 100 <= 14:
        return 'лет'
    return {1: 'год', 2: 'года', 3: 'года', 4: 'года'}.get(years % 10, 'лет')


def times_word(count):
    """2 раза, 5 раз, 21 раз, 22 раза"""
    if 11 <= count % 100 <= 14:
        return '%d раз' % count
    return '%d %s' % (count, 'раза' if count % 10 in (2, 3, 4) else 'раз')


def note_parts(text):
    """'22.10: Поле — противоречивые сведения (id)' -> (человеческий текст, id записи или None)"""
    found = re.search(r'\(([0-9a-f]{32})\)', text or '')
    return tidy(text or ''), found.group(1) if found else None


def age_text(patient):
    if patient['age_status'] == 'known' and patient['age_years'] is not None:
        return '%d %s' % (patient['age_years'], years_word(patient['age_years']))
    return 'возраст противоречив' if patient['age_status'] == 'conflicting' else 'возраст не указан'


def dm(iso):
    """2026-10-07 -> 07.10"""
    return '%s.%s' % (iso[8:10], iso[5:7]) if iso and len(iso) >= 10 else iso


def tidy(note):
    """'2026-10-22: Поле — противоречивые сведения (id).' -> '22.10: Поле — противоречивые сведения'"""
    note = re.sub(r'\s*\([0-9a-f]{32}\)', '', note).rstrip('.')
    return re.sub(r'^(\d{4})-(\d{2})-(\d{2}):', lambda m: '%s.%s:' % (m.group(3), m.group(2)), note)


def cut(text, limit):
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _marks(entries):
    """Five latest self-reports, oldest first, with the run of 'worse' ending today."""
    own = [e for e in entries if e['kind'] == 'self_report'][:5]
    values = [e['payload']['wellbeing'] for e in reversed(own)]
    streak = 0
    for value in reversed(values):
        if value != 'worse':
            break
        streak += 1
    return {'series': values, 'streak': streak, 'unknown': values.count('unknown'),
            'last_on': own[0]['observed_on'] if own else None, 'total': len([e for e in entries if e['kind'] == 'self_report'])}


def _adverse(entries):
    """The newest record that says anything about adverse events decides; older ones only give the start date."""
    for index, entry in enumerate(entries):
        field = entry['payload']['fields'].get('adverse_events', {'status': 'unknown', 'text': None})
        if field['status'] == 'unknown':
            continue
        result = {'status': field['status'], 'text': field['text'], 'on': entry['observed_on'], 'since': entry['observed_on'],
                  'entry_id': entry['id'], 'newer_silent': index > 0}
        if field['status'] in ('known', 'conflicting'):
            for older in entries[index + 1:]:
                before = older['payload']['fields'].get('adverse_events', {'status': 'unknown'})
                if before['status'] != field['status']:
                    break
                result['since'] = older['observed_on']
        return result
    return {'status': 'unknown', 'text': None, 'on': None, 'since': None, 'entry_id': None, 'newer_silent': False}


def _plan(db, user, patient_id):
    try:
        data = follow_up.view(db, user, patient_id, {})
    except decisions.DecisionError:
        return {'kind': 'none', 'counts': {}, 'due': 0}
    tasks = [t for t in data['tasks'] if not t['superseded'] and not t['future']]
    counts = {}
    for task in tasks:
        counts[task['outcome']] = counts.get(task['outcome'], 0) + 1
    return {'kind': 'tasks' if tasks else ('plan' if data['plans'] else 'none'), 'counts': counts, 'due': len(tasks)}


def summary(db, user, patient):
    patient_id = patient['id']
    entries = records.history(db, patient_id)
    marks = _marks(entries)
    adverse = _adverse(entries)
    notes = [w for w in records.warnings(patient, entries) if not w.startswith('Исходный возраст')]
    plan = _plan(db, user, patient_id)
    name, ordinal = person(patient['code'])

    reasons = []

    def reason(text, sub=None, page='card', anchor=None):
        reasons.append({'text': text, 'sub': sub, 'page': page, 'anchor': anchor})

    # A later silent report is not a withdrawal of an adverse-event description.
    # Keep the latest explicit description for each approved prescription item.
    medication_events = {}
    for entry in entries:
        for drug in entry['payload'].get('medication_feedback', []):
            identity = (drug['proposal_id'], drug['med_index'])
            if 'adverse' in drug['responses'] and identity not in medication_events:
                medication_events[identity] = entry['id']
                reason('Требует внимания: нежелательные явления',
                       cut(drug['name'] + ': ' + drug['responses']['adverse'], 160) + ' · запись от ' + dm(entry['observed_on']),
                       anchor='entry-' + entry['id'])
    if adverse['status'] == 'known' and adverse['entry_id'] not in medication_events.values():
        sub = 'запись от %s' % dm(adverse['on'])
        if adverse['since'] != adverse['on']:
            sub += ', в записях с %s' % dm(adverse['since'])
        if adverse['newer_silent']:
            sub += '; в более новых записях сведений нет'
        reason('Записано нежелательное явление', cut(adverse['text'] or '', 120).rstrip('.') + '. ' + sub.capitalize(), anchor='entry-' + adverse['entry_id'])
    if notes:
        reason('Сверить противоречивые сведения', cut(tidy(notes[0]), 120), anchor='warnings')
    elif adverse['status'] == 'conflicting':
        reason('Сверить сведения о нежелательном явлении', 'В записях есть противоречие.', anchor='entry-' + adverse['entry_id'])
    if plan['counts'].get('conflicting'):
        reason('Сверить выполнение плана', 'Отметки о выполнении расходятся.', page='plan', anchor='fu-plan')
    if marks['streak'] >= 2:
        reason('Самочувствие хуже %s подряд' % times_word(marks['streak']), 'По последним отметкам пациента.', anchor='records')
    open_items = plan['counts'].get('missed', 0) + plan['counts'].get('unknown', 0)
    if open_items:
        missed = plan['counts'].get('missed', 0)
        unknown = plan['counts'].get('unknown', 0)
        parts = []
        if missed:
            parts.append('Отмечено пропусков: %d' % missed)
        if unknown:
            parts.append('Без отметки: %d' % unknown)
        reason('Есть пропуски в плане' if missed else 'Не отмечено выполнение плана',
               '; '.join(parts) + '.', page='plan', anchor='fu-plan')

    med_doses = medications.occurrences(db, patient_id, records.today()-timedelta(days=6), records.today())
    med_gaps = [d for d in med_doses if d['state'] in ('missed', 'partial') or d['overdue']]
    if med_gaps:
        missed = sum(d['state'] == 'missed' for d in med_gaps)
        partial = sum(d['state'] == 'partial' for d in med_gaps)
        unknown = sum(d['overdue'] for d in med_gaps)
        reason('Проверить приём препаратов', f'За 7 дней: пропущено {missed}, частично {partial}, без отметки {unknown}.',
               anchor='medications', page='plan')
        reasons[-1]['med_day'] = med_gaps[0]['day']

    if marks['total'] == 0:
        quiet = {'text': 'Отметок самочувствия пока нет', 'sub': None, 'page': 'card', 'anchor': 'records'}
    else:
        ago = (records.today() - date.fromisoformat(marks['last_on'])).days
        quiet = {'text': 'Последняя отметка %s' % dm(marks['last_on']),
                 'sub': ('сегодня' if ago == 0 else '%d дн. назад' % ago) + ', всего отметок: %d' % marks['total'],
                 'page': 'card', 'anchor': 'records'}
    return {'id': patient_id, 'name': name, 'ordinal': ordinal, 'age': age_text(patient), 'marks': marks,
            'adverse': adverse, 'plan': plan,
            'attention': bool(reasons), 'reason': reasons[0] if reasons else quiet, 'more': reasons[1:]}


def rows(db, user, patients):
    result = [summary(db, user, p) for p in patients]
    # Reasons for checking first; preserve alphabetical order within each group.
    return sorted(result, key=lambda r: not r['attention'])
