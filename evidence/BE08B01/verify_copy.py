"""Main-agent additive migration check on private SQLite backup, never live writes."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass.db import connect, migrate


def fingerprint(db):
    result = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        rows = sorted(json.dumps(list(r), sort_keys=True, ensure_ascii=False,
                                 default=lambda v: {'hex': v.hex()})
                      for r in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"'))
        result[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    return result


def health():
    with urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5) as response:
        return json.load(response)


source = sqlite3.connect((ROOT / 'var/compass.sqlite3').as_uri() + '?mode=ro', uri=True)
before_health = health()
source_before = fingerprint(source)
triggers_before = dict(source.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
target = ROOT / 'var/BE08B01-migration-check.sqlite3'
if target.exists():
    raise SystemExit('Refusing to overwrite migration evidence DB')
db = connect(target)
source.backup(db)
copy_before = fingerprint(db)
assert copy_before == source_before
migrate(db)
copy_after = fingerprint(db)
for table in copy_before:
    if table != 'schema_migrations':
        assert copy_before[table] == copy_after[table], table
triggers_after = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
assert all(triggers_after.get(k) == v for k, v in triggers_before.items())
assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
assert not db.execute('PRAGMA foreign_key_check').fetchall()
assert db.execute('SELECT enabled FROM backend_job_settings').fetchone()[0] == 0
first_migration = fingerprint(db)
migrate(db)
assert first_migration == fingerprint(db)
assert source_before == fingerprint(source)
assert before_health == health()
baseline = json.loads((ROOT / 'evidence/BE08B01/baseline.json').read_text())
assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
           for path, sha in baseline['preserved_files'].items())
result = {'pass': True, 'live_open_mode': 'ro', 'live_unchanged': True,
          'copy': str(target.relative_to(ROOT)), 'copy_mode': oct(target.stat().st_mode & 0o777),
          'existing_tables': len(copy_before), 'existing_rows_unchanged': True,
          'existing_triggers_retained': len(triggers_before), 'migration_idempotent': True,
          'added_tables': sorted(set(copy_after) - set(copy_before)),
          'schema_after': db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
          'jobs_enabled': 0, 'integrity': 'ok', 'foreign_key_errors': 0,
          'live_health': before_health, 'preserved_files': len(baseline['preserved_files']),
          'clinical_validation': False, 'external_calls': 0}
(ROOT / 'evidence/BE08B01/copy-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
db.close()
source.close()
