"""BE02 lossless adapter acceptance on a NEW private SQLite backup only."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from apps.compass import backend_analyses as analyses, backend_snapshot as snapshots
from apps.compass.db import connect, migrate


def rows(db):
    return {r[0]: sorted(json.dumps(list(v), ensure_ascii=False,
                                   default=lambda b: {'blob_hex': b.hex()}) for v in db.execute('SELECT * FROM "'+r[0]+'"'))
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def decoded(row, path):
    value = row
    for part in path.lstrip('/').split('/'):
        value = value[part.replace('~1', '/').replace('~0', '~')]
        if part.endswith('_json') and value is not None:
            value = json.loads(value)
    return value


def main():
    original, destination, output = map(Path, sys.argv[1:])
    if destination.exists() or original.resolve() == destination.resolve():
        raise RuntimeError('A new private destination is required')
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect(original.resolve().as_uri()+'?mode=ro', uri=True)
    copy = sqlite3.connect(destination)
    try:
        source.backup(copy)
    finally:
        copy.close(); source.close()
    db = connect(destination)
    try:
        before = rows(db)
        definitions = dict(db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        migrate(db)
        results = []
        relations = list(db.execute('''SELECT r.* FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.ends_at IS NULL AND u.disabled=0 ORDER BY patient_id'''))
        for relation in relations:
            user = {'id': relation['doctor_id'], 'role': 'doctor'}
            patient = relation['patient_id']
            run = analyses.create(db, user, patient, {'contract_version': '1.0', 'operation': 'risk',
                                                     'request_key': hashlib.sha256(patient.encode()).hexdigest()[:32]})
            raw = db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?', (run['snapshot_id'],)).fetchone()[0]
            snapshot = json.loads(raw)
            assert run['snapshot_id'] == hashlib.sha256(raw.encode()).hexdigest()
            history = snapshot['patient_history']
            checked_fields = 0
            for ref, meta in history['sources'].items():
                resolved = snapshots.resolve(snapshot, ref)
                table = 'care_actions' if meta['table'] == 'actions' else meta['table']
                actual = dict(db.execute(f'SELECT * FROM {table} WHERE {meta["key"]}=?', (meta['id'],)).fetchone())
                if table == 'care_actions':
                    actual['proposal_id'] = resolved['row']['proposal_id']
                assert actual == resolved['row']
                assert 'patient_id' not in actual or actual['patient_id'] == patient
                analyses.validate('HistorySource', analyses.inputs(db, user, patient, run['run_id'], reference=ref))
            for entry in history['entries']:
                for fact in entry['fields']:
                    source_row = snapshots.resolve(snapshot, fact['source_ref'])['row']
                    assert fact['value'] == decoded(source_row, fact['path']), (patient, fact['path'])
                    checked_fields += 1
            first = analyses.inputs(db, user, patient, run['run_id'])
            combined = []
            for page in range(1, first['page_count']+1):
                part = analyses.inputs(db, user, patient, run['run_id'], page=page)
                analyses.validate('HistoryPage', part)
                combined.extend(part['entries'])
            assert combined == history['entries']
            assert all(history['counts'][c] > 0 for c in snapshots.CATEGORIES[:4])
            again = analyses.create(db, user, patient, {'contract_version': '1.0', 'operation': 'risk',
                                                       'request_key': hashlib.sha256((patient+'again').encode()).hexdigest()[:32]})
            assert again['snapshot_id'] == run['snapshot_id']
            results.append({'patient_id': patient, 'snapshot_bytes': len(raw.encode()),
                            'sources_checked': len(history['sources']), 'fields_checked': checked_fields,
                            'entries': history['entry_count'], 'pages': first['page_count'],
                            'counts': history['counts'], 'same_input_hash_equal': True})
        after = rows(db)
        preserved = all(after[k] == v for k,v in before.items() if k not in ('schema_migrations', 'audit_entries'))
        assert preserved
        assert set(before['audit_entries']) <= set(after['audit_entries'])
        current_definitions = dict(db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        assert all(current_definitions[k] == v for k,v in definitions.items())
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        report = {'result': 'PASS', 'source_opened_read_only': True,
                  'destination_mode': oct(destination.stat().st_mode & 0o777),
                  'original_tables': len(before), 'original_clinical_rows_preserved': preserved,
                  'original_schema_preserved': True, 'audit_only_appended': True,
                  'integrity': 'ok', 'foreign_key_errors': 0, 'patients': results}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({'result':'PASS','patients':len(results),'sources':sum(r['sources_checked'] for r in results),
                          'fields':sum(r['fields_checked'] for r in results),'max_snapshot_bytes':max(r['snapshot_bytes'] for r in results),
                          'original_clinical_rows_preserved':preserved}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == '__main__':
    main()
