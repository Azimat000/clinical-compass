"""S46: every revision and source survives in the single physician history."""
from datetime import timedelta
from html import escape
import re
import secrets
import unittest
from apps.compass import first_visits, records, follow_up
import test_first_visits


class VisitHistorySingleHomeTests(unittest.TestCase):
    setUp = test_first_visits.FirstVisitTests.setUp
    tearDown = test_first_visits.FirstVisitTests.tearDown
    values = test_first_visits.FirstVisitTests.values
    post = test_first_visits.FirstVisitTests.post
    rows = test_first_visits.FirstVisitTests.rows

    def detailed(self):
        day = records.today().isoformat()
        old_day = (records.today()-timedelta(days=2)).isoformat()
        values = self.values(observed_on=old_day, age_status='conflicting', age_detail='OLD-AGE-DETAIL',
                             age_basis='OLD-AGE-BASIS', documented_facts='OLD-DOCUMENT', document_basis='OLD-DOC-SOURCE',
                             action_draft='OLD-ACTION')
        for n, code in enumerate(first_visits.FIELDS):
            values.update({code+'_status':['known','denied','conflicting'][n%3], code+'_text':'' if n%3==1 else 'OLD-'+code,
                           code+'_basis':'OLD-SOURCE-'+code, code+'_source':'document', code+'_on':old_day})
        response = self.post(values)
        self.assertEqual(303, response.status_code)
        visit = self.rows()[0]['visit_id']
        newer = {**values, 'request_key':secrets.token_hex(16), 'base_revision':'1', 'observed_on':day,
                 'state':'completed', 'documented_facts':'NEW-DOCUMENT', 'document_basis':'NEW-DOC-SOURCE',
                 'action_draft':'NEW-ACTION', 'age_detail':'NEW-AGE-DETAIL', 'age_basis':'NEW-AGE-BASIS'}
        for code in first_visits.FIELDS:
            newer[code+'_text']='' if values[code+'_status']=='denied' else 'NEW-'+code
            newer[code+'_basis']='NEW-SOURCE-'+code
            newer[code+'_on']=day
        result = self.post(newer, visit)
        self.assertEqual(303, result.status_code)
        return visit, values, newer, result

    def test_complete_payloads_authors_dates_states_and_all_revisions_live_in_card(self):
        visit, _, _, result = self.detailed()
        rows = [tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions ORDER BY rowid')]
        self.assertEqual('/demo/FV01#visit-'+visit, result.location)
        for path in ('/demo/FV01','/patients/FV01/follow-up'):
            response = self.clients['doc-a'].get(path)
            self.assertEqual(200,response.status_code)
            page=response.text
            self.assertIn('Предыдущие версии (1)',page)
            for item in self.rows():
                self.assertEqual(1,page.count('id="visit-version-'+visit+'-'+str(item['revision'])+'"'))
                self.assertIn(item['recorded_at'],page)
                for key in ('action_draft','age_basis'):
                    self.assertIn(escape(item['payload'][key]),page)
                # UI11: document notes stay stored with every revision but are not shown or linked.
                for key in ('documented_facts','document_basis'):
                    self.assertTrue(item['payload'][key])
                    self.assertNotIn(escape(item['payload'][key]),page)
                self.assertNotIn('#visit-document-'+item['id'],page)
                self.assertIn(item['payload']['age']['detail'],page)
                for field in item['payload']['fields'].values():
                    self.assertIn(escape(field['text']),page)
                    self.assertIn(escape(field['basis']),page)
                    self.assertIn(field['observed_on'],page)
            self.assertIn('Явно отрицает',page)
            self.assertIn('Противоречивые сведения',page)
            ids=re.findall(r'\bid="([^"]+)"',page)
            self.assertEqual(len(ids),len(set(ids)))
        old=self.clients['doc-a'].get('/patients/FV01/first-visits/'+visit)
        self.assertEqual(302,old.status_code)
        self.assertEqual(result.location,old.location)
        self.assertEqual(rows,[tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions ORDER BY rowid')])

    def test_editor_keeps_only_current_form_and_completion_is_immutable(self):
        visit, original, completed, _ = self.detailed()
        editor=self.clients['doc-a'].get('/patients/FV01/first-visits').text
        for marker in ('OLD-DOCUMENT','NEW-DOCUMENT','Предыдущие версии','Сохранённые приёмы','Архивные записи приёма'):
            self.assertNotIn(marker,editor)
        self.assertIn('name="state" value="draft"',editor)
        self.assertIn('/demo/FV01#visit-history',editor)
        before=[tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')]
        rejected=self.post({**completed,'request_key':secrets.token_hex(16),'base_revision':'2'},visit)
        self.assertEqual(409,rejected.status_code)
        self.assertIn('Новая версия не сохранена',rejected.text)
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM first_visit_versions')])
        draft=self.post(self.values(observed_on=records.today().isoformat(), documented_facts='CURRENT-DRAFT',document_basis='SOURCE'))
        draft_page=self.clients['doc-a'].get(draft.location).text
        self.assertNotIn('CURRENT-DRAFT',draft_page)
        self.assertEqual('CURRENT-DRAFT',self.rows()[0]['payload']['documented_facts'])
        self.assertNotIn('OLD-DOCUMENT',draft_page)
        self.assertNotIn('NEW-DOCUMENT',draft_page)

    def test_period_selects_visit_once_but_keeps_its_complete_revision_chain(self):
        visit, _, _, _ = self.detailed()
        today=records.today().isoformat()
        page=self.clients['doc-a'].get('/demo/FV01',query_string={'start':today,'end':today}).text
        self.assertEqual(1,page.count('id="visit-'+visit+'"'))
        stored=[r['payload']['documented_facts'] for r in self.rows()]
        self.assertIn('OLD-DOCUMENT',stored)
        self.assertIn('NEW-DOCUMENT',stored)
        self.assertNotIn('OLD-DOCUMENT',page)
        self.assertNotIn('NEW-DOCUMENT',page)
        data=follow_up.view(self.db,self.doctor,'FV01',{'start':today,'end':today},include_plan=False)
        self.assertEqual(1,len(data['visits']))
        self.assertEqual(2,len(data['visit_versions'][visit]))
        for uid,code in [('pat-fv',403),('pat-b',403),('doc-b',404)]:
            self.assertEqual(code,self.clients[uid].get('/patients/FV01/first-visits/'+visit).status_code)
        self.assertNotIn('OLD-DOCUMENT',self.clients['pat-fv'].get('/demo/FV01/visits').text)
