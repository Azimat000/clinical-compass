"""S12: literal evidence, privileged review, unsupported input and isolation."""
import io
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch
from test_records import RecordsTests
from apps.compass import extraction, decisions, access
from werkzeug.datastructures import FileStorage
from test_access import csrf

DOCTOR={'id':'doc-a','role':'doctor'}


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

    # UI11: the documents screen and its web endpoints are gone; the stored imports and
    # their review stay as internal history, so the module keeps its own guarantees.

    def save(self, text='35 лет. F41.1. Авиандр 10 мг.', key=None, user=None, pid='D01'):
        return extraction.save_import(self.db, user or DOCTOR, pid, text, key or secrets.token_hex(16))

    def test_import_retries_review_correction_add_reject_persistence_and_no_actions(self):
        text='35 лет. F41.1. <script>bad</script>'
        key=secrets.token_hex(16)
        initial_outbox=self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0]
        before=decisions.snapshot(self.db,'D01',self.db.execute('SELECT id FROM care_relationships').fetchone()[0])
        first=self.save(text,key)
        self.assertEqual(first,self.save(text,key))
        with self.assertRaises(extraction.ExtractionError) as error:
            self.save(text+'x',key)
        self.assertEqual(409,error.exception.status)
        item=extraction.history(self.db,'D01')[0]
        c=item['result']['candidates'][0]
        form={'request_key':secrets.token_hex(16),'candidate_id':c['id'],'field':c['field'],'assertion':c['assertion'],
              'value':extraction.canonical(c['value']),'quote':c['quote'],'reason':'Сверено с вымышленным источником','disposition':'accept'}
        extraction.review(self.db,DOCTOR,'D01',item['id'],form)
        extraction.review(self.db,DOCTOR,'D01',item['id'],form)
        for changed,status in (({'reason':'другое'},409),({'request_key':secrets.token_hex(16),'value':'70'},400),
                               ({'request_key':secrets.token_hex(16),'quote':'выдуманное основание'},400)):
            with self.assertRaises(extraction.ExtractionError) as error:
                extraction.review(self.db,DOCTOR,'D01',item['id'],{**form,**changed})
            self.assertEqual(status,error.exception.status)
        for kind in ('correct','reject','add'):
            extraction.review(self.db,DOCTOR,'D01',item['id'],{**form,'request_key':secrets.token_hex(16),'disposition':kind,
                              'candidate_id':'' if kind=='add' else c['id'],'value':'требует уточнения'})
        self.assertEqual(4,self.db.execute('SELECT count(*) FROM extraction_reviews').fetchone()[0])
        self.assertNotEqual(before,decisions.snapshot(self.db,'D01',item['relationship_id']))
        for table in ('proposals','care_actions','clinical_entries','clinical_contexts','critical_events'):
            self.assertEqual(0,self.db.execute('SELECT count(*) FROM '+table).fetchone()[0],table)
        self.assertEqual(initial_outbox,self.db.execute('SELECT count(*) FROM outbox_events').fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE text_imports SET source_text='changed'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM extraction_reviews')
        audit_rows = self.db.execute("SELECT * FROM audit_entries WHERE event LIKE 'extraction.%'").fetchall()
        self.assertTrue(audit_rows)
        for row in audit_rows:
            # Random hexadecimal identifiers can legitimately contain "bad".
            # Check the fields that could carry content, and constrain IDs.
            self.assertEqual({}, json.loads(row['metadata_json']))
            self.assertRegex(row['entity_id'], r'^[0-9a-f]{32}$')
            self.assertNotIn(text, str(tuple(row)))

    def test_unsupported_input_limits_and_atomic_rollback(self):
        for value in ('','a\x00b','x'*24001,'9'*5000+' раза в день'):
            with self.assertRaises(extraction.ExtractionError):
                self.save(value)
        for filename,raw in [('a.pdf',b'%PDF-'),('a.txt',b'\xff'),('a.txt',b'x'*24001),('a.txt',b'PK\x00\x00')]:
            with self.assertRaises(extraction.ExtractionError):
                extraction.upload_text(FileStorage(io.BytesIO(raw),filename))
        self.assertEqual('45 лет',extraction.upload_text(FileStorage(io.BytesIO('45 лет'.encode()),'a.txt')))
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM text_imports').fetchone()[0])
        with patch.object(access,'audit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.save('50 лет')
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM text_imports').fetchone()[0])

    def test_new_import_and_review_require_rereview_of_pending_decision(self):
        from test_decisions import DecisionTests
        def draft():
            return decisions.draft(self.db,DOCTOR,'D01',DecisionTests.values(None))
        def confirm(pid):
            version=self.db.execute('SELECT version FROM proposals WHERE id=?',(pid,)).fetchone()[0]
            return decisions.confirm(self.db,DOCTOR,'D01',pid,{'version':str(version),'decision':'approved','reviewed':'yes','rationale':'Synthetic'})
        pending=draft()
        self.save()
        with self.assertRaises(decisions.DecisionError) as error:
            confirm(pending)
        self.assertEqual(409,error.exception.status)
        pending=draft()
        item=extraction.history(self.db,'D01')[0]
        c=item['result']['candidates'][0]
        extraction.review(self.db,DOCTOR,'D01',item['id'],{'request_key':secrets.token_hex(16),
            'candidate_id':c['id'],'field':c['field'],'assertion':'unknown','value':'needs check',
            'quote':c['quote'],'reason':'Synthetic','disposition':'correct'})
        with self.assertRaises(decisions.DecisionError) as error:
            confirm(pending)
        self.assertEqual(409,error.exception.status)
        confirm(draft())
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_access_ended_pair_and_no_web_entry(self):
        for user,pid,expected in [({'id':'pat-a','role':'patient'},'D01',403),({'id':'doc-b','role':'doctor'},'D01',404),(DOCTOR,'D02',404)]:
            with self.assertRaises(decisions.DecisionError) as error:
                self.save(user=user,pid=pid)
            self.assertEqual(expected,error.exception.status)
        for uid in ('doc-a','pat-a'):
            client=self.clients[uid]
            self.assertEqual(404,client.get('/patients/D01/imports').status_code)
            self.assertEqual(404,client.post('/patients/D01/imports',data={'csrf':csrf(client),'source_text':'25 лет'}).status_code)
        self.db.execute("UPDATE care_relationships SET ends_at='2026-10-18'")
        with self.assertRaises(decisions.DecisionError) as error:
            self.save()
        self.assertEqual(404,error.exception.status)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM text_imports').fetchone()[0])

del RecordsTests
