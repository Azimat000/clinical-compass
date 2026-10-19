"""Upgrade an actual S10A revision database without rewriting prior rows or decisions."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from apps.compass import records, clinical_rules, decisions
    from apps.compass.db import connect, migrate
    with tempfile.TemporaryDirectory() as temp:
        old_root = Path(temp) / 'old'
        old_root.mkdir()
        archive = subprocess.check_output(['git', 'archive', 'fff9bc9'], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old_root, filter='data')
        database = Path(temp) / 'upgrade.sqlite3'
        old_code = '''
import sys,secrets,json
sys.path.insert(0,'apps/tests')
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import access,records,decisions
from test_access import setup_identities
from test_decisions import DecisionTests
db=connect(sys.argv[1]);migrate(db);seed_demo(db);setup_identities(db)
access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
records.save(db,{'id':'pat-a','role':'patient'},'D01','self_report',
 {'request_key':'a'*32,'observed_on':records.today().isoformat(),'summary':'Old synthetic report'})
doc={'id':'doc-a','role':'doctor'}
first=decisions.draft(db,doc,'D01',DecisionTests.values(None,kind='referral'))
version=db.execute('SELECT version FROM proposals WHERE id=?',(first,)).fetchone()[0]
decisions.confirm(db,doc,'D01',first,{'version':str(version),'decision':'approved','reviewed':'yes','rationale':'Synthetic old decision'})
pending=decisions.draft(db,doc,'D01',DecisionTests.values(None,kind='referral'))
print(json.dumps({'approved':first,'pending':pending}))
db.close()
'''
        identifiers = json.loads(subprocess.check_output([sys.executable, '-c', old_code, str(database)], cwd=old_root, text=True))
        db = connect(database)
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        before = {t: [tuple(r) for r in db.execute('SELECT * FROM "' + t + '"')] for t in tables}
        migrate(db)
        for table, rows in before.items():
            after = [tuple(r) for r in db.execute('SELECT * FROM "' + table + '"')]
            assert all(r in after for r in rows) if table == 'schema_migrations' else rows == after, table
        assert db.execute('SELECT count(*) FROM clinical_rule_evaluations').fetchone()[0] == 0
        old_pending = db.execute('SELECT * FROM proposals WHERE id=?', (identifiers['pending'],)).fetchone()
        try:
            decisions.confirm(db, {'id': 'doc-a', 'role': 'doctor'}, 'D01', old_pending['id'],
                              {'version': str(old_pending['version']), 'decision': 'approved', 'reviewed': 'yes', 'rationale': 'test'})
        except decisions.DecisionError as exc:
            assert exc.status == 409
        else:
            raise AssertionError('Old unsynchronised draft could be confirmed')
        context = {'request_key': 'b' * 32, 'observed_on': records.today().isoformat(),
                   'clinical_basis': 'Synthetic existing record', 'aviandr_prescription': 'active',
                   'prescription_basis': 'Synthetic existing prescription', 'gad_status': 'present',
                   'severity': 'nonsevere', 'suicide_risk': 'denied', 'psychiatric_comorbidity': 'denied',
                   'treatment_resistance': 'denied'}
        clinical_rules.save_context(db, {'id': 'doc-a', 'role': 'doctor'}, 'D01', context)
        records.save(db, {'id': 'pat-a', 'role': 'patient'}, 'D01', 'self_report',
                     {'request_key': 'c' * 32, 'observed_on': records.today().isoformat(),
                      'safety_form_version': 'aviandr-safety-v1', 'safety_taken': 'present',
                      'safety_after_dose': 'present', 'safety_current': 'present', 'safety_trismus': 'present'})
        assert db.execute('SELECT count(*) FROM critical_events').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0] == 1
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        print(json.dumps({'old_revision': 'fff9bc9', 'previous_tables': len(tables),
            'previous_nonempty_tables': sum(bool(v) for v in before.values()), 'all_previous_rows_preserved': True,
            'old_approved_decision_preserved': True, 'old_pending_requires_new_draft': True,
            'old_report_not_reclassified': True, 'new_rule_created_real_event': True,
            'clinical_actions_after_new_event': 1, 'integrity': 'ok', 'foreign_key_violations': 0}, indent=2))
        db.close()


if __name__ == '__main__':
    main()
