"""Private unfinished work, conflict handling and atomic consumption on synthetic data."""
import json
import re
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from apps.compass import report_drafts as drafts, records, ages
from apps.compass.db import connect, migrate
from apps.compass.web import create_app
import test_s26d
import test_access


class ReportDraftTests(unittest.TestCase):
    setUp = test_s26d.PatientSendTests.setUp
    tearDown = test_s26d.PatientSendTests.tearDown
    link = test_s26d.PatientSendTests.link
    offer = test_s26d.PatientSendTests.offer
    post = test_s26d.PatientSendTests.post
    counts = test_s26d.PatientSendTests.counts
    url = '/patients/D01/self-report-draft'
    user = {'id':'pat-a','role':'patient'}

    def values(self, **kw):
        return {'request_key':secrets.token_hex(16),'draft_revision':'0','observed_on':records.today().isoformat(),
                'summary':'  Личный синтетический черновик\nне отправлен  ',**kw}

    def send(self, values, who='pat-a', url=None):
        c = self.clients[who]
        return c.post(url or self.url,data={'csrf':test_access.csrf(c),**values},headers={'Accept':'application/json'})

    def test_unfinished_values_restore_after_restart_and_no_clinical_side_effects(self):
        form = self.values(observed_on='',age_status='known',age_years='',complaints_status='known',complaints_text='',
                           adverse_events_status='denied',adverse_events_text='Противоречие ещё не исправлено',
                           safety_form_version='aviandr-safety-v1',safety_taken='present',safety_rigidity='present')
        before = self.counts(); age = ages.source_snapshot(self.db,self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone())
        response = self.send(form)
        self.assertEqual(200,response.status_code)
        self.assertEqual(before,self.counts());self.assertEqual(age,ages.source_snapshot(self.db,self.db.execute("SELECT * FROM patients WHERE id='D01'").fetchone()))
        self.db.close();self.db=connect(self.path);migrate(self.db)
        app=create_app(self.path);c=app.test_client()
        # The same valid authenticated session survives application reconstruction.
        from apps.compass import access
        c.set_cookie(access.COOKIE,self.clients['pat-a'].get_cookie(access.COOKIE).value)
        data=c.get(self.url).json
        self.assertTrue(data['active'])
        for key,value in form.items():
            if key!='draft_revision':self.assertEqual(value,data['values'][key],key)
        page=c.get('/demo/D01').text
        self.assertIn('Черновик восстановлен',page);self.assertIn('Противоречие ещё не исправлено',page)
        self.assertIn('value="'+form['request_key']+'"',page)
        stored=self.db.execute('SELECT values_json FROM self_report_drafts').fetchone()[0]
        self.assertNotIn('csrf',stored);self.assertNotIn('draft_revision',stored)

    def test_only_owner_can_read_or_write_and_doctor_cannot_find_private_text(self):
        marker='PRIVATE-DRAFT-MARKER-ONLY'
        self.assertEqual(200,self.send(self.values(summary=marker)).status_code)
        for who,status in [('doc-a',403),('doc-b',403),('pat-b',404)]:
            c=self.clients[who]
            self.assertEqual(status,c.get(self.url).status_code)
            self.assertEqual(status,self.send(self.values(),who).status_code)
        self.assertEqual(302,self.app.test_client().get(self.url).status_code)
        for path in ['/demo/D01','/patients/D01/follow-up','/notifications']:
            self.assertNotIn(marker,self.clients['doc-a'].get(path).text)
        self.assertIn('Пациенты не найдены',self.clients['doc-a'].get('/?q='+marker).text)
        self.assertNotIn(marker,self.clients['pat-b'].get('/demo/D02').text)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM self_report_drafts').fetchone()[0])

    def test_save_does_not_require_doctor_relationship(self):
        self.db.execute("UPDATE care_relationships SET ends_at='2000-01-01T00:00:00+00:00'")
        before=self.counts()
        self.assertEqual(200,self.send(self.values()).status_code)
        self.assertEqual(before,self.counts())

    def test_lost_save_response_identical_retry_and_stale_edit(self):
        form=self.values();first=self.send(form)
        self.assertEqual(200,first.status_code)
        self.assertEqual(first.json,self.send(form).json)
        changed={**form,'summary':'Другой текст'}
        self.assertEqual(409,self.send(changed).status_code)
        changed['draft_revision']=str(first.json['revision'])
        newer=self.send(changed)
        self.assertEqual(200,newer.status_code)
        self.assertEqual(409,self.send(form).status_code)
        self.assertEqual('Другой текст',self.clients['pat-a'].get(self.url).json['values']['summary'])

    def test_concurrent_tabs_cannot_silently_replace_one_another(self):
        forms=[self.values(summary='Вкладка А'),self.values(summary='Вкладка Б')]
        def save(form):
            db=connect(self.path)
            try:
                try:return drafts.save(db,self.user,'D01',form)['revision']
                except drafts.Error as error:return error.status
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,forms))
        self.assertEqual([1,409],sorted(results))
        self.assertIn(self.clients['pat-a'].get(self.url).json['values']['summary'],['Вкладка А','Вкладка Б'])

    def test_send_clears_content_and_late_autosave_never_resurrects_it(self):
        form=self.values();saved=self.send(form);form['draft_revision']=str(saved.json['revision'])
        before=self.counts()
        sent=self.send(form,url='/patients/D01/self-reports')
        self.assertEqual(200,sent.status_code)
        state=self.clients['pat-a'].get(self.url).json
        self.assertFalse(state['active']);self.assertEqual({},state['values'])
        counts=self.counts();self.assertEqual(before['clinical_entries']+1,counts['clinical_entries'])
        self.assertEqual(409,self.send(form).status_code)
        self.assertEqual(sent.json,self.send(form,url='/patients/D01/self-reports').json)
        self.assertEqual(counts,self.counts())
        self.assertNotIn('Черновик восстановлен',self.clients['pat-a'].get('/demo/D01').text)

    def test_mid_send_failure_rolls_back_record_and_keeps_draft(self):
        form=self.values();response=self.send(form);form['draft_revision']=str(response.json['revision'])
        before=self.counts();saved=self.clients['pat-a'].get(self.url).json
        with patch.object(drafts,'consumed',side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaises(sqlite3.OperationalError):records.save(self.db,self.user,'D01','self_report',form)
        self.assertEqual(before,self.counts());self.assertEqual(saved,self.clients['pat-a'].get(self.url).json)
        records.save(self.db,self.user,'D01','self_report',form)
        self.assertFalse(self.clients['pat-a'].get(self.url).json['active'])

    def test_delete_clear_retry_and_tombstone_reject_old_request(self):
        form=self.values();save=self.send(form);form['draft_revision']=str(save.json['revision'])
        before=self.counts();deletion={**form,'draft_action':'delete'}
        response=self.send(deletion)
        self.assertEqual(200,response.status_code);self.assertFalse(response.json['active'])
        self.assertEqual(response.json,self.send(deletion).json)
        self.assertEqual(409,self.send(form).status_code)
        self.assertEqual({},self.clients['pat-a'].get(self.url).json['values'])
        self.assertEqual(before,self.counts())
        fresh=self.values(draft_revision=str(response.json['revision']))
        self.assertEqual(200,self.send(fresh).status_code)
        self.assertEqual(409,self.send(deletion).status_code)

    def test_changed_draft_in_other_tab_blocks_stale_final_send(self):
        form=self.values();first=self.send(form);form['draft_revision']=str(first.json['revision'])
        newer={**form,'summary':'Новая версия'};self.assertEqual(200,self.send(newer).status_code)
        before=self.counts()
        r=self.send(form,url='/patients/D01/self-reports')
        self.assertEqual(409,r.status_code);self.assertEqual(before,self.counts())
        self.assertEqual('Новая версия',self.clients['pat-a'].get(self.url).json['values']['summary'])

    def test_csrf_limits_xss_and_native_form(self):
        before=self.counts()
        self.assertEqual(403,self.clients['pat-a'].post(self.url,data=self.values()).status_code)
        self.assertEqual(400,self.send(self.values(summary='x'*4001)).status_code)
        self.assertEqual(400,self.send(self.values(wellbeing='unrecognized')).status_code)
        self.assertEqual(400,self.send(self.values(summary='bad\x00text')).status_code)
        form=self.values(summary='<script>window.BAD=true</script>')
        self.assertEqual(303,self.post('pat-a',self.url,form).status_code)
        page=self.clients['pat-a'].get('/demo/D01').text
        self.assertIn('&lt;script&gt;window.BAD=true&lt;/script&gt;',page)
        self.assertNotIn('<script>window.BAD=true</script>',page)
        state=self.clients['pat-a'].get(self.url).json
        self.assertEqual(303,self.post('pat-a',self.url,{**form,'draft_revision':str(state['revision']),'draft_action':'delete'}).status_code)
        self.assertFalse(self.clients['pat-a'].get(self.url).json['active'])
        self.assertEqual(before,self.counts())
