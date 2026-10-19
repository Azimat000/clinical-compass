"""Backup failures must not create a source or overwrite another file."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from apps.compass.backup import copy_database
from apps.compass.db import connect, migrate
from apps.compass.repository import seed_demo


class BackupTests(unittest.TestCase):
    def test_snapshot_restore_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, backup, restored = [root / x for x in ('live', 'backup', 'restored')]
            db = connect(source); migrate(db); seed_demo(db)
            result = copy_database(source, backup)
            self.assertEqual(0o600, backup.stat().st_mode & 0o777)
            db.execute("UPDATE patients SET code='changed' WHERE id='D01'")
            copy_database(backup, restored, result['sha256'])
            with sqlite3.connect(restored) as other:
                self.assertNotEqual('changed', other.execute("SELECT code FROM patients WHERE id='D01'").fetchone()[0])
            digest = hashlib.sha256(backup.read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError): copy_database(source, backup)
            self.assertEqual(digest, hashlib.sha256(backup.read_bytes()).hexdigest())
            with self.assertRaises(ValueError): copy_database(source, source)
            db.close()

    def test_missing_corrupt_tampered_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'source'; target = root/'target'
            with self.assertRaises(sqlite3.OperationalError): copy_database(source, target)
            self.assertFalse(source.exists()); self.assertFalse(target.exists())
            source.write_bytes(b'broken SQLite')
            with self.assertRaises(sqlite3.DatabaseError): copy_database(source, target)
            self.assertFalse(target.exists())
            with self.assertRaises(ValueError): copy_database(source, target, '0'*64)
            source.unlink()
            db = connect(source); migrate(db); seed_demo(db); db.close()
            target.symlink_to(source)
            with self.assertRaises(ValueError): copy_database(source, target)
            self.assertTrue(source.exists())

    def test_foreign_key_violation_refused_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'live',Path(folder)/'backup'
            db=connect(source);migrate(db);seed_demo(db);db.close()
            with sqlite3.connect(source) as raw:
                raw.execute("CREATE TABLE s15_broken_fk(user_id TEXT REFERENCES users(id))")
                raw.execute("INSERT INTO s15_broken_fk VALUES('missing')")
            with self.assertRaises(ValueError): copy_database(source,target)
            self.assertFalse(target.exists())

    def test_concurrent_writer_backup_is_a_consistent_snapshot(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'live';target=Path(folder)/'backup'
            db=connect(source);migrate(db);seed_demo(db)
            db.execute('CREATE TABLE s15_pair(id INTEGER PRIMARY KEY,a INTEGER,b INTEGER)')
            db.execute('INSERT INTO s15_pair VALUES(1,0,0)');db.close()
            stop=threading.Event();started=threading.Event();errors=[]
            def write():
                from apps.compass.db import transaction
                writer=connect(source)
                try:
                    for n in range(1,100):
                        if stop.is_set():break
                        with transaction(writer):
                            writer.execute('UPDATE s15_pair SET a=?,b=?',(n,n))
                        started.set();stop.wait(.001)
                except Exception as exc:errors.append(type(exc).__name__)
                finally:writer.close()
            thread=threading.Thread(target=write);thread.start()
            try:
                self.assertTrue(started.wait(5));copy_database(source,target)
            finally:stop.set();thread.join(timeout=10)
            self.assertFalse(thread.is_alive());self.assertEqual([],errors)
            with sqlite3.connect(target) as snapshot:
                a,b=snapshot.execute('SELECT a,b FROM s15_pair').fetchone()
                self.assertEqual(a,b);self.assertGreaterEqual(a,1)
