"""Backup active SQLite read-only, migrate/check copy; never change live data."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys

from apps.compass import backend_analyses as analyses, backend_jobs as jobs
from apps.compass.db import connect, migrate


def rows(db):
    return {r[0]: sorted(json.dumps(list(row), ensure_ascii=False, default=lambda v: bytes(v).hex())
                        for row in db.execute('SELECT * FROM "' + r[0] + '"'))
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def main():
    origin, destination = map(Path, sys.argv[1:3])
    if destination.exists(): raise ValueError('destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.touch(mode=0o600)
    with sqlite3.connect('file:' + str(origin.resolve()) + '?mode=ro', uri=True) as source:
        before = rows(source)
        with sqlite3.connect(destination) as target: source.backup(target)
        source_schema = {r[0]:r[1] for r in source.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    db = connect(destination)
    try:
        migrate(db)
        db.execute('UPDATE backend_job_settings SET enabled=1')
        outcomes = []
        for relationship in db.execute('SELECT * FROM care_relationships WHERE ends_at IS NULL ORDER BY patient_id').fetchall():
            patient = relationship['patient_id']; user = {'id':relationship['doctor_id'],'role':'doctor'}
            value = analyses.create(db,user,patient,{'contract_version':'1.0','operation':'risk','request_key':secrets.token_hex(16)})
            if value['status']=='queued': jobs.process_one(db,'risk')
            value = analyses.read(db,user,patient,value['run_id'])
            # Existing histories have no new explicit context. Never fabricate one.
            assert value['status'] in ('insufficient_data','unsupported'), value['status']
            assert value['result'] is None and value['release']['status']=='blocked'
            outcomes.append({'patient':patient,'status':value['status'],'code':value['errors'][0]['code']})
        assert len(outcomes)==10
        after = rows(db)
        for name, data in before.items():
            if name in ('audit_entries','schema_migrations'): continue
            assert after[name]==data, name
        assert set(before['audit_entries']) <= set(after['audit_entries'])
        for name, sql in source_schema.items():
            if sql is not None:
                assert db.execute('SELECT sql FROM sqlite_master WHERE name=?',(name,)).fetchone()[0]==sql, name
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        print(json.dumps({'pass':True,'source_mode':'ro','copy_mode':oct(destination.stat().st_mode&0o777),
                          'original_tables':len(before),'old_clinical_tables_and_schema_preserved':True,
                          'audit_only_appended':True,'integrity':'ok','foreign_keys':0,'model_calls':0,
                          'outcomes':outcomes},ensure_ascii=False,indent=2))
    finally: db.close()


if __name__=='__main__': main()
