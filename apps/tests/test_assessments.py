"""S07: externally specified arithmetic, restricted outputs and durable provenance."""
import json
from datetime import timedelta
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

from apps.compass import access, assessments, records
from apps.compass.db import connect, migrate, MIGRATIONS
from apps.compass.repository import seed_demo
from apps.compass.web import create_app
from test_access import setup_identities, login, csrf


class AssessmentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'assessment.sqlite3'
        self.db = connect(self.path)
        migrate(self.db)
        seed_demo(self.db)
        setup_identities(self.db)
        access.accept_invite(self.db, 'pat-a', access.invite(self.db, 'doc-a', 'D01'))
        self.app = create_app(self.path)
        self.clients = {u: self.app.test_client() for u in ('doc-a', 'doc-b', 'pat-a', 'pat-b')}
        for uid, client in self.clients.items():
            self.assertEqual(302, login(client, uid).status_code)
        self.form = assessments.definition()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def assignment(self, **updates):
        return {'assignment_key': secrets.token_hex(16), 'form_version_id': self.form['id'],
                'age_status': 'known', 'age_years': '35', 'age_basis': 'Сверено по вымышленному профилю D01', **updates}

    def post(self, uid, route, data):
        client = self.clients[uid]
        return client.post(route, data={'csrf': csrf(client), **data})

    def offer(self):
        self.assertEqual(303, self.post('doc-a', '/patients/D01/assessment-requests', self.assignment()).status_code)
        return self.db.execute('SELECT id FROM assessment_requests ORDER BY requested_at DESC').fetchone()[0]

    def test_patient_sees_actual_deadline_in_moscow_including_error_page(self):
        # A 24h storage timestamp may extend beyond the allowed Moscow calendar day.
        task = assessments.with_deadline({'age_on': '2026-10-20', 'expires_at': '2026-10-21T18:00:00+00:00'})
        self.assertEqual('20.10.2026 24:00 МСК', task['deadline_label'])
        self.assertEqual('2026-10-21T00:00:00+03:00', task['deadline_iso'])
        earlier = assessments.with_deadline({'age_on': '2026-10-20', 'expires_at': '2026-10-20T17:30:00+00:00'})
        self.assertEqual('20.10.2026 20:30 МСК', earlier['deadline_label'])
        request_id = self.offer()
        expected = assessments.with_deadline(self.db.execute('SELECT * FROM assessment_requests WHERE id=?', (request_id,)).fetchone())
        for route in ('/demo/D01', '/assessments/' + request_id):
            html = self.clients['pat-a'].get(route).get_data(as_text=True)
            self.assertIn(expected['deadline_label'], html)
            self.assertIn('datetime="' + expected['deadline_iso'] + '"', html)
        error = self.post('pat-a', '/assessments/' + request_id, self.answers('4'))
        self.assertEqual(400, error.status_code)
        self.assertIn(expected['deadline_label'], error.get_data(as_text=True))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM assessment_results').fetchone()[0])

    def answers(self, value='3'):
        return {'form_version_id': self.form['id'], **{f'answer_{i}': value for i in range(1, 43)}}

    def test_manual_reference_vectors_and_every_missing_position(self):
        # Expected values supplied independently by the researcher's official-key review.
        vectors = [([0]*42, {'depression':0,'anxiety':0,'stress':0}),
                   ([3]*42, {'depression':42,'anxiety':42,'stress':42}),
                   ([i%4 for i in range(1,43)], {'depression':21,'anxiety':19,'stress':23})]
        d_positions = {3,5,10,13,16,17,21,24,26,31,34,37,38,42}
        vectors.append(([1 if i in d_positions else 0 for i in range(1,43)], {'depression':14,'anxiety':0,'stress':0}))
        for answers, expected in vectors:
            self.assertEqual(expected, assessments.score_answers(answers,self.form))
        for index in range(42):
            values=[3]*42; values[index]=None
            self.assertIsNone(assessments.score_answers(values,self.form))
        for bad in (-1,4,1.5,True,'1'):
            with self.assertRaises(assessments.AssessmentError):
                assessments.score_answers([bad]+[0]*41,self.form)

    def test_full_patient_submission_doctor_results_and_patient_receipt_only(self):
        task=self.offer()
        page=self.clients['pat-a'].get('/assessments/'+task).get_data(as_text=True)
        self.assertIn(self.form['items'][20],page)
        self.assertIn(self.form['instruction'],page)
        self.assertEqual(42,page.count('<fieldset class="q"'))
        self.assertEqual(303,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        doctor=self.clients['doc-a'].get('/api/patients/D01/assessments').json['assessments'][0]
        self.assertEqual({'depression':42,'anxiety':42,'stress':42},doctor['scores'])
        self.assertEqual([3]*42,doctor['answers'])
        self.assertEqual('pat-a',doctor['actor_id'])
        self.assertEqual(self.form['source']['sha256'],doctor['source_sha256'])
        self.assertEqual(self.form['id'],doctor['scale_version_id'])
        self.assertIsNone(doctor['score'])  # Never invent an overall DASS score.
        for path,heading in (('/assessments/'+task,'Анкета отправлена врачу'),('/demo/D01/forms','Отправлены врачу'),('/demo/D01','Ваши отметки')):
            html=self.clients['pat-a'].get(path).get_data(as_text=True)
            self.assertIn(heading,html)
            for prohibited in ('Депрессивные симптомы:','42 / 42',self.form['items'][20],doctor['id'],'scores_json','answers_json'):
                self.assertNotIn(prohibited,html)
        receipts=self.clients['pat-a'].get('/api/patients/D01/assessments').json['assessments']
        self.assertEqual({'request_id','requested_at','recorded_at','form_version_id'},set(receipts[0]))
        html=self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertIn('Депрессивные симптомы: 42 / 42',html)
        self.assertIn('Исходные ответы (42 пункта)',html)
        self.assertIn(self.form['items'][20],html)
        for table in ('care_actions','proposals','risk_evaluations','alerts','doctor_confirmations'):
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM '+table).fetchone()[0])

    def test_incomplete_is_saved_without_any_subscale_and_gaps_are_not_zero(self):
        task=self.offer(); data=self.answers(); data['answer_21']=''
        self.assertEqual(303,self.post('pat-a','/assessments/'+task,data).status_code)
        row=assessments.history(self.db,{'id':'doc-a','role':'doctor'},'D01')[0]
        self.assertIsNone(row['scores']); self.assertEqual('incomplete',row['completeness'])
        self.assertIsNone(row['answers'][20])
        trend=assessments.trends([row])[0]
        self.assertTrue(all(not s['points'] for s in trend['series']))
        self.assertIn('Ни одна сумма не рассчитана',self.clients['doc-a'].get('/demo/D01').get_data(as_text=True))

    def test_patient_cannot_choose_a_task_or_other_role_and_csrf_is_enforced(self):
        for uid,pid,status in [('pat-a','D01',403),('doc-b','D01',404),('doc-a','D02',404)]:
            self.assertEqual(status,self.post(uid,f'/patients/{pid}/assessment-requests',self.assignment()).status_code)
        task=self.offer()
        for uid in ('doc-b','pat-b'):
            self.assertEqual(404,self.clients[uid].get('/assessments/'+task).status_code)
            self.assertEqual(404,self.post(uid,'/assessments/'+task,self.answers()).status_code)
            self.assertEqual(404,self.clients[uid].get('/api/patients/D01/assessments').status_code)
        self.assertEqual(403,self.clients['pat-a'].post('/assessments/'+task,data=self.answers()).status_code)
        self.assertEqual(401,self.app.test_client().get('/api/patients/D01/assessments').status_code)
        self.assertEqual(302,self.app.test_client().get('/assessments/'+task).status_code)
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(404,self.clients['doc-a'].get('/api/patients/D01/assessments').status_code)
        access.accept_invite(self.db,'pat-a',access.invite(self.db,'doc-b','D01'))
        self.assertEqual(409,self.post('doc-b','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_age_unknown_conflicting_underage_and_fresh_explicit_source(self):
        invalid=[{'age_status':'unknown','age_years':''},{'age_status':'conflicting'},
                 {'age_years':'17'},{'age_years':'121'},{'age_basis':''},
                 {'age_years':'18','birth_date':'2000-01-01'}]
        for data in invalid:
            self.assertEqual(400,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(**data)).status_code)
        self.db.execute("UPDATE patients SET age_status='conflicting' WHERE id='D01'")
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        self.db.execute("UPDATE patients SET age_status='unknown',age_years=NULL WHERE id='D01'")
        # Fresh known data are allowed; an unknown old profile is never silently converted into adulthood.
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_years='18')).status_code)
        record={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                'age_status':'known','age_years':'19'}
        records.save(self.db,{'id':'doc-a','role':'doctor'},'D01','visit',record)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_years='18')).status_code)

    def test_new_age_conflict_after_assignment_is_rechecked_on_submission(self):
        task=self.offer()
        record={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                'age_status':'conflicting','age_detail':'Несовпадающие вымышленные даты'}
        records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',record)
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_historical_latest_age_conflict_is_not_silently_ignored(self):
        record={'request_key':secrets.token_hex(16),'observed_on':(records.today()-timedelta(days=1)).isoformat(),
                'age_status':'conflicting','age_detail':'Несовпадающие сведения в предыдущей записи'}
        records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',record)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        record={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                'age_status':'known','age_years':'35','summary':'Врач сверил вымышленные источники возраста.'}
        records.save(self.db,{'id':'doc-a','role':'doctor'},'D01','visit',record)
        # A normal visit no longer silently resolves an earlier explicit conflict.
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)

    def test_own_receipt_survives_relationship_end_without_reopening_submission(self):
        task=self.offer(); self.post('pat-a','/assessments/'+task,self.answers())
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01'")
        response=self.clients['pat-a'].get('/assessments/'+task)
        self.assertEqual(200,response.status_code)
        self.assertIn('Анкета отправлена врачу',response.get_data(as_text=True))
        self.assertNotIn('42 / 42',response.get_data(as_text=True))
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)

    def test_retry_atomicity_immutable_results_and_no_fake_expert(self):
        offer=self.assignment()
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',offer).status_code)
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',offer).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',{**offer,'age_basis':'другой источник'}).status_code)
        task=self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        with patch.object(access,'audit',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                assessments.submit(self.db,{'id':'pat-a','role':'patient'},task,self.answers())
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessment_results').fetchone()[0])
        for _ in range(2):
            self.assertEqual(303,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,{**self.answers(),'answer_1':'0'}).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])
        for statement in ("UPDATE assessments SET answers_json='[]'",'DELETE FROM assessments',
                          "UPDATE assessment_results SET scores_json='{}'",'DELETE FROM assessment_results',
                          "UPDATE catalog_versions SET definition_json='{}'", "UPDATE source_versions SET sha256='changed'"):
            with self.assertRaises(sqlite3.IntegrityError): self.db.execute(statement)
        catalogue=self.db.execute('SELECT * FROM catalog_versions').fetchone()
        self.assertIsNone(catalogue['reviewed_by']); self.assertIsNone(catalogue['reviewed_at'])
        self.assertEqual('inactive',catalogue['status'])
        audit=str([tuple(r) for r in self.db.execute("SELECT * FROM audit_entries WHERE event LIKE 'assessment.%'")])
        self.assertNotIn('answers',audit); self.assertNotIn('scores',audit)

    def test_invalid_answers_duplicate_fields_versions_expiry_and_retirement(self):
        task=self.offer()
        for changes in ({'answer_1':'-1'},{'answer_1':'4'},{'answer_1':'1.0'},{'answer_43':'1'}):
            self.assertEqual(400,self.post('pat-a','/assessments/'+task,{**self.answers(),**changes}).status_code)
        values=MultiDict(self.answers()); values.add('answer_1','0')
        with self.assertRaises(assessments.AssessmentError): assessments.parse_answers(values)
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,{**self.answers(),'form_version_id':'other'}).status_code)
        self.db.execute("UPDATE catalog_versions SET status='retired'")
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.db.execute("UPDATE catalog_versions SET status='inactive'")
        with patch.object(records,'today',return_value=records.today().replace(year=2027)):
            self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_source_provenance_xss_doctor_capture_and_restart(self):
        self.assertEqual(303,self.post('doc-a','/patients/D01/assessment-requests',self.assignment(age_basis='<script>bad</script>')).status_code)
        task=self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        self.assertEqual(303,self.post('doc-a','/assessments/'+task,self.answers('0')).status_code)
        page=self.clients['doc-a'].get('/demo/D01').get_data(as_text=True)
        self.assertIn('&lt;script&gt;bad',page); self.assertNotIn('<script>bad',page)
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        row=fresh.get('/api/patients/D01/assessments').json['assessments'][0]
        self.assertEqual({'depression':0,'anxiety':0,'stress':0},row['scores'])
        self.assertEqual('doc-a',row['actor_id'])
        for field in ('completed_at','observed_on','recorded_at','scale_version_id','scoring_version','source_sha256','age_basis'):
            self.assertTrue(row[field])

    def test_withdrawn_source_disables_measurement_without_destroying_diary(self):
        self.db.execute("UPDATE source_versions SET rights_status='unknown'")
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,self.clients['doc-a'].get_cookie(access.COOKIE).value)
        self.assertEqual(200,fresh.get('/demo/D01').status_code)
        self.assertEqual(409,self.post('doc-a','/patients/D01/assessment-requests',self.assignment()).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessments').fetchone()[0])

    def test_versions_are_separate_and_patient_diary_is_not_a_score(self):
        task=self.offer(); self.post('pat-a','/assessments/'+task,self.answers('0'))
        row=assessments.history(self.db,{'id':'doc-a','role':'doctor'},'D01')[0]
        other={**row,'scale_version_id':'different-version'}
        self.assertEqual(2,len(assessments.trends([row,other])))
        for day,value in [('2026-10-17','worse'),('2026-10-18','better')]:
            records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',{
                'request_key':secrets.token_hex(16),'observed_on':day,'wellbeing':value})
        diary=records.wellbeing_trend(records.history(self.db,'D01'))
        self.assertEqual(['Хуже','Лучше'],[p['label'] for p in diary])
        page=self.clients['pat-a'].get('/demo/D01/diary').get_data(as_text=True)
        self.assertIn('Дневник',page)
        self.assertIn('Хуже',page);self.assertIn('Лучше',page)
        self.assertNotIn('Динамика DASS-42',page)
        self.assertNotRegex(page,r'Депрессивные|Тревожные|из 42')

    def test_migration_from_s06_preserves_every_prior_row(self):
        old=connect(Path(self.tmp.name)/'s06.sqlite3')
        directory=Path(self.tmp.name)/'s06-migrations'; directory.mkdir()
        for name in ('001_initial.sql','002_access.sql','003_records.sql'):
            (directory/name).write_bytes((MIGRATIONS/name).read_bytes())
        migrate(old,directory); seed_demo(old); setup_identities(old)
        tables=[r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '%_search%' AND name!='schema_migrations'")]
        before={t:[tuple(r) for r in old.execute('SELECT * FROM "'+t+'"')] for t in tables}
        migrate(old)
        for table,rows in before.items(): self.assertEqual(rows,[tuple(r) for r in old.execute('SELECT * FROM "'+table+'"')])
        self.assertEqual([],old.execute('PRAGMA foreign_key_check').fetchall())
        old.close()


if __name__=='__main__': unittest.main()
