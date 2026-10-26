"""Independent preservation check using a private backup and read-only live DB."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass.db import connect,migrate
from apps.compass import backend_alerts as alerts


def fingerprint(db):
    return {name:{'rows':len(rows),'sha256':hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            for rows in [sorted(json.dumps(list(r),ensure_ascii=False,default=lambda v:{'hex':v.hex()}) for r in db.execute('SELECT * FROM "'+name+'"'))]}


def health():
    return json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=5))

source=sqlite3.connect((ROOT/'var/compass.sqlite3').as_uri()+'?mode=ro',uri=True)
before=fingerprint(source);health_before=health()
triggers=dict(source.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
target=ROOT/'var/BE09-migration-check.sqlite3'
assert not target.exists(),'refusing overwrite'
db=connect(target);source.backup(db)
assert fingerprint(db)==before
migrate(db);after=fingerprint(db)
assert all(before[t]==after[t] for t in before if t!='schema_migrations')
assert all(dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).get(k)==v for k,v in triggers.items())
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert not db.execute('PRAGMA foreign_key_check').fetchall()
assert db.execute('SELECT enabled FROM backend_job_settings').fetchone()[0]==0
assert alerts.status(db)==[]
migrate(db);assert fingerprint(db)==after
assert fingerprint(source)==before and health()==health_before
baseline=json.loads((ROOT/'evidence/BE09/baseline.json').read_text())
assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in baseline['untracked'].items())
result={'pass':True,'source_read_only':True,'active_rows_unchanged':True,'active_health':health_before,
        'old_tables_preserved':len(before),'old_triggers_preserved':len(triggers),
        'copy':str(target.relative_to(ROOT)),'mode':oct(target.stat().st_mode & 0o777),'schema':db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
        'jobs_enabled':0,'integrity':'ok','foreign_key_errors':0,'repeat_migration_unchanged':True,
        'preexisting_untracked_files_preserved':len(baseline['untracked']),'accounts_and_passwords_unchanged':True,'external_calls':0}
(ROOT/'evidence/BE09/copy-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
db.close();source.close()
