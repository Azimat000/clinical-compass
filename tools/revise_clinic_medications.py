"""Re-author only the identified S55 fictional fixture into a NEW private database.

No live UPDATE, trigger removal, clinical rule release or real patient support.
All identities/IDs/auth state survive; historical source remains in its snapshot.
New text/dates/amounts are authored fiction, not physician review or prescribing.
"""
import argparse
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import db as database, decisions, medications

DATA = ROOT / 'data/fictional/clinic-medications-20261026.json'
ORIGINAL = ROOT / 'data/fictional/clinic-20261026.json'
EVENT = 'fictional.medication_history_reauthored'
EXPECTED = dict(users=12, patients=10, care_relationships=10, clinical_entries=70,
                first_visit_versions=91, assessments=90, assessment_requests=120,
                proposals=34, doctor_confirmations=32, care_actions=31,
                adherence_tasks=90, adherence_entries=71, medication_marks=227,
                text_imports=10, extraction_reviews=21, messages=140,
                self_report_drafts=1, clinical_rule_evaluations=0, critical_events=0)
INDEXES = {
    'encounter_search': 'INSERT INTO encounter_search(encounter_id,narrative) SELECT id,narrative FROM encounters',
    'clinical_entry_search': "INSERT INTO clinical_entry_search(entry_id,body) SELECT id,summary || ' ' || payload_json FROM clinical_entries",
    'import_search': 'INSERT INTO import_search(import_id,body) SELECT id,source_text FROM text_imports',
    'patient_search': "INSERT INTO patient_search(patient_id,label) SELECT id,id || ' ' || code FROM patients",
}


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def load():
    data = json.loads(DATA.read_text())
    assert data['source_dataset_sha256'] == digest(ORIGINAL.read_bytes())
    assert data['provenance'] == dict(synthetic=True, simulated_dates=True,
        clinical_review=False, real_user_trial=False, medication_eligibility_established=False)
    assert set(data['plans']) == {'P201', 'P202', 'P203', 'P204', 'P207', 'P208'}
    return data


def original_guard(db, data):
    if db.execute('SELECT 1 FROM patients WHERE synthetic<>1').fetchone():
        raise ValueError('Real or unrecognized patients are forbidden')
    origins = db.execute("SELECT * FROM audit_entries WHERE event='fictional.roster_loaded'").fetchall()
    if len(origins) != 1 or db.execute('SELECT 1 FROM audit_entries WHERE event=?', (EVENT,)).fetchone():
        raise ValueError('Expected one unrevised S55 fixture')
    origin = json.loads(origins[0]['metadata_json'])
    if (origin.get('dataset_version') != 'clinic-roster-20261026-v1'
            or origin.get('dataset_sha256') != data['source_dataset_sha256']
            or not origin.get('synthetic') or not origin.get('simulated_dates')
            or origin.get('clinical_review') is not False or origin.get('real_user_trial') is not False
            or origin.get('observation_start') != '2026-09-14'):
        raise ValueError('Unrecognized authored source')
    for table, count in EXPECTED.items():
        if db.execute('SELECT count(*) FROM '+table).fetchone()[0] != count:
            raise ValueError('New user/clinical information must be preserved separately: '+table)
    if db.execute("SELECT 1 FROM audit_entries WHERE occurred_at>? AND event NOT LIKE 'auth.%'",
                  (origins[0]['occurred_at'],)).fetchone():
        raise ValueError('Post-fixture user work exists; refusing to re-author it')
    original = json.loads(ORIGINAL.read_text())
    for p in original['patients']:
        person = db.execute('SELECT * FROM patients WHERE id=?', (p['id'],)).fetchone()
        if not person or (person['code'], person['user_id']) != (p['name'], p['login']):
            raise ValueError('Identity differs from S55')
        rows = db.execute('SELECT summary FROM clinical_entries WHERE patient_id=? ORDER BY observed_on', (p['id'],)).fetchall()
        if [r[0] for r in rows] != p['diary']:
            raise ValueError('Authored diary differs; refusing to overwrite')
    return origin


def schedule(meds):
    result = []
    for med in meds:
        first, last = date.fromisoformat(med['start']), date.fromisoformat(med['end'])
        result.append(dict(**med, days=(last-first).days+1))
    return result


def plan_text(meds):
    if not meds:
        return 'В текущем составе препаратов нет.'
    result = []
    for med in meds:
        amount = '½ таблетки' if med['slots'][0]['quarters'] == 2 else '1 таблетка'
        result.append(f"{med['name']}: {amount} в08:00, {med['start']}–{med['end']}.")
    return ' '.join(result).replace('в08', 'в 08')


def transform(rows, data):
    replacements = {**data['text_replacements'],
        'Препарат А, таблетки': data['medicines']['elicea10'],
        'Препарат Б, таблетки': data['medicines']['aleval50']}

    def strings(value):
        if isinstance(value, dict):
            return {k: strings(v) for k, v in value.items()}
        if isinstance(value, list):
            return [strings(v) for v in value]
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
        return value

    proposals = {r['id']: r for r in rows['proposals']}
    for row in rows['proposals']:
        pid, version = row['patient_id'], str(row['version'])
        payload = strings(json.loads(row['payload_json']))
        if version in data['plans'].get(pid, {}):
            payload['medications'] = schedule(data['plans'][pid][version])
            payload['medication_source_basis'] = [s['id'] for s in data['sources']]
            payload['individual_eligibility_verified'] = False
            payload['content'] += '\n' + plan_text(payload['medications'])
        row['kind'] = data['kind_overrides'].get(pid, {}).get(version, row['kind'])
        payload['kind'] = row['kind']
        if pid == 'P204' and version == '2':
            payload['content'] += ' Изменение касается дозы того же сертралина; замены на эсциталопрам нет.'
        if pid == 'P207' and version == '2':
            payload['content'] = ('После обсуждения сонливости согласовано постепенное завершение Элицеи. '
                + plan_text(payload['medications']) + ' С 19.10.2026 препарат не принимать. '
                'Дневник сна и дневного самочувствия продолжить; причинность сонливости не установлена.')
        if pid == 'P207' and version == '3':
            payload['content'] = ('Продолжить дневник во время снижения: Элицея 5 мг 06–18.10.2026, '
                'с 19.10.2026 без препарата по отдельному подтверждённому решению. '
                'Подготовить полный список прежних и сопутствующих назначений.')
        row['payload_json'] = canonical(payload)
    # A stop recorded at the final visit retains the same physician's fictional review.
    stop = next(r for r in rows['proposals'] if r['patient_id']=='P207' and r['version']==4)
    prior = next(r for r in rows['proposals'] if r['patient_id']=='P207' and r['version']==2)
    value = json.loads(stop['payload_json'])
    value['therapy_review'] = json.loads(prior['payload_json'])['therapy_review']
    value['content'] = ('Снижение Элицеи завершено 18.10.2026, с 19.10.2026 приёма нет. '
        'Текущий состав препаратов пуст. Продолжить дневник и уточнение причин дневной сонливости.')
    stop['payload_json'] = canonical(value)

    for table in ('first_visit_versions', 'clinical_entries', 'self_reports', 'observations', 'adverse_events', 'messages'):
        for row in rows[table]:
            for name, value in list(row.items()):
                if name.endswith('_json') and isinstance(value, str):
                    parsed = json.loads(value)
                    revised = strings(parsed)
                    if revised != parsed:
                        row[name] = canonical(revised)
                elif name in ('summary', 'description', 'body'):
                    row[name] = strings(value)

    def active(proposal, day):
        meds = json.loads(proposals[proposal]['payload_json']).get('medications', [])
        found = [(i, m) for i, m in enumerate(meds) if m['start'] <= day <= m['end']]
        if len(found) != 1:
            raise ValueError('Expected one exact medication phase: '+day+' '+proposal)
        return found[0]

    # Resolve every report's label/index from its own immutable proposal and date.
    for row in rows['clinical_entries']:
        payload = json.loads(row['payload_json'])
        previous_payload = json.loads(row['payload_json'])
        for item in payload.get('medication_feedback', []):
            index, med = active(item['proposal_id'], row['observed_on'])
            item.update(med_index=index, name=med['name'])
        if row['patient_id']=='P207' and row['observed_on']=='2026-10-12':
            payload['medication_feedback_plan'] = prior['id']
            payload['medication_feedback'] = [dict(proposal_id=prior['id'],med_index=0,
                name=data['medicines']['elicea10'],responses={'no_effect':
                'Принимаю согласованные 5 мг во время снижения; оценивать устойчивое изменение самочувствия пока рано.'})]
        if payload != previous_payload:
            row['payload_json'] = canonical(payload)
    reports = {r['self_report_id']: r for r in rows['clinical_entries']}
    for row in rows['self_reports']:
        row['payload_json'] = reports[row['id']]['payload_json']
        # The authoring edition uses the existing feedback-aware persisted format.
        if json.loads(row['payload_json']).get('medication_feedback'):
            row['schema_version'] = 4

    for row in rows['medication_marks']:
        row['med_index'], med = active(row['proposal_id'], row['dose_on'])
        if row['actual_quarters'] is not None and row['actual_quarters'] > med['slots'][0]['quarters']:
            raise ValueError('Existing actual quantity exceeds revised prescription')
    sequence = max(r['sequence'] for r in rows['medication_marks'])
    added = []
    for offset in range(13):
        day = date(2026,10,6)+timedelta(days=offset)
        sequence += 1
        added.append(dict(sequence=sequence, patient_id='P207', proposal_id=prior['id'],med_index=0,slot_index=0,
            dose_on=day.isoformat(),actor_id='irina.savina',actual_quarters=2,
            recorded_at=day.isoformat()+'T09:00:00.000000+00:00',
            request_key=digest(('S56:P207:'+day.isoformat()).encode())[:32]))
    rows['medication_marks'].extend(added)

    # Preserve the exact set of observations/people present at each old decision;
    # replace their content with the corresponding re-authored persisted rows.
    def identity(row):
        for field in ('id', 'sequence'):
            if field in row:
                return field, row[field]
        return None
    lookup = {table: {identity(r): r for r in records if identity(r)} for table, records in rows.items()}
    for row in rows['proposals']:
        snapshot = json.loads(row['input_snapshot_json'])
        for table, values in snapshot.items():
            if table in lookup and isinstance(values, list):
                snapshot[table] = [lookup[table].get(identity(v), strings(v)) for v in values]
        if row['patient_id']=='P207':
            eligible = [r for r in added if r['recorded_at'] <= row['created_at']]
            if eligible:
                snapshot.setdefault('medication_marks', []).extend(eligible)
                snapshot['medication_marks'].sort(key=lambda r:r['sequence'])
        row['input_snapshot_json'] = canonical(snapshot)
    return added


def build(source_path, target_path):
    data = load()
    source_path, target_path = Path(source_path).resolve(), Path(target_path).resolve()
    if not source_path.is_file() or source_path == target_path or target_path.exists():
        raise ValueError('Existing source and NEW distinct output are required')
    before_hash = digest(source_path.read_bytes())
    created = False
    try:
        with closing(sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)) as source:
            source.row_factory = sqlite3.Row
            source.execute('BEGIN')
            original_guard(source, data)
            types = {r['name']: r['type'] for r in source.execute('PRAGMA table_list')}
            schema = [dict(r) for r in source.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY rowid")]
            tables = [s for s in schema if s['type']=='table' and types.get(s['name'])=='table' and not s['name'].startswith('sqlite_')]
            rows = {s['name']:[dict(r) for r in source.execute('SELECT * FROM '+quoted(s['name']))] for s in tables}
            original_rows = json.loads(json.dumps(rows))
            sequences = [tuple(r) for r in source.execute('SELECT * FROM sqlite_sequence')]
            added = transform(rows, data)
            changed = {table:sum(a!=b for a,b in zip(original_rows[table],items))
                       for table, items in rows.items() if original_rows[table]!=items}
            for table in ('users','patients','care_relationships','source_versions','catalog_versions','assessment_form_releases',
                          'doctor_confirmations','care_actions','text_imports','extraction_reviews','audit_entries','self_report_drafts'):
                assert rows[table]==original_rows[table], table
            target_path.parent.mkdir(parents=True,exist_ok=True)
            target_path.touch(mode=0o600,exist_ok=False)
            created = True
            with closing(sqlite3.connect(target_path,isolation_level=None)) as target:
                target.execute('PRAGMA journal_mode=DELETE')
                target.execute('BEGIN IMMEDIATE')
                for table in tables:
                    target.execute(table['sql'])
                    items = rows[table['name']]
                    if items:
                        columns = list(items[0])
                        sql = 'INSERT INTO '+quoted(table['name'])+'('+','.join(map(quoted,columns))+') VALUES('+','.join('?' for _ in columns)+')'
                        target.executemany(sql, [tuple(r[c] for c in columns) for r in items])
                # Keep monotonic AUTOINCREMENT state, including retired sequence gaps.
                for name, seq in sequences:
                    current = target.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(name,)).fetchone()
                    if current and current[0] < seq:
                        target.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?',(seq,name))
                for item in schema:
                    if item['type']=='table' and types.get(item['name'])=='virtual':
                        assert item['name'] in INDEXES
                        target.execute(item['sql'])
                        target.execute(INDEXES[item['name']])
                for item in schema:
                    if item['type'] in ('index','trigger'):
                        target.execute(item['sql'])
                target.execute('COMMIT')
                target.execute('PRAGMA foreign_keys=ON')
                assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not target.execute('PRAGMA foreign_key_check').fetchall()
                for name in INDEXES:
                    target.execute('INSERT INTO '+quoted(name)+'('+quoted(name)+") VALUES('integrity-check')")
                expected = [(r['name'],r['sql']) for r in schema if r['type']=='trigger']
                actual = list(target.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid"))
                assert expected == actual
                provenance = dict(**data['provenance'],revision=data['version'],
                    actual_reauthored_at=database.now(),source_database_sha256=before_hash,
                    authoring_file_sha256=digest(DATA.read_bytes()),source_dataset_sha256=data['source_dataset_sha256'],
                    source_documents=data['sources'],changed_rows=changed,added_synthetic_marks=len(added),
                    preserved_ids=True,source_history_retained_offline=True,active_clinical_rules=False,
                    primary_source_verification='product facts only; not individual clinical validation')
                for mark in added:
                    target.execute('INSERT INTO audit_entries(actor_id,event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?,?)',
                        (mark['actor_id'],'medication.reported',str(mark['sequence']),mark['recorded_at'],canonical(dict(
                            synthetic=True,simulated_dates=True,authored_revision=data['version'],
                            actual_reauthored_at=provenance['actual_reauthored_at']))))
                target.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                    (EVENT,data['version'],database.now(),json.dumps(provenance,ensure_ascii=False)))
            assert digest(source_path.read_bytes())==before_hash, 'Source changed during reconstruction'
    except BaseException:
        if created:
            target_path.unlink(missing_ok=True)
        raise
    return dict(status='BUILT',database=str(target_path),**provenance)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.source,args.output),ensure_ascii=False,indent=2))
