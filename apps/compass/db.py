"""Explicit connections and transactional, checksum-checked SQL migrations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).with_name('migrations')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Create private BEFORE SQLite opens it, including its rollback journal.
    # Existing databases are tightened; never chmod unrelated parent folders.
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if os.name == 'posix':
            path.chmod(0o600)
    else:
        os.close(descriptor)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    # Rollback journal avoids the WAL race affecting the host SQLite 3.50.4.
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA synchronous=FULL')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def migrate(db, directory=MIGRATIONS):
    # complete_statement keeps multi-statement trigger bodies intact.
    with transaction(db):
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
        applied = dict(db.execute('SELECT version, checksum FROM schema_migrations')) if exists else {}
        files = sorted(directory.glob('*.sql'))
        if set(applied) - {p.stem for p in files}:
            raise RuntimeError('Applied migration is missing')
        for path in files:
            script = path.read_text()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.stem in applied:
                if applied[path.stem] != digest:
                    raise RuntimeError(f'Migration checksum mismatch: {path.name}')
                continue
            statement = ''
            for line in script.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            if statement.strip():
                raise RuntimeError(f'Incomplete migration: {path.name}')
            db.execute('INSERT INTO schema_migrations VALUES (?,?,?)', (path.stem, digest, now()))


def health(db):
    return {'status': 'ok', 'schema_version': db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
            'foreign_keys': bool(db.execute('PRAGMA foreign_keys').fetchone()[0]),
            'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0]}
