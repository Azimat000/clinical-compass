"""Private online SQLite snapshots; restore only to a new, offline path."""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from .db import now


def checked(db):
    if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok']:
        raise ValueError('Database integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Database foreign key check failed')
    return dict(db.execute('SELECT version,checksum FROM schema_migrations'))


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)


def copy_database(source, target, expected_sha256=None):
    source, target = Path(source).resolve(), Path(target).absolute()
    if target.is_symlink():
        raise ValueError('Destination symlink is forbidden')
    target = target.resolve()
    if source == target:
        raise ValueError('Source and destination must differ')
    if expected_sha256 is not None and hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('Backup checksum mismatch')
    # Never create the source or overwrite an existing destination, including symlinks.
    with closing(readonly(source)) as src:
        checked(src)
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=128)
                versions = checked(dst)
                # Describe the actual copied snapshot, not a concurrently changing source.
                tables=[row[0] for row in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                snapshot_rows={name:dst.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
            with target.open('rb') as stream:
                os.fsync(stream.fileno())
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return {'completed_at': now(), 'bytes': target.stat().st_size,
                    'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'migrations': versions, 'integrity_check': 'ok', 'foreign_key_check': [],
                    'snapshot_rows':snapshot_rows,
                    'recovery_limit':'Only rows in this snapshot are retained. Later records, critical events and receipts require reconciliation; their absence does not mean no risk.'}
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'restore'])
    parser.add_argument('source')
    parser.add_argument('target')
    parser.add_argument('--sha256', help='Required when restoring; from a separately retained backup record')
    args = parser.parse_args()
    if args.operation == 'restore' and not args.sha256:
        parser.error('restore requires --sha256')
    result = copy_database(args.source, args.target, args.sha256)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
