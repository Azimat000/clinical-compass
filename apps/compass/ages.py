"""Read-only age applicability from recorded sources; no reconciliation workflow."""
from datetime import date
import hashlib
import json
from . import records


class AgeError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def source_snapshot(db, patient):
    sources = [{'id': 'profile:' + patient['id'], 'observed_on': patient['created_at'][:10],
                'age': {'status': patient['age_status'], 'years': patient['age_years'],
                        'birth_date': patient['birth_date']}}]
    for entry in reversed(records.history(db, patient['id'])):
        if entry['payload']['age']['status'] != 'unknown':
            sources.append({'id': entry['id'], 'actor_id': entry['actor_id'], 'kind': entry['kind'],
                            'observed_on': entry['observed_on'], 'recorded_at': entry['recorded_at'],
                            'age': entry['payload']['age']})
    # First-visit notes are independent append-only sources, including drafts.
    # New sources invalidate outstanding forms.
    for row in db.execute('SELECT * FROM first_visit_versions WHERE patient_id=? ORDER BY rowid', (patient['id'],)):
        payload = json.loads(row['payload_json'])
        sources.append({'id': row['id'], 'actor_id': row['actor_id'], 'kind': 'first_visit',
                        'observed_on': payload['observed_on'], 'recorded_at': row['recorded_at'],
                        'age': payload['age']})
    return canonical(sources)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def view(db, patient):
    snapshot = source_snapshot(db, patient)
    return {'sources': json.loads(snapshot), 'fingerprint': digest(snapshot)}


def years_on(birth, on):
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def possible_years(source, on):
    """An integer at an earlier observation gives a range; a DOB gives an exact age."""
    age = source['age']
    if age['status'] == 'conflicting':
        raise AgeError('Возрастная применимость не установлена: сведения противоречивы.')
    try:
        observed = date.fromisoformat(source['observed_on'])
        if observed > on:
            raise ValueError()
        birth = date.fromisoformat(age['birth_date']) if age.get('birth_date') else None
        years = age.get('years')
        if birth:
            old = years_on(birth, observed)
            current = years_on(birth, on)
            if birth > observed or birth.year < 1900 or not 0 <= current <= 120 or (years is not None and years != old):
                raise ValueError()
            return {current}
        if years is None:
            if age['status'] == 'known':
                raise ValueError()
            return None
        if age['status'] != 'known' or type(years) is not int or not 0 <= years <= 120:
            raise ValueError()
        delta = years_on(observed, on)
        low = years + delta
        return {low} if (observed.month, observed.day) == (on.month, on.day) else {low, low + 1}
    except (ValueError, TypeError):
        raise AgeError('Возрастная применимость не установлена: некорректные сведения о возрасте.') from None


def verify(db, patient, years):
    state = view(db, patient)
    allowed = set(range(121))
    for source in state['sources']:
        candidates = possible_years(source, records.today())
        if candidates is not None:
            allowed &= candidates
    if years not in allowed:
        raise AgeError('Возрастная применимость не установлена: возраст расходится с записями.')
    # Keep the existing token format for outstanding requests without a review.
    return digest(canonical({'sources': state['fingerprint'], 'review': None}))
