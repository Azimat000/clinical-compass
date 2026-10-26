"""Read-only source -> new private backup; never open active data for writing."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from apps.compass import backend_analyses as analyses, backend_sources as sources
from apps.compass.db import connect, migrate


def rows(db):
    return {r[0]: sorted(json.dumps(list(v),ensure_ascii=False,default=lambda b:{'blob_hex':b.hex()})
                        for v in db.execute('SELECT * FROM "'+r[0]+'"'))
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def main():
    original, destination, output = map(Path, sys.argv[1:])
    if original.resolve() == destination.resolve() or destination.exists():
        raise RuntimeError('New private destination required')
    fd = os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    source = sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True)
    target = sqlite3.connect(destination)
    try: source.backup(target)
    finally: source.close(); target.close()
    db = connect(destination)
    try:
        before = rows(db)
        definitions = dict(db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        migrate(db)
        counts = {'patients':0,'runs':0,'claims':0}
        for relation in db.execute('''SELECT r.* FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.ends_at IS NULL AND u.disabled=0 ORDER BY patient_id''').fetchall():
            user = {'id':relation['doctor_id'],'role':'doctor'}
            patient = relation['patient_id']
            hashes = set()
            for operation in ['risk','diagnosis','plan']:
                run = analyses.create(db,user,patient,{'contract_version':'1.0','operation':operation,
                    'request_key':hashlib.sha256((patient+operation).encode()).hexdigest()[:32]})
                raw = db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(run['snapshot_id'],)).fetchone()[0]
                frozen = json.loads(raw)['backend_sources']
                assert frozen == sources.capture()
                assert all(not s['reasons'] for s in frozen['sources'].values()), frozen
                assert len(frozen['claims'])==6
                assert set(r['id'] for r in sources.references(frozen)) <= set(r['id'] for r in run['sources'])
                assert hashlib.sha256(raw.encode()).hexdigest()==run['snapshot_id']
                assert analyses.read(db,user,patient,run['run_id'])==run
                assert run['release']['status']=='blocked' and run['result'] is None
                hashes.add(run['snapshot_id']); counts['runs']+=1; counts['claims']+=len(frozen['claims'])
            assert len(hashes)==1
            counts['patients']+=1
        after = rows(db)
        assert all(after[k]==v for k,v in before.items() if k not in {'schema_migrations','audit_entries'})
        assert set(before['audit_entries']) <= set(after['audit_entries'])
        current = dict(db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))
        assert all(current[k]==v for k,v in definitions.items())
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        report = {'result':'PASS','source_opened_read_only':True,'destination_mode':oct(destination.stat().st_mode&0o777),
                  'original_tables':len(before),'original_rows_preserved':True,'schema_preserved':True,
                  'audit_only_appended':True,'integrity':'ok','foreign_key_errors':0,**counts,
                  'source_version':'backend-sources-v1','clinical_release':'blocked','active_service_updated':False}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report))
    finally: db.close()


if __name__=='__main__': main()
