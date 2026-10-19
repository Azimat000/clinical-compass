"""Run in the demo container; emit only row digests, never records or credentials."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

source = sqlite3.connect(os.environ.get('COMPASS_DB', '/app/var/compass.sqlite3'))
if sys.argv[1] == 'before':
    target = Path('/app/var/s07-before-fa21b24.sqlite3')
    if target.exists():
        raise SystemExit('Refusing to overwrite existing private backup')
    destination = sqlite3.connect(target)
    source.backup(destination)
    destination.close()
    source.close()
    source = sqlite3.connect(target)
tables = [r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")]
excluded = {'sessions', 'login_limits', 'login_challenges'}
rows = {}
for table in sorted(set(tables) - excluded):
    name = table.replace('"', '""')
    rows[table] = sorted(hashlib.sha256(json.dumps(list(row), ensure_ascii=False,
        default=lambda value: {'hex': value.hex()}).encode()).hexdigest()
        for row in source.execute('SELECT * FROM "' + name + '"'))
print(json.dumps({'phase': sys.argv[1], 'row_digests': rows, 'excluded_mutable_auth_tables': sorted(excluded),
                  'integrity_check': source.execute('PRAGMA integrity_check').fetchone()[0],
                  'foreign_key_check': source.execute('PRAGMA foreign_key_check').fetchall()}, indent=2))
source.close()
