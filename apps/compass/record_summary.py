"""Independent read-only feature: completeness counts, without a clinical score."""
import json


def summarize(db, patient_id):
    counts = {'records': 0, 'known': 0, 'unknown': 0, 'denied': 0, 'conflicting': 0}
    for row in db.execute('SELECT payload_json FROM clinical_entries WHERE patient_id=?', (patient_id,)):
        counts['records'] += 1
        for field in json.loads(row['payload_json'])['fields'].values():
            counts[field['status']] += 1
    return counts
