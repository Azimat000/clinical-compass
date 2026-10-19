"""S12: literal evidence, privileged review, unsupported input and isolation."""
import io
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from test_records import RecordsTests
from apps.compass import extraction, decisions, access
from apps.compass.web import create_app
from test_access import csrf


class ExtractionTests(unittest.TestCase):
    setUp = RecordsTests.setUp
    tearDown = RecordsTests.tearDown
    def post_import(self, uid='doc-a', pid='D01', **values):
        client=self.clients[uid]
        return client.post(f'/patients/{pid}/imports',data={'csrf':csrf(client),
            'request_key':secrets.token_hex(16),'source_text':'35 лет. F41.1. Авиандр 10 мг.',**values})

    def test_literal_spans_negation_conflicts_dates_and_high_risk_uncertainty(self):
        text='В анкете 31 год; врач указал 38 лет. Авиандр 10 мг; Авиандр 20 мг. 31.09.2026. Беременность отрицает. Он хотел причинить себе вред.'
        result=extraction.extract(text)
        for c in result['candidates']:
            self.assertEqual(c['quote'],text[c['span']['start']:c['span']['end']])
        self.assertEqual({'conflicting'},{c['assertion'] for c in result['candidates'] if c['field']=='age_years'})
        self.assertEqual({'conflicting'},{c['assertion'] for c in result['candidates'] if c['field']=='dose'})
        self.assertIn(('event_date','invalid',None),[(c['field'],c['assertion'],c['value']) for c in result['candidates']])
        self.assertIn(('pregnancy_status','negated',False),[(c['field'],c['assertion'],c['value']) for c in result['candidates']])
        self.assertEqual('unknown',next(c['assertion'] for c in result['candidates'] if c['field']=='self_harm_report'))
        self.assertIn('medication_allergy',result['unextracted_fields'])
        self.assertEqual([],extraction.extract('Произвольная история без распознанных слов')['candidates'])

    def test_import_retries_review_correction_add_reject_persistence_and_no_actions(self):
        text='35 лет. F41.1. <script>bad</script>'
        key=secrets.token_hex(16)
        initial_outbox=self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0]
        before=decisions.snapshot(self.db,'D01',self.db.execute('SELECT id FROM care_relationships').fetchone()[0])
        self.assertEqual(303,self.post_import(source_text=text,request_key=key).status_code)
        self.assertEqual(303,self.post_import(source_text=text,request_key=key).status_code)
        self.assertEqual(409,self.post_import(source_text=text+'x',request_key=key).status_code)
        item=extraction.history(self.db,'D01')[0]
        c=item['result']['candidates'][0]
        form={'csrf':csrf(self.clients['doc-a']),'request_key':secrets.token_hex(16),
              'candidate_id':c['id'],'field':c['field'],'assertion':c['assertion'],
              'value':extraction.canonical(c['value']),'quote':c['quote'],'reason':'Сверено с вымышленным источником','disposition':'accept'}
        path=f"/patients/D01/imports/{item['id']}/review"
        client=self.clients['doc-a']
        self.assertEqual(303,client.post(path,data=form).status_code)
        self.assertEqual(303,client.post(path,data=form).status_code)
        self.assertEqual(409,client.post(path,data={**form,'reason':'другое'}).status_code)
        self.assertEqual(400,client.post(path,data={**form,'request_key':secrets.token_hex(16),'value':'70'}).status_code)
        self.assertEqual(400,client.post(path,data={**form,'quote':'выдуманное основание'}).status_code)
        for kind in ('correct','reject','add'):
            self.assertEqual(303,client.post(path,data={**form,'request_key':secrets.token_hex(16),'disposition':kind,
                             'candidate_id':'' if kind=='add' else c['id'],'value':'требует уточнения'}).status_code)
        self.assertEqual(4,self.db.execute('SELECT count(*) FROM extraction_reviews').fetchone()[0])
        self.assertNotEqual(before,decisions.snapshot(self.db,'D01',item['relationship_id']))
        fresh=create_app(self.path).test_client()
        fresh.set_cookie(access.COOKIE,client.get_cookie(access.COOKIE).value)
        page=fresh.get('/patients/D01/imports')
        self.assertEqual(200,page.status_code)
        self.assertIn('&lt;script&gt;',page.get_data(as_text=True))
        self.assertNotIn('<script>bad',page.get_data(as_text=True))
        for table in ('proposals','care_actions','clinical_entries','clinical_contexts','critical_events'):
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM '+table).fetchone()[0],table)
        self.assertEqual(initial_outbox,self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE text_imports SET source_text='changed'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM extraction_reviews')
        self.assertNotIn('bad',str([tuple(r) for r in self.db.execute("SELECT * FROM audit_entries WHERE event LIKE 'extraction.%'")]))

    def test_unsupported_input_limits_and_atomic_rollback(self):
        for value in ('','a\x00b','x'*24001,'9'*5000+' раза в день'):
            self.assertEqual(400,self.post_import(source_text=value).status_code)
        self.assertEqual(413,self.post_import(source_text='я'*12001).status_code)
        for filename,raw in [('a.pdf',b'%PDF-'),('a.txt',b'\xff'),('a.txt',b'x'*24001),('a.txt',b'PK\x00\x00')]:
            self.assertEqual(400,self.post_import(source_text='',file=(io.BytesIO(raw),filename)).status_code)
        self.assertEqual(303,self.post_import(source_text='',file=(io.BytesIO('45 лет'.encode()),'a.txt')).status_code)
        self.assertEqual(400,self.post_import(file=(io.BytesIO(b'text'),'a.txt')).status_code)
        with patch.object(access,'audit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                extraction.save_import(self.db,{'id':'doc-a','role':'doctor'},'D01','50 лет',secrets.token_hex(16))
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM text_imports').fetchone()[0])

    def test_new_import_and_review_require_rereview_of_pending_decision(self):
        from test_decisions import DecisionTests
        doctor={'id':'doc-a','role':'doctor'}
        def draft():
            return decisions.draft(self.db,doctor,'D01',DecisionTests.values(None))
        def confirm(pid):
            version=self.db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()[0]
            return decisions.confirm(self.db,doctor,'D01',pid,{'version':str(version),'decision':'approved','reviewed':'yes','rationale':'Synthetic'})
        pending=draft()
        self.post_import()
        with self.assertRaises(decisions.DecisionError) as error:
            confirm(pending)
        self.assertEqual(409,error.exception.status)
        pending=draft()
        item=extraction.history(self.db,'D01')[0]
        c=item['result']['candidates'][0]
        extraction.review(self.db,doctor,'D01',item['id'],{'request_key':secrets.token_hex(16),
            'candidate_id':c['id'],'field':c['field'],'assertion':'unknown','value':'needs check',
            'quote':c['quote'],'reason':'Synthetic','disposition':'correct'})
        with self.assertRaises(decisions.DecisionError) as error:
            confirm(pending)
        self.assertEqual(409,error.exception.status)
        confirm(draft())
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_access_csrf_ended_pair_and_other_import_review(self):
        for uid,pid,expected in [('pat-a','D01',403),('doc-b','D01',404),('doc-a','D02',404)]:
            self.assertEqual(expected,self.post_import(uid,pid).status_code)
            self.assertEqual(expected,self.clients[uid].get(f'/patients/{pid}/imports').status_code)
        self.assertEqual(403,self.clients['doc-a'].post('/patients/D01/imports',data={'source_text':'25 лет'}).status_code)
        self.assertEqual(303,self.post_import().status_code)
        iid=extraction.history(self.db,'D01')[0]['id']
        self.assertEqual(403,self.clients['pat-a'].post(f'/patients/D01/imports/{iid}/review',data={'csrf':csrf(self.clients['pat-a'])}).status_code)
        self.db.execute("UPDATE care_relationships SET ends_at='2026-10-18'")
        self.assertEqual(404,self.post_import().status_code)


del RecordsTests
