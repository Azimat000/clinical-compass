"""Prescribed-drug diary reports, synthetic access and atomic persistence checks."""
import secrets
import unittest
from unittest.mock import patch
import test_access
import test_decisions
import test_medications
from apps.compass import access, medication_feedback as feedback, medications, overview, records
from apps.compass.web import create_app


class MedicationFeedbackTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm
    schedule = test_medications.MedicationTests.schedule

    def form(self, **extra):
        return dict(observed_on=records.today().isoformat(), wellbeing='same', request_key=secrets.token_hex(16),
                    medication_feedback_version=feedback.VERSION,
                    medication_feedback_plan=medications.base_id(self.db, 'D01'), **extra)

    def send(self, form, who='pat-a'):
        return self.post(who, '/patients/D01/self-reports', form)

    def test_only_approved_patient_prescriptions_and_all_three_independent_choices(self):
        p = self.schedule(med_1_name='Вторая вымышленная таблетка', med_1_start=records.today().isoformat(), med_1_days='4', med_1_0_time='10:00', med_1_0_qty='4')
        draft = self.draft(kind='plan_change', med_change='replace', med_reviewed='yes', med_base=p['id'],
                           med_0_name='PRIVATE_UNAPPROVED', med_0_start=records.today().isoformat(), med_0_days='2', med_0_0_time='10:00', med_0_0_qty='4')
        page = self.clients['pat-a'].get('/demo/D01/report').text
        for name in ['Вымышленная таблетка', 'Вторая вымышленная таблетка', 'Есть эффект', 'Нет эффекта', 'Нежелательные явления']:
            self.assertIn(name, page)
        self.assertNotIn('PRIVATE_UNAPPROVED', page)
        self.assertNotIn('Вымышленная таблетка', self.clients['pat-b'].get('/demo/D02/report').text)
        self.assertEqual(6, page.count('type="checkbox"'))
        for removed in ['Дополнительные сведения для врача', 'Принимали Авиандр?', 'name="age_status"', 'name="safety_taken"', 'name="adverse_events_text"']:
            self.assertNotIn(removed, page)
        self.assertEqual(303, self.confirm(draft, 'rejected').status_code)
        self.assertIn('Вторая вымышленная таблетка', self.clients['pat-a'].get('/demo/D01/report').text)

    def test_multi_response_per_drug_visible_to_both_roles_and_attention_survives_silence(self):
        self.schedule()
        form = self.form(complaints_status='known', complaints_text='Жалобы сохранились',
                         feedback_0_effect='yes', feedback_0_effect_text='Стал спокойнее',
                         feedback_0_no_effect='yes', feedback_0_no_effect_text='Сон не изменился',
                         feedback_0_adverse='yes', feedback_0_adverse_text='Появилась тошнота')
        result = self.send(form); self.assertEqual(303, result.status_code)
        entry = records.history(self.db, 'D01')[0]
        self.assertEqual(3, len(entry['payload']['medication_feedback'][0]['responses']))
        for who, path in [('pat-a','/demo/D01/diary'),('doc-a','/demo/D01'),('doc-a','/patients/D01/follow-up')]:
            page = self.clients[who].get(path).text
            for text in ['Стал спокойнее', 'Сон не изменился', 'Появилась тошнота', 'Жалобы сохранились']:
                self.assertIn(text, page)
        self.assertEqual(1, self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        self.assertEqual(303, self.send(self.form()).status_code)
        patient = self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone()
        row = overview.summary(self.db, {'id':'doc-a','role':'doctor'}, patient)
        self.assertTrue(row['attention']); self.assertIn('Требует внимания', row['reason']['text'])
        self.assertEqual('entry-' + entry['id'], row['reason']['anchor'])
        page = self.clients['doc-a'].get('/?show=flagged').text
        self.assertIn('Появилась тошнота', page);self.assertIn('#entry-'+entry['id'],page)
        self.assertNotIn('Появилась тошнота',self.clients['doc-b'].get('/').text)

    def test_required_descriptions_format_and_no_partial_writes(self):
        self.schedule()
        for extra, status in [({'feedback_0_effect':'yes'},400),({'feedback_0_adverse':'yes','feedback_0_adverse_text':'  '},400),
                              ({'feedback_0_effect':'bad'},400),({'feedback_8_effect':'yes'},400),
                              ({'feedback_0_effect_text':'x'*2001},400),({'feedback_0_effect_text':'bad\x00'},400),
                              ({'feedback_7_effect':'yes','feedback_7_effect_text':'Not prescribed'},409),
                              ({'medication_feedback_plan':'0'*32,'feedback_0_effect':'yes','feedback_0_effect_text':'Fake'},409)]:
            with self.subTest(extra=extra):
                before=self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0]
                self.assertEqual(status, self.send({**self.form(), **extra}).status_code)
                self.assertEqual(before,self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        r=self.send(self.form(feedback_0_effect='yes',summary='KEEP_ME'))
        self.assertIn('KEEP_ME',r.text);self.assertIn('name="feedback_0_effect" value="yes"',r.text)
        self.assertIn('Добавьте описание выбранной отметки',r.text)

    def test_retry_restart_rollback_and_stale_prescription(self):
        self.schedule()
        form=self.form(feedback_0_adverse='yes',feedback_0_adverse_text='Вымышленная реакция')
        with patch.object(access,'audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',form)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])
        first=self.send(form);self.assertEqual(303,first.status_code)
        self.assertEqual(first.location,self.send(form).location)
        old=self.form(feedback_0_effect='yes',feedback_0_effect_text='Old')
        self.schedule(med_0_name='Замена')
        stale=self.send(old)
        self.assertEqual(409,stale.status_code)
        self.assertIn('Old',stale.text)
        self.assertIn('Врач изменил назначения',stale.text)
        self.assertIn('Вымышленная таблетка',stale.text)
        # An already committed receipt stays idempotent after a schedule replacement.
        self.assertEqual(first.location,self.send(form).location)
        self.assertEqual(409,self.send({**form,'feedback_0_adverse_text':'Changed'}).status_code)
        fresh=create_app(self.path).test_client();fresh.set_cookie(access.COOKIE,self.clients['pat-a'].get_cookie(access.COOKIE).value)
        self.assertIn('Вымышленная реакция',fresh.get('/demo/D01/diary').text)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])

    def test_private_unfinished_draft_restores_selected_and_unselected_text(self):
        self.schedule()
        form=self.form(draft_revision='0', feedback_0_adverse='yes',feedback_0_adverse_text='',feedback_0_effect_text='Unfinished')
        url='/patients/D01/self-report-draft'
        self.assertEqual(303,self.post('pat-a',url,form).status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM adverse_events').fetchone()[0])
        page=self.clients['pat-a'].get('/demo/D01/report').text
        self.assertIn('Черновик восстановлен',page);self.assertIn('Unfinished',page)
        self.assertIn('name="feedback_0_adverse" value="yes" aria-controls="detail-feedback_0_adverse" checked',page)
        self.assertNotIn('Unfinished',self.clients['doc-a'].get('/demo/D01').text)
        state=self.clients['pat-a'].get(url).json
        form['draft_revision']=str(state['revision']);form['feedback_0_adverse_text']='Личный текст'
        self.assertEqual(303,self.send(form).status_code)
        self.assertFalse(self.clients['pat-a'].get(url).json['active'])
        self.assertNotIn('effect',records.history(self.db,'D01')[0]['payload']['medication_feedback'][0]['responses'])

    def test_access_csrf_escaping_and_no_prescriptions(self):
        empty=self.clients['pat-a'].get('/demo/D01/report').text
        self.assertIn('Врач пока не назначил препараты через сайт',empty)
        self.assertEqual(303,self.send(self.form()).status_code)
        self.schedule(med_0_name='<script>NAME</script>')
        form=self.form(feedback_0_effect='yes',feedback_0_effect_text='<script>DESCRIPTION</script>')
        for who,status in [('doc-a',403),('pat-b',404)]:
            self.assertEqual(status,self.send(form,who).status_code)
        self.assertEqual(403,self.clients['pat-a'].post('/patients/D01/self-reports',data=form).status_code)
        self.assertEqual(303,self.send(form).status_code)
        for who,path in [('pat-a','/demo/D01/diary'),('doc-a','/demo/D01')]:
            page=self.clients[who].get(path).text
            self.assertIn('&lt;script&gt;DESCRIPTION',page);self.assertNotIn('<script>DESCRIPTION',page)
        self.assertEqual('ok',self.db.execute('PRAGMA integrity_check').fetchone()[0])
        self.assertEqual([],self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_complaints_preserve_all_previous_states_validation_and_private_draft(self):
        for status, detail in [('known','Беспокоит сон'), ('conflicting','Сведения о жалобах расходятся'), ('unknown',''), ('denied','')]:
            self.assertEqual(303,self.send(self.form(complaints_status=status,complaints_text=detail)).status_code)
            saved=records.history(self.db,'D01')[0]['payload']['fields']['complaints']
            self.assertEqual({'status':status,'text':detail or None},saved)
        for status, detail in [('known',''), ('unknown','Незавершённое описание')]:
            response=self.send(self.form(complaints_status=status,complaints_text=detail))
            self.assertEqual(400,response.status_code)
            self.assertIn('name="complaints_status"',response.text)
            self.assertIn(detail,response.text)
        draft=self.form(draft_revision='0',complaints_status='known',complaints_text='Личная жалоба')
        self.assertEqual(303,self.post('pat-a','/patients/D01/self-report-draft',draft).status_code)
        self.assertIn('Личная жалоба',self.clients['pat-a'].get('/demo/D01/report').text)
        self.assertNotIn('Личная жалоба',self.clients['doc-a'].get('/demo/D01').text)
