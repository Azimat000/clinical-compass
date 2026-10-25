"""Synthetic schedules: approval, per-dose reports, revisions and access boundaries."""
from datetime import timedelta
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch
import test_access
import test_decisions
from apps.compass import medications, decisions, records, access, overview
from apps.compass.db import connect
from apps.compass.web import create_app


class MedicationTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    confirm = test_decisions.DecisionTests.confirm
    draft = test_decisions.DecisionTests.draft

    def schedule(self, **extra):
        day = (records.today()-timedelta(days=2)).isoformat()
        self.db.execute("UPDATE care_relationships SET starts_at='2020-01-01T00:00:00+00:00'")
        data = dict(kind='plan_change', med_change='replace', med_reviewed='yes', med_base=medications.base_id(self.db,'D01'),
                    med_0_name='Вымышленная таблетка 10 мг', med_0_start=day, med_0_days='5',
                    med_0_0_time='08:00', med_0_0_qty='2', med_0_1_time='21:00', med_0_1_qty='8')
        data.update(extra)
        with patch.object(decisions, 'now', return_value=day+'T00:00:00+00:00'):
            p = self.draft(**data)
            self.assertEqual(303, self.confirm(p).status_code)
        return p

    def dose(self, day=None):
        day = day or (records.today()-timedelta(days=1))
        return medications.occurrences(self.db, 'D01', day, day)[0]

    def mark(self, d, **extra):
        data = dict(request_key=secrets.token_hex(16), proposal_id=d['proposal_id'], med_index=str(d['med_index']),
                    slot_index=str(d['slot_index']), dose_on=d['day'], revision=d['revision'], outcome='taken', return_to='demo_patient')
        data.update(extra)
        return self.post('pat-a', '/patients/D01/medication-marks', data)

    def test_approval_gate_latest_home_and_safe_patient_projection(self):
        p=self.draft(kind='plan_change', content='Последний план пациента', basis='PRIVATE_BASIS', uncertainties='PRIVATE_UNCERTAINTY')
        self.assertNotIn('Последний план пациента',self.clients['pat-a'].get('/demo/D01').text)
        self.assertEqual(303,self.confirm(p).status_code)
        html=self.clients['pat-a'].get('/demo/D01').text
        self.assertIn('Последний план пациента',html)
        self.assertNotIn('PRIVATE_BASIS',html);self.assertNotIn('PRIVATE_UNCERTAINTY',html)
        p=self.draft(kind='plan_change', content='Новый черновик')
        self.assertNotIn('Новый черновик',self.clients['pat-a'].get('/demo/D01').text)
        self.assertEqual(303,self.confirm(p,'rejected').status_code)
        self.assertIn('Последний план пациента',self.clients['pat-a'].get('/demo/D01').text)

    def test_split_doses_fraction_course_and_navigation(self):
        self.schedule()
        d=self.dose();self.assertEqual('½',d['amount'])
        c=medications.calendar(self.db,'D01',d['day'])
        self.assertEqual(7,len(c['days']));self.assertEqual(2,len(c['doses']))
        self.assertEqual('2',c['doses'][1]['amount'])
        for uid,url in [('pat-a','/demo/D01'),('pat-a','/patients/D01/decisions'),('doc-a','/patients/D01/decisions')]:
            html=self.clients[uid].get(url+'?med_day='+d['day']).text
            self.assertIn('Вымышленная таблетка',html);self.assertIn('Предыдущая неделя',html);self.assertIn('pill.svg',html)
        end=records.today()+timedelta(days=4)
        self.assertEqual([],medications.occurrences(self.db,'D01',end,end))

    def test_each_intake_independent_partial_and_correction_history(self):
        self.schedule();d=self.dose()
        self.assertEqual(303,self.mark(d,outcome='quantity',actual_quarters='1').status_code)
        d=self.dose();self.assertEqual('partial',d['state']);self.assertEqual('¼',d['actual_label'])
        second=medications.calendar(self.db,'D01',d['day'])['doses'][1]
        self.assertEqual('unknown',second['state'])
        self.assertEqual(303,self.mark(d,outcome='taken').status_code)
        d=self.dose();self.assertEqual('taken',d['state']);self.assertEqual(2,len(d['history']))
        self.assertEqual(303,self.mark(d,outcome='unknown').status_code)
        d=self.dose();self.assertEqual('unknown',d['state']);self.assertEqual(3,len(d['history']))

    def test_retry_stale_tab_conflict_and_no_doctor_reporting(self):
        self.schedule();d=self.dose();key=secrets.token_hex(16)
        self.assertEqual(303,self.mark(d,request_key=key).status_code)
        self.assertEqual(303,self.mark(d,request_key=key).status_code)
        self.assertEqual(409,self.mark(d,request_key=key,outcome='missed').status_code)
        self.assertEqual(409,self.mark(d,outcome='missed').status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM medication_marks').fetchone()[0])
        form=dict(request_key=secrets.token_hex(16),proposal_id=d['proposal_id'],med_index='0',slot_index='0',dose_on=d['day'],outcome='taken')
        self.assertEqual(403,self.post('doc-a','/patients/D01/medication-marks',form).status_code)
        self.assertEqual(404,self.post('pat-b','/patients/D01/medication-marks',form).status_code)
        self.assertEqual(403,self.clients['pat-a'].post('/patients/D01/medication-marks',data=form).status_code)

    def test_future_forged_outside_course_and_invalid_quantity(self):
        self.schedule();d=self.dose()
        for extra in ({'proposal_id':'fake'},{'med_index':'7'},{'slot_index':'3'},{'dose_on':'1900-01-01'}):
            self.assertEqual(409,self.mark(d,**extra).status_code)
        for extra in ({'dose_on':'garbage'},{'outcome':'quantity','actual_quarters':'999'},{'outcome':'quantity','actual_quarters':'-1'},{'outcome':'quantity','actual_quarters':'1.5'}):
            self.assertEqual(400,self.mark(d,**extra).status_code)
        future=self.dose(records.today()+timedelta(days=1))
        self.assertEqual(409,self.mark(future).status_code)

    def test_new_plan_preserves_medications_unless_explicit_replacement(self):
        self.schedule();old=self.dose()
        p=self.draft(kind='plan_change');self.assertEqual(303,self.confirm(p).status_code)
        self.assertEqual(2,len(medications.calendar(self.db,'D01',(records.today()+timedelta(days=1)).isoformat())['doses']))
        p=self.draft(kind='plan_change',med_change='replace',med_reviewed='yes',med_base=medications.base_id(self.db,'D01'))
        self.assertEqual(303,self.confirm(p).status_code)
        self.assertEqual([],medications.calendar(self.db,'D01',(records.today()+timedelta(days=1)).isoformat())['doses'])
        self.assertEqual(303,self.mark(old).status_code)  # Historical dose still belongs to old plan.
        self.assertEqual(1,len(self.dose()['history']))

    def test_duplicate_time_bad_course_missing_review_and_stale_editor_rejected(self):
        base=self.values(kind='plan_change',med_change='replace',med_reviewed='yes',med_0_name='Тест',med_0_start=records.today().isoformat(),med_0_days='3',med_0_0_time='08:00',med_0_0_qty='2')
        for extra in ({'med_reviewed':''},{'med_0_days':'0'},{'med_0_days':'367'},{'med_0_0_qty':'0'},{'med_0_0_time':'24:00'},{'med_0_1_time':'08:00','med_0_1_qty':'4'},{'kind':'referral'},{'med_0_name':'<x>\0'}):
            with self.subTest(extra=extra):
                self.assertEqual(400,self.post('doc-a','/patients/D01/decisions',{**base,**extra}).status_code)
        self.schedule()
        self.assertEqual(409,self.post('doc-a','/patients/D01/decisions',base).status_code)

    def test_medication_report_invalidates_open_draft(self):
        self.schedule();p=self.draft(kind='plan_change')
        self.assertEqual(303,self.mark(self.dose()).status_code)
        self.assertEqual(409,self.confirm(p).status_code)

    def test_unmarked_is_distinct_and_doctor_sees_missed_partial_and_attention(self):
        self.schedule();d=self.dose()
        self.assertEqual('unknown',d['state']);self.assertTrue(d['overdue'])
        self.assertEqual(303,self.mark(d,outcome='missed').status_code)
        c=medications.calendar(self.db,'D01',d['day'])
        self.assertEqual('missed',c['doses'][0]['state'])
        html=self.clients['doc-a'].get('/patients/D01/decisions?med_day='+d['day']).text
        self.assertIn('Пропущено',html);self.assertNotIn('med-mark-form',html)
        page=self.clients['doc-a'].get('/').text
        self.assertIn('Проверить приём препаратов',page);self.assertIn('med_day=',page)

    def test_rollback_immutable_restart_and_html_escape(self):
        self.schedule(med_0_name='<script>fake()</script>')
        d=self.dose()
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                medications.report(self.db,{'id':'pat-a','role':'patient'},'D01',dict(request_key=secrets.token_hex(16),proposal_id=d['proposal_id'],med_index='0',slot_index='0',dose_on=d['day'],revision='',outcome='taken'))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM medication_marks').fetchone()[0])
        self.assertEqual(303,self.mark(d).status_code)
        for sql in ('DELETE FROM medication_marks','UPDATE medication_marks SET actual_quarters=0'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)
        fresh=create_app(self.path).test_client();fresh.set_cookie(access.COOKIE,self.clients['pat-a'].get_cookie(access.COOKIE).value)
        html=fresh.get('/demo/D01?med_day='+d['day']).text
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>fake()',html);self.assertIn('Принято',html)
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0]);self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_invalid_calendar_day_is_400_not_server_error(self):
        for day in ('garbage','9999-12-31','0001-01-01'):
            self.assertEqual(400,self.clients['pat-a'].get('/demo/D01?med_day='+day).status_code)

    def test_concurrent_reports_store_one_and_reject_stale_revision(self):
        from concurrent.futures import ThreadPoolExecutor
        self.schedule();d=self.dose()
        form=dict(proposal_id=d['proposal_id'],med_index='0',slot_index='0',dose_on=d['day'],revision='',outcome='taken')
        def send(key):
            db=connect(self.path)
            try:
                medications.report(db,{'id':'pat-a','role':'patient'},'D01',{**form,'request_key':key})
                return 303
            except decisions.DecisionError as e:
                return e.status
            finally:
                db.close()
        same=secrets.token_hex(16)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([303,303],list(pool.map(send,[same,same])))
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM medication_marks').fetchone()[0])
        self.assertEqual(409,send(secrets.token_hex(16)))

    def test_replacement_retains_earlier_doses_and_cuts_off_future_old_doses(self):
        self.schedule();original=self.dose()
        today=records.today().isoformat()
        # A new approval takes effect exactly at noon, preserving the old morning.
        payload=dict(kind='plan_change',med_change='replace',med_reviewed='yes',med_base=medications.base_id(self.db,'D01'),
                     med_0_name='Новый вымышленный препарат',med_0_start=today,med_0_days='3',med_0_0_time='18:00',med_0_0_qty='3')
        with patch.object(decisions,'now',return_value=today+'T09:00:00+00:00'):
            p=self.draft(**payload);self.assertEqual(303,self.confirm(p).status_code)
        doses=medications.occurrences(self.db,'D01',records.today(),records.today())
        self.assertEqual(['08:00','18:00'],[d['time'] for d in doses]);self.assertEqual('¾',doses[-1]['amount'])
        self.assertEqual(303,self.mark(original).status_code)

    def test_no_javascript_editor_and_patient_forms_have_native_actions(self):
        self.schedule();d=self.dose()
        html=self.clients['pat-a'].get('/demo/D01?med_day='+d['day']).text
        self.assertIn('/medication-marks',html);self.assertIn('name="revision"',html)
        html=self.clients['doc-a'].get('/patients/D01/decisions').text
        self.assertIn('name="med_7_3_qty"',html);self.assertIn('name="med_reviewed"',html)
        self.assertEqual(0,self.db.execute("SELECT count(*) FROM medication_marks").fetchone()[0])

    def test_therapy_stop_requires_explicit_schedule_change(self):
        self.schedule()
        response=self.post('doc-a','/patients/D01/decisions',self.values(kind='therapy_stop'))
        self.assertEqual(409,response.status_code)
        self.assertIn('явно задайте новый состав',response.text)
