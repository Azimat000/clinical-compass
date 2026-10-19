"""S13 search projections, filter intersections and unchanged access boundaries."""
import secrets
import unittest
from apps.compass import access,records,extraction,critical_delivery
from apps.compass.repository import patient_list
from apps.compass.db import now
import test_records
import test_clinical_rules
import test_critical_delivery
from test_access import csrf


class SearchTests(unittest.TestCase):
    setUp=test_records.RecordsTests.setUp
    tearDown=test_records.RecordsTests.tearDown

    def ids(self,**filters):
        return [p['id'] for p in patient_list(self.db,doctor_id='doc-a',**filters)]

    def test_all_search_sources_literals_filters_and_pair_isolation(self):
        records.save(self.db,{'id':'pat-a','role':'patient'},'D01','self_report',
                     {'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                      'complaints_status':'known','complaints_text':'Редкоеполе бессонница','summary':'Отдельноерезюме'})
        extraction.save_import(self.db,{'id':'doc-a','role':'doctor'},'D01','Импортированнаяистория 35 лет.',secrets.token_hex(16))
        for query in ['D01','Демо 01','демо 01','Редкоеполе','Отдельноерезюме','Импортированнаяистория']:
            self.assertEqual(['D01'],self.ids(query=query),query)
            self.assertEqual([],patient_list(self.db,query=query,doctor_id='doc-b'))
        self.assertEqual(['D01'],self.ids(query='Редкоеполе',record_kind='self_report',age_status='known'))
        self.assertEqual([],self.ids(record_kind='visit'))
        for query in ['%', '_', '\\', '" OR *', "' OR 1=1 --", 'несуществующийпоиск']:
            self.assertEqual([],self.ids(query=query),query)
        for key in ['age_status','record_kind','route_category','attention']:
            with self.assertRaises(ValueError): self.ids(**{key:'invalid'})
            self.assertEqual(400,self.clients['doc-a'].get('/?'+key+'=invalid').status_code)
        self.db.execute("UPDATE care_relationships SET ends_at=?",(now(),))
        self.assertEqual([],self.ids(query='Редкоеполе'))
        self.assertEqual([],self.ids(query='Импортированнаяистория'))

    def test_route_history_filter_without_claiming_current_decision(self):
        from apps.compass import decisions
        # Use the existing complete referral fixture, not arbitrary SQL decisions.
        from test_decisions import DecisionTests
        for category in ['mandatory','desirable']:
            values=DecisionTests.values(None,kind='referral')
            values['route_category']=category
            decisions.draft(self.db,{'id':'doc-a','role':'doctor'},'D01',values)
            self.assertEqual(['D01'],self.ids(route_category=category))
        self.assertEqual([],self.ids(attention='pending'))
        self.assertIn('включая проекты',self.clients['doc-a'].get('/').text)

    def test_error_retains_inputs_and_opens_report_panel(self):
        c=self.clients['pat-a']
        page=c.post('/patients/D01/self-reports',data={'csrf':csrf(c),'request_key':secrets.token_hex(16),
            'observed_on':'bad','summary':'Сохранить введённый текст'})
        self.assertEqual(400,page.status_code)
        self.assertIn('Сохранить введённый текст',page.text)
        self.assertIn('data-default-panel="report"',page.text)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM clinical_entries').fetchone()[0])


class CriticalFilterTests(unittest.TestCase):
    setUp=test_clinical_rules.ClinicalRuleTests.setUp
    tearDown=test_clinical_rules.ClinicalRuleTests.tearDown
    context=test_clinical_rules.ClinicalRuleTests.context
    context_form=test_clinical_rules.ClinicalRuleTests.context_form
    form=test_clinical_rules.ClinicalRuleTests.form
    save=test_clinical_rules.ClinicalRuleTests.save
    prepare=test_critical_delivery.CriticalDeliveryTests.prepare

    def test_pending_before_delivery_then_reaction_and_ended_relationship(self):
        self.save()
        def ids():return [p['id'] for p in patient_list(self.db,doctor_id='doc-a',attention='pending')]
        self.assertEqual(['D01'],ids())
        from apps.compass import events
        while events.process_one(self.db):pass
        eid=self.db.execute('SELECT id FROM critical_events').fetchone()[0]
        for op in ['received','seen','acknowledged','reacted']:
            critical_delivery.mark(self.db,self.doc,eid,op,'Synthetic actual physician response')
        self.assertEqual([],ids())
        self.db.execute("UPDATE care_relationships SET ends_at=?",(now(),))
        self.assertEqual([],ids())
