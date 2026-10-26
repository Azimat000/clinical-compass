"""Lossless structured source adapters. No NLP, inference or clinical decisions."""
import hashlib
import json

from . import decisions, first_visits

VERSION = 'patient-history-v2'
PAGE_SIZE = 50
CATEGORIES = ('questionnaires', 'wellbeing', 'anamnesis', 'visits', 'medication_actual',
              'plans', 'context')


def digest(value):
    return hashlib.sha256(decisions.canonical(value).encode()).hexdigest()


def enrich(db, raw, patient_id):
    """Called in the analysis transaction; retain the BE01 raw snapshot verbatim."""
    # Original decision snapshots intentionally omit proposal content. Analyses need
    # the actual prescribed text and response author, not just an action id.
    for table, query in (
        ('assessment_requests', 'SELECT * FROM assessment_requests WHERE patient_id=? ORDER BY id'),
        ('proposals', 'SELECT * FROM proposals WHERE patient_id=? ORDER BY id'),
        ('doctor_confirmations', '''SELECT c.* FROM doctor_confirmations c JOIN proposals p
            ON p.id=c.proposal_id WHERE p.patient_id=? ORDER BY c.id'''),
        ('decision_drafts', '''SELECT d.* FROM decision_drafts d JOIN proposals p
            ON p.id=d.proposal_id WHERE p.patient_id=? ORDER BY d.proposal_id'''),
    ):
        raw[table] = [dict(r) for r in db.execute(query, (patient_id,))]
    entries = []
    sources = {}

    def source(table, row, key='id'):
        # A content-addressed reference includes the table and exact row revision.
        ref = 's2_' + digest([table, row[key], row])
        sources[ref] = {'table': table, 'key': key, 'id': row[key], 'sha256': digest(row)}
        return ref

    def item(table, row, category, event_at=None, recorded_at=None, author_id=None,
             version=1, current=True, state='recorded', key='id', related=()):
        ref = source(table, row, key)
        value = {'ref': ref, 'category': category, 'event_at': event_at,
                 'recorded_at': recorded_at, 'author_id': author_id, 'version': version,
                 'current_revision': current, 'state': state, 'related_refs': list(related),
                 'supersedes_ref': None, 'fields': [], 'issues': []}
        value['temporal_scope'] = ('unknown' if event_at is None else
                                   'historical' if event_at[:10] < raw['day'] else
                                   'on_snapshot_day' if event_at[:10] == raw['day'] else 'future')
        entries.append(value)
        return value

    def field(entry, path, value, *, code, status=None, event_at=None, context='current',
              origin=None, basis=None, carried_from=None):
        # The path addresses the decoded JSON value in the frozen source row.
        entry['fields'].append({'path': path, 'value': value, 'code': code,
                                'source_ref': entry['ref'],
                                'status': status if status is not None else ('unknown' if value in (None, '') else 'known'),
                                'event_at': event_at or entry['event_at'], 'context': context,
                                'origin': origin, 'basis': basis, 'carried_from': carried_from})

    patient = raw['patients'][0]
    profile = item('patients', patient, 'context', patient['created_at'][:10], patient['created_at'])
    field(profile, '/age_status', patient['age_status'], code='age_status', status=patient['age_status'])
    field(profile, '/birth_date', patient['birth_date'], code='birth_date')
    field(profile, '/age_years', patient['age_years'], code='age_years')

    results = {r['assessment_id']: r for r in raw['assessment_results']}
    requests = {r['id']: r for r in raw['assessment_requests']}
    for row in raw['assessments']:
        result = results.get(row['id'])
        related = []
        if result:
            related.append(source('assessment_results', result, 'assessment_id'))
            request = requests.get(result['request_id'])
            if request:
                related.append(source('assessment_requests', request))
        entry = item('assessments', row, 'questionnaires',
                     result['observed_on'] if result else row['completed_at'],
                     result['recorded_at'] if result else None,
                     result['actor_id'] if result else None, row['scoring_version'],
                     state=row['completeness'], related=related)
        field(entry, '/answers_json', json.loads(row['answers_json']), code='answers')
        field(entry, '/score', row['score'], code='legacy_score')
        field(entry, '/scale_version_id', row['scale_version_id'], code='form_version')
        if result:
            # Related-row fields carry their own source reference explicitly.
            field(entry, '/scores_json', json.loads(result['scores_json']) if result['scores_json'] else None,
                  code='scores')
            entry['fields'][-1]['source_ref'] = related[0]
        if not result:
            entry['issues'].append('legacy_response_author_and_recorded_time_unknown')

    linked_reports, linked_encounters = set(), set()
    for row in raw['clinical_entries']:
        payload = json.loads(row['payload_json'])
        related = []
        for table, column, linked in [('self_reports', 'self_report_id', linked_reports),
                                      ('encounters', 'encounter_id', linked_encounters)]:
            if row[column]:
                linked.add(row[column])
                related.extend(source(table, r) for r in raw[table] if r['id'] == row[column])
        entry = item('clinical_entries', row, 'wellbeing' if row['kind'] == 'self_report' else 'visits',
                     row['observed_on'], row['recorded_at'], row['actor_id'], related=related)
        if 'summary' in payload:
            field(entry, '/payload_json/summary', payload['summary'], code='summary')
        for code, fact in payload.get('fields', {}).items():
            field(entry, '/payload_json/fields/' + code + '/text', fact.get('text'), code=code,
                  status=fact['status'], origin=row['kind'])
        for code in ('age', 'wellbeing', 'medication_feedback', 'medication_safety'):
            if code in payload:
                value = payload[code]
                field(entry, '/payload_json/' + code, value, code=code,
                      status=value.get('status') if isinstance(value, dict) and code == 'age' else
                      'unknown' if code == 'wellbeing' and value == 'unknown' else None)

    for row in raw['self_reports']:
        if row['id'] not in linked_reports:
            entry = item('self_reports', row, 'wellbeing', row['reported_at'], row['received_at'],
                         version=row['schema_version'])
            field(entry, '/payload_json', json.loads(row['payload_json']), code='legacy_report')
            entry['issues'].append('legacy_response_author_unknown')
    for row in raw['encounters']:
        if row['id'] not in linked_encounters:
            entry = item('encounters', row, 'visits', row['occurred_at'], author_id=row['author_id'],
                         version=row['schema_version'])
            field(entry, '/narrative', row['narrative'], code='narrative', origin=row['origin'])
            entry['issues'].append('recorded_time_unknown')

    versions = raw.get('first_visit_versions', [])
    latest = {}
    for row in versions:
        latest[row['visit_id']] = max(latest.get(row['visit_id'], 0), row['revision'])
    by_version = {(r['visit_id'], r['revision']): r for r in versions}
    for row in versions:
        payload = json.loads(row['payload_json'])
        entry = item('first_visit_versions', row, 'visits', payload['observed_on'], row['recorded_at'],
                     row['actor_id'], row['revision'], row['revision'] == latest[row['visit_id']], row['state'])
        previous = by_version.get((row['visit_id'], row['revision'] - 1))
        if previous:
            entry['supersedes_ref'] = source('first_visit_versions', previous)
        for code, fact in payload['fields'].items():
            field(entry, '/payload_json/fields/' + code + '/text', fact.get('text'), code=code,
                  status=fact['status'], event_at=fact['observed_on'],
                  context='cumulative_history' if code in first_visits.STATIC_FIELDS else 'current',
                  origin=fact['source'], basis=fact['basis'], carried_from=fact.get('carried_from'))
        for code in ('age', 'wellbeing', 'documented_facts', 'document_basis', 'action_draft'):
            if code in payload:
                value = payload[code]
                field(entry, '/payload_json/' + code, value, code=code,
                      status=value.get('status') if code == 'age' else
                      'unknown' if code == 'wellbeing' and value == 'unknown' else None,
                      event_at=payload.get('age_observed_on') if code == 'age' else None,
                      carried_from=payload.get('age_carried_from') if code == 'age' else None)
        # The anamnesis is a view of these same exact versioned fields, never a
        # separately authored record. Both views point to one frozen source.
        history_fields = [f for f in entry['fields'] if f['context'] == 'cumulative_history']
        if history_fields:
            entries.append({**entry, 'category': 'anamnesis', 'fields': history_fields})

    confirmations = {r['proposal_id']: r for r in raw['doctor_confirmations']}
    drafts = {r['proposal_id']: r for r in raw['decision_drafts']}
    actions = {r['proposal_id']: r for r in raw['actions']}
    med_plans = []
    for row in raw['proposals']:
        confirmation, action = confirmations.get(row['id']), actions.get(row['id'])
        related = []
        if confirmation:
            related.append(source('doctor_confirmations', confirmation))
        if action:
            related.append(source('actions', action))
        draft = drafts.get(row['id'])
        if draft:
            related.append(source('decision_drafts', draft, 'proposal_id'))
        state = ('applied' if action else confirmation['decision']) if confirmation else row['status']
        entry = item('proposals', row, 'plans', action['effective_at'] if action else row['created_at'],
                     row['created_at'], draft['actor_id'] if draft else None,
                     row['version'], state=state, related=related)
        field(entry, '/payload_json', json.loads(row['payload_json']), code='prescription',
              context='prescribed_only')
        if action and 'medications' in json.loads(row['payload_json']):
            med_plans.append((confirmation['confirmed_at'], row['version'], entry['ref']))
    active_medication_plan = max(med_plans)[2] if med_plans else None
    applied = [e for e in entries if e['category'] == 'plans' and e['state'] == 'applied']
    active_plan = max(applied, key=lambda e: e['version'])['ref'] if applied else None

    for row in raw['therapy_courses']:
        entry = item('therapy_courses', row, 'context', row['starts_at'], state='legacy_prescription')
        field(entry, '/schedule_json', json.loads(row['schedule_json']), code='legacy_schedule', context='prescribed_only')
        field(entry, '/drug_version_id', row['drug_version_id'], code='drug_version', context='prescribed_only')

    marks = raw.get('medication_marks', [])
    last_mark = {}
    for row in marks:
        key = tuple(row[k] for k in ('proposal_id', 'med_index', 'slot_index', 'dose_on'))
        last_mark[key] = max(last_mark.get(key, 0), row['sequence'])
    previous_mark = {}
    for row in sorted(marks, key=lambda r: r['sequence']):
        key = tuple(row[k] for k in ('proposal_id', 'med_index', 'slot_index', 'dose_on'))
        entry = item('medication_marks', row, 'medication_actual', row['dose_on'], row['recorded_at'],
                     row['actor_id'], row['sequence'], row['sequence'] == last_mark[key], key='sequence')
        entry['supersedes_ref'] = previous_mark.get(key)
        previous_mark[key] = entry['ref']
        field(entry, '/actual_quarters', row['actual_quarters'], code='actual_quarters', context='reported_intake')

    # Supplemental legacy facts retain their provenance; projections already
    # represented by a clinical entry are related sources rather than extra events.
    clinical_parents = {sources[e['ref']]['id']: e for e in entries
                        if sources[e['ref']]['table'] == 'clinical_entries'}
    for row in raw['observations']:
        provenance = json.loads(row['provenance_json'])
        parent = clinical_parents.get(provenance.get('entry_id'))
        if parent:
            parent['related_refs'].append(source('observations', row))
            continue
        historical = row['code'] in first_visits.STATIC_FIELDS
        entry = item('observations', row, 'anamnesis' if historical else 'context', row['observed_at'], row['recorded_at'], provenance.get('actor_id'))
        field(entry, '/value_json', json.loads(row['value_json']) if row['value_json'] else None,
              code=row['code'], status=row['data_status'], origin=provenance,
              context='cumulative_history' if historical else 'current')

    # Flag only explicit statuses or different structured values on the same day.
    # Text meaning/negation extraction belongs to BE05; no semantic guess here.
    grouped = {}
    for entry in entries:
        if entry['category'] in ('anamnesis', 'questionnaires') or not entry['current_revision']:
            continue
        for fact in entry['fields']:
            if fact['status'] == 'conflicting':
                entry['issues'].append('explicit_conflict:' + fact['code'])
            if (fact['code'] not in ('summary', 'narrative', 'legacy_report')
                    and fact['status'] in ('known', 'denied')
                    and fact['context'] == 'current' and fact['event_at']):
                key = (fact['event_at'][:10], fact['code'])
                grouped.setdefault(key, []).append((entry, fact))
    for group in grouped.values():
        if len({decisions.canonical([f['status'], f['value']]) for _, f in group}) > 1:
            for entry, fact in group:
                entry['issues'].append('same_day_disagreement:' + fact['code'])

    entries.sort(key=lambda e: (e['event_at'] or '', e['recorded_at'] or '', e['ref'], e['category']))
    for entry in entries:
        entry['issues'] = sorted(set(entry['issues']))
        entry['related_refs'] = sorted(set(entry['related_refs']))
    counts = {category: sum(e['category'] == category for e in entries) for category in CATEGORIES}
    return {'version': VERSION, 'complete': True, 'truncated': False, 'counts': counts,
            'entry_count': len(entries), 'page_size': PAGE_SIZE,
            'missing_categories': [c for c in CATEGORIES[:4] if counts[c] == 0],
            'active_medication_plan_ref': active_medication_plan,
            'active_plan_ref': active_plan,
            'sources': sources, 'entries': entries}


def resolve(snapshot, reference):
    """Resolve against frozen rows only; never fall through to live patient data."""
    meta = snapshot.get('patient_history', {}).get('sources', {}).get(reference)
    if meta is None:
        return None
    row = next((r for r in snapshot.get(meta['table'], []) if r[meta['key']] == meta['id']), None)
    if row is None or digest(row) != meta['sha256']:
        raise ValueError('Snapshot integrity mismatch')
    return {'ref': reference, **meta, 'row': row}
