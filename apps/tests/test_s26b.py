"""S26B: журнал «Кому нужно внимание» и постоянная шапка карточки врача. Тексты и серверные правила не менялись."""
import unittest
from apps.compass import critical_delivery, events
from apps.compass.db import now
from apps.compass.repository import patient_list, pending_signal_counts
from apps.compass.web import create_app
import test_clinical_rules
from test_access import login


class DoctorWorkspaceTests(unittest.TestCase):
    setUp = test_clinical_rules.ClinicalRuleTests.setUp
    tearDown = test_clinical_rules.ClinicalRuleTests.tearDown
    context = test_clinical_rules.ClinicalRuleTests.context
    context_form = test_clinical_rules.ClinicalRuleTests.context_form
    form = test_clinical_rules.ClinicalRuleTests.form
    save = test_clinical_rules.ClinicalRuleTests.save

    def clients(self):
        app = create_app(self.tmp.name + '/db.sqlite3')
        result = {u: app.test_client() for u in ('doc-a', 'doc-b', 'pat-a')}
        for uid, client in result.items():
            login(client, uid)
        return result

    def raise_signal(self):
        self.save()
        while events.process_one(self.db):
            pass
        return self.db.execute('SELECT id FROM critical_events').fetchone()[0]

    def test_no_signal_state_is_worded_and_not_a_claim_of_safety(self):
        page = self.clients()['doc-a'].get('/').text
        self.assertIn('<h1>Кому нужно внимание</h1>', page)
        self.assertIn('Сигналов без записанной реакции нет', page)
        self.assertIn('отсутствие сигнала не означает отсутствие риска', page)
        self.assertNotIn('has-signal', page)

    def test_signal_patient_goes_first_and_is_marked_with_words(self):
        self.db.execute("UPDATE patients SET code='Яя Первый' WHERE id='D01'")
        self.db.execute("INSERT INTO care_relationships VALUES('rel2','D02','doc-a',?,NULL)", (now(),))
        before = [p['id'] for p in patient_list(self.db, doctor_id='doc-a', signals_first=True)]
        self.assertEqual(['D02', 'D01'], before)
        self.raise_signal()
        order = [p['id'] for p in patient_list(self.db, doctor_id='doc-a', signals_first=True)]
        self.assertEqual(['D01', 'D02'], order)
        self.assertEqual({'D01': 1}, pending_signal_counts(self.db, 'doc-a'))
        page = self.clients()['doc-a'].get('/').text
        self.assertIn('Сигналы без записанной реакции — пациентов: 1', page)
        self.assertIn('Критический сигнал без записанной реакции: 1', page)
        self.assertLess(page.index('Яя Первый'), page.index('Демо 02'))
        self.assertEqual(1, page.count('class="patient-row has-signal"'))

    def test_other_doctor_does_not_see_signal_and_reaction_clears_it_only_after_server_records_it(self):
        eid = self.raise_signal()
        clients = self.clients()
        self.assertEqual({}, pending_signal_counts(self.db, 'doc-b'))
        self.assertIn('Сигналов без записанной реакции нет', clients['doc-b'].get('/').text)
        for action in ('received', 'seen', 'acknowledged'):
            critical_delivery.mark(self.db, self.doc, eid, action, '')
        self.assertIn('Сигналы без записанной реакции', clients['doc-a'].get('/').text)
        self.assertEqual({'D01': 1}, pending_signal_counts(self.db, 'doc-a'))
        critical_delivery.mark(self.db, self.doc, eid, 'reacted', 'Synthetic actual physician response')
        self.assertEqual({}, pending_signal_counts(self.db, 'doc-a'))
        self.assertIn('Сигналов без записанной реакции нет', clients['doc-a'].get('/').text)

    def test_card_header_is_on_every_doctor_page_and_shows_signal_and_age(self):
        self.raise_signal()
        doctor = self.clients()['doc-a']
        for url in ['/demo/D01', '/patients/D01/decisions', '/patients/D01/communication', '/patients/D01/imports',
                    '/patients/D01/first-visits', '/patients/D01/follow-up']:
            page = doctor.get(url).text
            self.assertIn('class="case-head"', page, url)
            self.assertIn('Постоянная шапка карточки', page, url)
            self.assertIn('⚠ Без записанной реакции: 1', page, url)
            self.assertIn('Исходный возраст', page, url)
            self.assertIn('Записанное направление', page, url)
            self.assertIn('aria-label="Задача врача"', page, url)
            self.assertIn('aria-label="Разделы карточки"', page, url)
        card = doctor.get('/demo/D01').text
        self.assertEqual(1, card.count('<h1>'))
        self.assertIn('<h1>Демо 01</h1>', card)

    def test_card_navigation_is_short_and_keeps_every_doctor_function_reachable(self):
        doctor = self.clients()['doc-a']
        page = doctor.get('/demo/D01').text
        nav = page[page.index('aria-label="Разделы карточки"'):]
        nav = nav[:nav.index('</nav>')]
        self.assertEqual(5, nav.count('<a '))
        for link in ['#overview', '#dynamics', '#assessments', '#clinical-data', '/patients/D01/decisions']:
            self.assertIn(link, nav)
        for path in ['/patients/D01/first-visits', '/patients/D01/follow-up', '/patients/D01/imports', '/patients/D01/communication']:
            self.assertIn('href="' + path + '"', page)
        self.assertIn('Первый приём', page)
        self.assertIn('Сводка повторного приёма', page)
        decisions = doctor.get('/patients/D01/decisions').text
        self.assertIn('<a aria-current="page" href="/patients/D01/decisions">План и решения</a>', decisions)
        self.assertIn('href="/patients/D01/communication"', decisions)

    def test_patient_role_keeps_own_card_without_doctor_header(self):
        patient = self.clients()['pat-a']
        for url in ['/demo/D01', '/patients/D01/decisions', '/patients/D01/communication']:
            page = patient.get(url).text
            self.assertNotIn('case-head', page, url)
            self.assertNotIn('Задача врача', page, url)
        self.assertEqual(403, patient.get('/patients/D01/imports').status_code)

    def test_status_key_separates_draft_receipt_and_unknown(self):
        page = self.clients()['doc-a'].get('/').text
        for phrase in ['Проект не меняет план', 'Сохранено, получено и просмотрено не значит', 'Неизвестно, отрицание, противоречие']:
            self.assertIn(phrase, page)


if __name__ == '__main__':
    unittest.main()
