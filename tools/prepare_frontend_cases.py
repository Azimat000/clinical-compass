"""Prepare an append-only synthetic FE03C copy; never activate it or call a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.compass import records
from apps.compass.db import connect, migrate, now

MANIFEST = ROOT / 'data/fictional/frontend-cases-v1.json'
TARGET = ROOT / 'var/FE03C-cases.sqlite3'
EVENT = 'fictional.frontend_cases_prepared'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('before', 'after'), default='before')
    args = parser.parse_args()
    raw = MANIFEST.read_bytes()
    data = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    source = ROOT / data['source']
    created_copy = not TARGET.exists()
    if created_copy:
        if args.phase != 'before':
            raise SystemExit('Prepare before first; no reset is supported.')
        descriptor = os.open(TARGET, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
                if original.execute('SELECT 1 FROM patients WHERE synthetic<>1').fetchone():
                    raise ValueError('Only synthetic patients are allowed')
                with sqlite3.connect(TARGET) as copied:
                    original.backup(copied)
        except BaseException:
            TARGET.unlink(missing_ok=True)
            raise
    db = connect(TARGET)
    try:
        prior = db.execute('SELECT metadata_json FROM audit_entries WHERE event=? ORDER BY occurred_at',
                           (EVENT,)).fetchall()
        if any(json.loads(r[0])['manifest_sha256'] != digest for r in prior):
            raise ValueError('Manifest changed; existing copy is preserved. Use a new version/path.')
        if any(json.loads(r[0])['phase'] == args.phase for r in prior):
            print(json.dumps({'status': 'already_prepared', 'phase': args.phase,
                              'database': str(TARGET), 'existing_history_preserved': True}))
            return
        if args.phase == 'after' and not any(json.loads(r[0])['phase'] == 'before' for r in prior):
            raise ValueError('Missing before provenance; refusing to modify existing database')
        if not prior and not created_copy:
            raise ValueError('Unrecognized existing target; refusing to change it')
        migrate(db)
        db.execute('UPDATE backend_job_settings SET enabled=0')
        created = []
        for event in data['events']:
            if event['phase'] != args.phase:
                continue
            patient = event['patient_id']
            if event['kind'] == 'self_report':
                user = db.execute('SELECT u.* FROM users u JOIN patients p ON p.user_id=u.id WHERE p.id=?',
                                  (patient,)).fetchone()
            else:
                user = db.execute('SELECT u.* FROM users u JOIN care_relationships r ON r.doctor_id=u.id '
                                  'WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?',
                                  (patient, now())).fetchone()
            if user is None:
                raise ValueError('Missing existing relationship: ' + patient)
            key = hashlib.sha256((data['version'] + ':' + event['id']).encode()).hexdigest()[:32]
            entry = records.save(db, user, patient, event['kind'], {
                'request_key': key, 'observed_on': data['observed_on'],
                'summary': event['summary'], 'wellbeing': 'unknown'})
            created.append({'event': event['id'], 'patient_id': patient, 'entry_id': entry})
        metadata = {'synthetic': True, 'clinical_review': False, 'manifest_sha256': digest,
                    'phase': args.phase, 'entries': created, 'model_calls': 0,
                    'history_policy': 'append_only_no_reset'}
        db.execute('INSERT INTO audit_entries(event,entity_id,occurred_at,metadata_json) VALUES(?,?,?,?)',
                   (EVENT, data['version'], now(), json.dumps(metadata, ensure_ascii=False)))
        print(json.dumps({'status': 'prepared_unverified', 'database': str(TARGET), **metadata},
                         ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
