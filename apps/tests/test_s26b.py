"""UI04: список «Кому нужно внимание» и карточка врача. Серверные правила сигналов не менялись, меняется только разметка."""
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
        self.assertIn('Записанных причин для внимания нет', page)
        self.assertIn('не вывод о том, что у пациентов всё хорошо', page)
        self.assertNotIn('СИГНАЛ', page)
        self.assertNotIn('class="flagged"', page)

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
        self.assertIn('Критический сигнал без реакции врача', page)
        self.assertIn('критический сигнал без записанной реакции врача', page)  # полная причина флага для скринридера
        self.assertLess(page.index('Яя Первый'), page.index('Демо 02'))
        self.assertEqual(1, page.count('class="flagged"'))
        self.assertIn('С причиной для внимания: 1 из 2', page)

    def test_other_doctor_does_not_see_signal_and_reaction_clears_it_only_after_server_records_it(self):
        eid = self.raise_signal()
        clients = self.clients()
        self.assertEqual({}, pending_signal_counts(self.db, 'doc-b'))
        self.assertNotIn('СИГНАЛ', clients['doc-b'].get('/').text)
        for action in ('received', 'seen', 'acknowledged'):
            critical_delivery.mark(self.db, self.doc, eid, action, '')
        self.assertIn('СИГНАЛ', clients['doc-a'].get('/').text)
        self.assertEqual({'D01': 1}, pending_signal_counts(self.db, 'doc-a'))
        critical_delivery.mark(self.db, self.doc, eid, 'reacted', 'Synthetic actual physician response')
        self.assertEqual({}, pending_signal_counts(self.db, 'doc-a'))
        self.assertNotIn('СИГНАЛ', clients['doc-a'].get('/').text)

    def test_card_header_shows_signal_and_age_and_has_one_heading(self):
        self.raise_signal()
        doctor = self.clients()['doc-a']
        card = doctor.get('/demo/D01').text
        self.assertEqual(1, card.count('<h1'))
        self.assertIn('<h1 translate="no">Демо 01</h1>', card)
        self.assertIn('19 лет', card)
        self.assertIn('Критических сигналов без реакции врача: 1', card)
        self.assertIn('Сводка к приёму', card)
        fu = doctor.get('/patients/D01/follow-up').text
        self.assertIn('<h1>Сводка к приёму</h1>', fu)
        self.assertIn('Карточка пациента', fu)

    def test_card_navigation_is_short_and_offers_only_screens_that_exist(self):
        doctor = self.clients()['doc-a']
        page = doctor.get('/demo/D01').text
        nav = page[page.index('aria-label="Разделы карточки"'):]
        nav = nav[:nav.index('</nav>')]
        self.assertEqual(5, nav.count('<a '))
        for link in ['#records', '#assessments', '#age-review', '#clinical-rules', '#link']:
            self.assertIn(link, nav)
            self.assertIn('id="%s"' % link[1:], page)
        # Решения, приём и документы готовы (UI05) и есть в строке разделов пациента; сообщения появятся в UI06, ссылки на 503 нет.
        for path in ['decisions', 'first-visits', 'imports']:
            self.assertIn('href="/patients/D01/' + path + '"', page)
        self.assertNotIn('/patients/D01/communication', page)
        self.assertIn('href="/patients/D01/follow-up"', page)

    def test_patient_role_keeps_own_card_without_doctor_header(self):
        patient = self.clients()['pat-a']
        page = patient.get('/demo/D01').text
        self.assertNotIn('Разделы карточки', page)
        self.assertNotIn('Сводка к приёму', page)
        self.assertEqual(403, patient.get('/patients/D01/imports').status_code)
        self.assertEqual(403, patient.get('/patients/D01/follow-up').status_code)

    def test_legend_separates_known_unknown_and_conflicting_by_word(self):
        page = self.clients()['doc-a'].get('/').text
        for phrase in ['есть сведения', 'неизвестно', 'противоречие', 'не указано', 'лучше', 'без изменений', 'хуже']:
            self.assertIn(phrase, page)


if __name__ == '__main__':
    unittest.main()
