"""Create a populated database using the real preceding Git revision, then upgrade."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from apps.compass.db import connect, migrate
    from apps.compass import access, records, events
    with tempfile.TemporaryDirectory() as temp:
        old_root = Path(temp) / 'old'
        old_root.mkdir()
        archive = subprocess.check_output(['git', 'archive', 'd2ace1b'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old_root, filter='data')
        database = Path(temp) / 'upgrade.sqlite3'
        old_code = '''
import sys
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import access,records
db=connect(sys.argv[1]);migrate(db);seed_demo(db);access.seed_accounts(db)
access.accept_invite(db,'patient-D01',access.invite(db,'doctor-demo','D01'))
records.save(db,{'id':'patient-D01','role':'patient'},'D01','self_report',
 {'request_key':'a'*32,'observed_on':'2026-10-18','summary':'Pre-upgrade synthetic report','wellbeing':'unknown'})
db.close()
'''
        subprocess.run([sys.executable, '-c', old_code, str(database)], cwd=old_root, check=True)
        db = connect(database)
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        snapshots = {t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '"')] for t in tables}
        migrate(db)
        for table, rows in snapshots.items():
            actual = [tuple(r) for r in db.execute('SELECT * FROM "' + table + '"')]
            if table == 'schema_migrations':
                assert all(row in actual for row in rows)
            else:
                assert rows == actual, table
        assert db.execute('SELECT count(*) FROM routine_notifications').fetchone()[0] == 0
        entry = records.save(db, {'id': 'patient-D01', 'role': 'patient'}, 'D01', 'self_report',
                             {'request_key': 'b' * 32, 'observed_on': '2026-10-19',
                              'summary': 'Post-upgrade synthetic report', 'wellbeing': 'unknown'})
        while events.process_one(db):
            pass
        assert db.execute('SELECT ready_at FROM routine_notifications WHERE id=?', (entry,)).fetchone()[0]
        assert len(records.history(db, 'D01')) == 2
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        print(json.dumps({'old_revision': 'd2ace1b', 'previous_tables': len(tables),
                          'previous_nonempty_tables': sum(bool(v) for v in snapshots.values()),
                          'all_previous_rows_preserved': True, 'old_reports_not_reissued_as_new': True,
                          'new_report_ready_after_upgrade': True, 'history_entries_after_new_report': 2,
                          'integrity': 'ok', 'foreign_key_violations': 0}, indent=2))
        db.close()


if __name__ == '__main__':
    main()
