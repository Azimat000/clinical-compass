"""BE01 acceptance: migrate a private consistent backup, never the running database."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from apps.compass.db import connect, migrate


def digest_rows(db):
    result = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        rows = sorted(json.dumps(list(r), ensure_ascii=False, default=str) for r in db.execute('SELECT * FROM "'+name+'"'))
        result[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(rows).encode()).hexdigest()}
    return result


def schema(db):
    return dict(db.execute('SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL'))


def main():
    source, target, report = map(Path, sys.argv[1:])
    if target.exists() or source.resolve() == target.resolve():
        raise RuntimeError('Use a NEW private destination, never the active database')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600);os.close(fd)
    original = sqlite3.connect(source.resolve().as_uri()+'?mode=ro', uri=True)
    copy = sqlite3.connect(target)
    try:
        original.backup(copy)
        original_schema = schema(original)
    finally:
        copy.close();original.close()
    db = connect(target)
    try:
        before = digest_rows(db)
        old_schema = schema(db)
        old_migrations = list(db.execute('SELECT * FROM schema_migrations ORDER BY version'))
        migrate(db)
        after = digest_rows(db)
        new_schema = schema(db)
        preserved = all(after[k] == v for k,v in before.items() if k != 'schema_migrations')
        migration_rows = list(db.execute("SELECT * FROM schema_migrations WHERE version!='016_backend_analyses' ORDER BY version"))
        preserved = preserved and old_migrations == migration_rows
        preserved_schema = all(new_schema[k] == v for k,v in old_schema.items())
        new_tables = sorted(set(after)-set(before))
        migrate(db)
        repeat_safe = digest_rows(db) == after and schema(db) == new_schema
        immutable = {}
        # Original history protections stay installed, not disabled by migration.
        for table in ['first_visit_versions', 'care_actions', 'doctor_confirmations']:
            try:
                db.execute('UPDATE '+table+' SET id=id')
            except sqlite3.IntegrityError:
                immutable[table] = True
            else:
                immutable[table] = False
        info = {'source_opened_read_only': True, 'live_schema_had_no_BE01': 'analysis_runs' not in original_schema,
                'original_table_count': len(before), 'new_tables': new_tables,
                'preexisting_rows_preserved': preserved, 'preexisting_schema_preserved': preserved_schema,
                'preexisting_triggers': sum(1 for s in old_schema.values() if s.startswith('CREATE TRIGGER')),
                'repeat_migration_safe': repeat_safe, 'original_history_update_rejected': immutable,
                'integrity': db.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_errors': len(db.execute('PRAGMA foreign_key_check').fetchall()),
                'existing_table_digests': {k:v for k,v in before.items() if k != 'schema_migrations'},
                'target_mode': oct(target.stat().st_mode & 0o777)}
        assert preserved and preserved_schema and repeat_safe and all(immutable.values()), info
        assert new_tables == ['analysis_input_snapshots','analysis_result_versions','analysis_runs'], info
        assert info['integrity'] == 'ok' and info['foreign_key_errors'] == 0, info
        report.write_text(json.dumps(info, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({k:v for k,v in info.items() if k != 'existing_table_digests'}, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':main()
