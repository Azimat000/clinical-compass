"""Check local data and pre-existing user files without exposing account rows."""
import hashlib
import json
from pathlib import Path
import sqlite3


def snapshot(path):
    db = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    db.execute('BEGIN')
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    values = {}
    for name in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(repr(tuple(row)) for row in db.execute('SELECT * FROM ' + quoted))
        values[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    foreign_keys = len(db.execute('PRAGMA foreign_key_check').fetchall())
    audit = {tuple(r) for r in db.execute('SELECT * FROM audit_entries')}
    db.close()
    return values, integrity, foreign_keys, audit


before, _, _, old_audit = snapshot('var/backups/S50-before-action-removal.sqlite3')
after, integrity, foreign_keys, new_audit = snapshot('var/compass.sqlite3')
changed = {t: {'before':before.get(t), 'after':after.get(t)} for t in before.keys() | after.keys() if before.get(t) != after.get(t)}
allowed = {'sessions', 'audit_entries', 'login_challenges', 'login_limits'}
assert set(changed) <= allowed, list(changed)
assert old_audit <= new_audit, 'Old audit rows missing'
assert before['clinical_contexts'] == after['clinical_contexts']
assert integrity == 'ok' and foreign_keys == 0
baseline = json.loads(Path('var/S50-baseline.json').read_text())
assert all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p,h in baseline['pre_existing_untracked'].items())
report = {'status':'PASS', 'table_count':len(after), 'unchanged_tables':len(after)-len(changed), 'changed_auth_tables':changed,
          'clinical_contexts_unchanged':True, 'old_audit_preserved':True, 'new_audit_rows':len(new_audit-old_audit),
          'integrity':integrity, 'foreign_key_errors':foreign_keys,
          'pre_existing_untracked_files_unchanged':len(baseline['pre_existing_untracked']),
          'backup_permissions':oct(Path('var/backups/S50-before-action-removal.sqlite3').stat().st_mode & 0o777)}
Path('evidence/S50/preservation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS: data and user files preserved; unchanged tables:', report['unchanged_tables'])
