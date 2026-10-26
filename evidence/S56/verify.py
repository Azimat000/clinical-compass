"""Independent read-only acceptance of the persisted fictional medication edition."""
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass import assessments, decisions, medications
from apps.compass.db import connect


def verify(path, original):
    with closing(connect(path)) as db,closing(connect(original)) as old:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        protected=('users','patients','care_relationships','source_versions','catalog_versions','assessment_form_releases',
                   'doctor_confirmations','care_actions','text_imports','extraction_reviews','self_report_drafts',
                   'assessment_requests','assessments','assessment_results','adherence_tasks','adherence_entries','message_context','message_receipts')
        for table in protected:
            assert [tuple(r) for r in db.execute('SELECT * FROM '+table)]==[tuple(r) for r in old.execute('SELECT * FROM '+table)],table
        for table in ('clinical_entries','self_reports','first_visit_versions','proposals','messages'):
            assert {r[0] for r in db.execute('SELECT id FROM '+table)}=={r[0] for r in old.execute('SELECT id FROM '+table)},table
        triggers="SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        assert [tuple(r) for r in db.execute(triggers)]==[tuple(r) for r in old.execute(triggers)]
        for table in ('clinical_entries','first_visit_versions','medication_marks','proposals','messages'):
            field='sequence' if table=='medication_marks' else 'id'
            try:
                db.execute(f'UPDATE {table} SET {field}={field}')
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError('Immutability protection missing: '+table)
        for table,field in (('proposals','payload_json'),('proposals','input_snapshot_json'),('clinical_entries','payload_json'),
                            ('first_visit_versions','payload_json'),('self_reports','payload_json'),('messages','body'),
                            ('adverse_events','description'),('clinical_entry_search','body')):
            for r in db.execute('SELECT '+field+' FROM '+table):
                assert 'Препарат А' not in r[0] and 'Препарат Б' not in r[0],table
        courses=[]
        for pid in ('P201','P202','P203','P204','P207','P208'):
            plans=medications.approved(db,pid)
            courses.append(dict(patient_id=pid,plans=[dict(proposal_id=p['id'],confirmed_at=p['confirmed_at'],medications=p['medications']) for p in plans]))
        def doses(pid,day):
            return medications.occurrences(db,pid,date.fromisoformat(day),date.fromisoformat(day))
        for pid in ('P202','P208'):
            assert '25 мг' in doses(pid,'2026-09-21')[0]['name']
            assert '50 мг' in doses(pid,'2026-09-22')[0]['name']
        for day,strength in (('2026-10-05','50 мг'),('2026-10-06','25 мг'),('2026-10-12','25 мг'),('2026-10-13','50 мг')):
            items=doses('P204',day)
            assert len(items)==1 and 'Алевал '+strength in items[0]['name'] and items[0]['quarters']==4
        assert doses('P207','2026-10-05')[0]['quarters']==4
        assert doses('P207','2026-10-06')[0]['quarters']==2
        assert doses('P207','2026-10-18')[0]['actual']==2
        assert doses('P207','2026-10-19')==[]
        assert medications.approved(db,'P207')[-1]['medications']==[]
        assert doses('P203','2026-10-19')[0]['state']=='missed'
        assert doses('P203','2026-10-20')[0]['state']=='partial'
        assert len(doses('P203','2026-10-24')[0]['history'])==3
        for row in db.execute('SELECT * FROM clinical_entries'):
            payload=json.loads(row['payload_json'])
            assert row['payload_json']==db.execute('SELECT payload_json FROM self_reports WHERE id=?',(row['self_report_id'],)).fetchone()[0]
            assert row['summary']+' '+row['payload_json']==db.execute('SELECT body FROM clinical_entry_search WHERE entry_id=?',(row['id'],)).fetchone()[0]
            for item in payload.get('medication_feedback',[]):
                proposal=db.execute('SELECT payload_json FROM proposals WHERE id=?',(item['proposal_id'],)).fetchone()[0]
                med=json.loads(proposal)['medications'][item['med_index']]
                assert med['name']==item['name'] and med['start']<=row['observed_on']<=med['end']
        for row in db.execute('SELECT * FROM proposals'):
            snapshot=json.loads(row['input_snapshot_json'])
            for table in ('clinical_entries','self_reports','first_visit_versions','medication_marks','messages','observations','adverse_events'):
                for item in snapshot.get(table,[]):
                    key='sequence' if table=='medication_marks' else 'id'
                    assert item==dict(db.execute(f'SELECT * FROM {table} WHERE {key}=?',(item[key],)).fetchone()),(table,row['id'])
            assert all(m['recorded_at']<=row['created_at'] for m in snapshot.get('medication_marks',[]))
        for pid in ('P205','P206','P209','P210'):
            for table in ('clinical_entries','self_reports','first_visit_versions','proposals'):
                assert [tuple(r) for r in db.execute('SELECT * FROM '+table+' WHERE patient_id=?',(pid,))]==[tuple(r) for r in old.execute('SELECT * FROM '+table+' WHERE patient_id=?',(pid,))],(pid,table)
        for patient in db.execute('SELECT id,user_id FROM patients'):
            assert len(assessments.pending(db,dict(id=patient['user_id'],role='patient'),patient['id']))==3
        old_audit={tuple(r) for r in old.execute('SELECT * FROM audit_entries')}
        assert old_audit<={tuple(r) for r in db.execute('SELECT * FROM audit_entries')}
        provenance=json.loads(db.execute("SELECT metadata_json FROM audit_entries WHERE event='fictional.medication_history_reauthored'").fetchone()[0])
        assert provenance['synthetic'] and provenance['simulated_dates'] and not provenance['clinical_review'] and not provenance['medication_eligibility_established']
        assert provenance['authoring_file_sha256']==hashlib.sha256((ROOT/'data/fictional/clinic-medications-20261026.json').read_bytes()).hexdigest()
        assert db.execute('SELECT count(*) FROM clinical_rule_evaluations').fetchone()[0]==0
        assert decisions.reference()['active_rules'] is False
        counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('users','patients','clinical_entries','first_visit_versions','proposals','doctor_confirmations','care_actions','medication_marks','messages','assessments')}
        assert counts['medication_marks']==240
        trigger_count=db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
    return dict(status='PASS',database=str(path),counts=counts,identities_and_ids_preserved=True,
        passwords_and_source_releases_preserved=True,old_audit_preserved=True,unchanged_nonmedicated_patients=4,
        schema_trigger_count=trigger_count,
        current_placeholders=0,integrity='ok',foreign_key_errors=0,courses=courses,provenance=provenance)


if __name__=='__main__':
    result=verify(sys.argv[1],sys.argv[2])
    Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('PASS: names, dates, strengths, reports, marks and snapshots agree; IDs/access/sources preserved')
