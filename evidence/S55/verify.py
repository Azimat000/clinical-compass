"""Independent persisted-row acceptance. Never prints or exports credentials."""
from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.compass import assessments, decisions, first_visits, medications, plan_tasks, records
from apps.compass.db import connect
from tools import seed_clinic_roster as roster


def verify(path, old_path):
    data = roster.dataset()
    with closing(connect(path)) as db, closing(sqlite3.connect(Path(old_path).resolve().as_uri()+'?mode=ro', uri=True)) as old:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 12
        assert db.execute("SELECT count(*) FROM users WHERE role='doctor'").fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM patients').fetchone()[0] == 10
        assert db.execute('SELECT count(*) FROM patients WHERE synthetic<>1').fetchone()[0] == 0
        old_ids = {r[0] for r in old.execute('SELECT id FROM users')} | {r[0] for r in old.execute('SELECT id FROM patients')}
        dump = '\n'.join(db.iterdump())
        assert all("'"+x.replace("'", "''")+"'" not in dump for x in old_ids)
        sources = {}
        for table in roster.SOURCE_TABLES:
            before = [tuple(r) for r in old.execute('SELECT * FROM '+table)]
            after = [tuple(r) for r in db.execute('SELECT * FROM '+table)]
            assert before == after, table
            sources[table] = dict(rows=len(after), unchanged=True)
        origin = json.loads(db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.roster_loaded'").fetchone()[0])
        assert origin['synthetic'] and origin['simulated_dates'] and not origin['clinical_review'] and not origin['real_user_trial']
        assert origin['dataset_sha256'] == hashlib.sha256(roster.DATASET.read_bytes()).hexdigest()
        patients = []
        for p in data['patients']:
            pid = p['id']
            doctor, patient = dict(id=p['doctor'], role='doctor'), dict(id=p['login'], role='patient')
            assert db.execute('SELECT doctor_id FROM care_relationships WHERE patient_id=? AND ends_at IS NULL', (pid,)).fetchone()[0] == p['doctor']
            visits = first_visits.history(db, doctor, pid)
            completed = [v for v in visits if v['state'] == 'completed']
            assert len(completed) == 3
            assert [v['payload']['fields']['conclusion']['text'] for v in completed] == list(reversed(p['visits']))
            for v in completed:
                assert v['revision'] == 3 and v['payload']['documented_facts']
                assert all(v['payload']['fields'][field]['text'] for field in first_visits.CURRENT_FIELDS + first_visits.STATIC_FIELDS)
            rows = db.execute('SELECT * FROM clinical_entries WHERE patient_id=? ORDER BY observed_on', (pid,)).fetchall()
            assert len(rows) == 7 and [r['summary'] for r in rows] == p['diary']
            assert all(r['kind'] == 'self_report' and r['actor_id'] == p['login'] for r in rows)
            assert len(assessments.history(db, doctor, pid)) == 9
            assert len(assessments.pending(db, patient, pid)) == 3
            tasks = plan_tasks.view(db, doctor, pid)['tasks']
            assert any(t['superseded'] for t in tasks)
            assert any(t['future'] and not t['superseded'] for t in tasks)
            active = [t for t in tasks if not t['superseded'] and not t['future']]
            authored = next(t for t in active if t['label'] == p['task'])
            assert authored['outcome'] == p['outcome'], pid
            for t in tasks:
                assert all(h['actor_id'] == p['login'] and h['recorded_at'] >= t['due_at'] for h in t['history'])
            for r in rows:
                payload = json.loads(r['payload_json'])
                if payload.get('medication_feedback'):
                    assert payload['medication_feedback_plan']
                    for item in payload['medication_feedback']:
                        assert item['name'] in roster.MEDICINES and item['responses']
            patients.append(dict(id=pid,name=p['name'],doctor=p['doctor'],completed_visits=3,
                diary_entries=7,questionnaires=9,pending_questionnaires=3,plan_items=len(tasks),scenario=p['scenario']))
        start = date.fromisoformat(origin['observation_start'])
        stop = start + timedelta(days=21)
        assert medications.approved(db, 'P207')[-1]['medications'] == []
        assert not medications.occurrences(db, 'P207', stop+timedelta(days=1), records.today())
        assert medications.approved(db, 'P204')[0]['medications'][0]['name'] != medications.approved(db, 'P204')[-1]['medications'][0]['name']
        calendar = medications.occurrences(db, 'P207', start, stop)
        assert sum(d['state']=='unknown' for d in calendar) == 2
        doses = medications.occurrences(db, 'P203', start, records.today())
        assert any(d['state']=='missed' for d in doses) and any(d['state']=='partial' for d in doses)
        assert any(len(d['history'])==3 for d in doses)
        assert db.execute("SELECT count(*) FROM assessments WHERE completeness='incomplete'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM assessments WHERE completeness<>'complete' AND score IS NOT NULL").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM doctor_confirmations WHERE decision='rejected'").fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM proposals p WHERE NOT EXISTS (SELECT 1 FROM doctor_confirmations c WHERE c.proposal_id=p.id)').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM clinical_rule_evaluations').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM critical_events').fetchone()[0] == 0
        assert decisions.reference()['active_rules'] is False
        counts = {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
                  ('users','patients','care_relationships','first_visit_versions','self_reports','assessments',
                   'assessment_requests','proposals','doctor_confirmations','care_actions','adherence_tasks',
                   'adherence_entries','medication_marks','adverse_events','text_imports','extraction_reviews',
                   'messages','message_receipts','self_report_drafts','clinical_rule_evaluations','critical_events')}
    baseline = json.loads((ROOT/'var/S55-baseline.json').read_text())
    assert all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in baseline['untracked'].items())
    return dict(status='PASS',database=str(path),counts=counts,patients=patients,
                old_identities_absent=len(old_ids),source_metadata=sources,integrity='ok',foreign_key_errors=0,
                provenance=origin,pre_existing_untracked_files_preserved=len(baseline['untracked']))


if __name__ == '__main__':
    result = verify(sys.argv[1], sys.argv[2])
    Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS: 2 doctors, 10 complete histories; sources unchanged; no old identities or active clinical rules')
