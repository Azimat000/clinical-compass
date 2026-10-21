"""Read models and idempotent, synthetic-only seed."""
import json
from pathlib import Path
from .db import now, transaction
from .events import enqueue

DATASET = Path(__file__).resolve().parents[2] / 'data' / 'synthetic' / 'cases.json'


def seed_demo(db):
    dataset = json.loads(DATASET.read_text())
    if dataset['provenance']['synthetic'] is not True or dataset['provenance']['active'] is not False:
        raise ValueError('Only inactive synthetic input is allowed')
    with transaction(db):
        for index, case in enumerate(dataset['cases'], start=1):
            if case['provenance']['synthetic'] is not True or case['provenance']['active'] is not False:
                raise ValueError('Only inactive synthetic cases are allowed')
            code = case['id']
            if db.execute('SELECT 1 FROM patients WHERE id=?', (code,)).fetchone():
                continue
            stamp = now()
            # Original dataset remains untouched; no medical drafts are activated.
            age = case['profile'].get('age_years')
            age_status = 'conflicting' if case['profile'].get('age_reports') else ('known' if age is not None else 'unknown')
            db.execute('INSERT INTO patients(id,code,age_years,age_status,synthetic,created_at) VALUES(?,?,?,?,?,?)',
                       (code, f'Демо {index:02d}', age, age_status, 1, stamp))
            db.execute('INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES(?,?,?,?,?)',
                       (f'{code}-initial', code, stamp, case['title'] + '. Клиническое заключение не утверждено.', 'S03-v1 / ' + code))
            db.execute('INSERT INTO observations(id,patient_id,encounter_id,code,value_json,data_status,observed_at,recorded_at,provenance_json) VALUES(?,?,?,?,?,?,?,?,?)',
                       (f'{code}-profile', code, f'{code}-initial', 'synthetic_profile_snapshot',
                        json.dumps(case['profile'], ensure_ascii=False), 'known', stamp, stamp,
                        json.dumps({'dataset': dataset['dataset_version'], 'case_id': code, 'clinical_review_status': 'not_reviewed'})))
            enqueue(db, 'demo.patient_created.v1', code, {'patient_id': code, 'synthetic': True})
            db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                       ('demo.seeded', code, stamp, json.dumps({'synthetic': True})))


PENDING_SIGNAL_SQL = '''SELECT 1 FROM critical_events c LEFT JOIN critical_delivery d ON d.event_id=c.id
    JOIN care_relationships r ON r.id=c.relationship_id
    WHERE c.patient_id=p.id AND d.reacted_at IS NULL AND c.recipient_id=?
    AND r.doctor_id=c.recipient_id AND r.ends_at IS NULL AND r.starts_at<=?'''


def patient_list(db, query='', age_status='', doctor_id=None, record_kind='', route_category='', attention='', signals_first=False):
    if age_status not in ('', 'known', 'unknown', 'conflicting') or record_kind not in ('', 'self_report', 'visit') or route_category not in ('', 'mandatory', 'desirable') or attention not in ('', 'pending'):
        raise ValueError('Invalid patient filter')
    sql = 'SELECT p.* FROM patients p WHERE 1=1'
    params = []
    if doctor_id is not None:
        sql += ' AND EXISTS (SELECT 1 FROM care_relationships r WHERE r.patient_id=p.id AND r.doctor_id=? AND r.ends_at IS NULL AND r.starts_at<=?)'
        params += [doctor_id, now()]
    if query:
        # Quote the whole input as an FTS literal; users cannot inject its grammar.
        literal = '"' + query.replace('"', '""') + '"'
        sql += """ AND (p.id LIKE ? ESCAPE '\\' OR p.code LIKE ? ESCAPE '\\'
            OR p.id IN (SELECT patient_id FROM patient_search WHERE patient_search MATCH ?) OR p.id IN (
            SELECT e.patient_id FROM encounters e JOIN encounter_search s ON s.encounter_id=e.id
            WHERE encounter_search MATCH ?)
            OR p.id IN (SELECT c.patient_id FROM clinical_entries c JOIN clinical_entry_search s ON s.entry_id=c.id
                        WHERE clinical_entry_search MATCH ?)
            OR p.id IN (SELECT t.patient_id FROM text_imports t JOIN import_search s ON s.import_id=t.id
                        WHERE import_search MATCH ?))"""
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        params += [f'%{escaped}%', f'%{escaped}%', literal, literal, literal, literal]
    if age_status:
        sql += ' AND p.age_status=?'
        params.append(age_status)
    if record_kind:
        sql += ' AND EXISTS (SELECT 1 FROM clinical_entries c WHERE c.patient_id=p.id AND c.kind=?)'
        params.append(record_kind)
    if route_category:
        sql += """ AND EXISTS (SELECT 1 FROM proposals v WHERE v.patient_id=p.id AND v.kind='referral'
            AND coalesce(json_extract(v.payload_json,'$.routing_review.category'),
                         json_extract(v.payload_json,'$.route.category'))=?)"""
        params.append(route_category)
    if attention:
        sql += f' AND EXISTS ({PENDING_SIGNAL_SQL})'
        params += [doctor_id, now()]
    order = 'p.code'
    if signals_first and doctor_id is not None:
        order = (f'(EXISTS ({PENDING_SIGNAL_SQL})) DESC, p.code')
        params += [doctor_id, now()]
    return db.execute(sql + ' ORDER BY ' + order + ' LIMIT 100', params).fetchall()


def pending_signal_counts(db, doctor_id):
    """Число критических сигналов без записанной реакции врача по каждому пациенту."""
    rows = db.execute('''SELECT c.patient_id AS patient_id, COUNT(*) AS n FROM critical_events c
        LEFT JOIN critical_delivery d ON d.event_id=c.id JOIN care_relationships r ON r.id=c.relationship_id
        WHERE d.reacted_at IS NULL AND c.recipient_id=? AND r.doctor_id=c.recipient_id
        AND r.ends_at IS NULL AND r.starts_at<=? GROUP BY c.patient_id''', (doctor_id, now())).fetchall()
    return {row['patient_id']: row['n'] for row in rows}
