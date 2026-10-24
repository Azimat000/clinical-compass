"""S31: concise review reasons, truthful plan states, direct links and no critical UI."""
import re
import unittest
from unittest.mock import patch

import test_access
import test_decisions
import test_ui04


class ReviewListTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    self_report = test_ui04.DoctorCabinetTests.self_report

    def plan(self, **counts):
        return patch('apps.compass.overview._plan', return_value={'kind': 'tasks', 'counts': counts, 'due': sum(counts.values())})

    def page(self):
        response = self.clients['doc-a'].get('/')
        self.assertEqual(200, response.status_code)
        return response.text

    def test_unknown_completion_is_not_reported_as_a_missed_task(self):
        with self.plan(unknown=2, taken=1):
            page = self.page()
        self.assertIn('Не отмечено выполнение плана', page)
        self.assertIn('Без отметки: 2', page)
        self.assertNotIn('Есть пропуски в плане', page)
        self.assertNotIn('Отмечено пропусков', page)

    def test_missed_and_unknown_completion_are_shown_separately(self):
        with self.plan(missed=1, unknown=2, taken=1):
            page = self.page()
        self.assertIn('Есть пропуски в плане', page)
        self.assertIn('Отмечено пропусков: 1; Без отметки: 2', page)
        self.assertIn('href="/patients/D01/follow-up#fu-plan"', page)

    def test_every_reason_is_visible_and_each_link_has_an_existing_target(self):
        self.db.execute("UPDATE patients SET age_status='unknown',age_years=NULL WHERE id='D01'")
        self.self_report('Тошнота и расхождения', 'worse', adverse_events_status='known', adverse_events_text='Тошнота',
                         complaints_status='conflicting', complaints_text='Разные сведения')
        self.self_report('Хуже повторно', 'worse')
        with self.plan(missed=1, unknown=1, conflicting=1):
            page = self.page()
        for reason in ('Записано нежелательное явление', 'Сверить противоречивые сведения', 'Сверить выполнение плана',
                       'Уточнить возраст', 'Самочувствие хуже 2 раза подряд', 'Есть пропуски в плане'):
            self.assertIn(reason, page)
        listing = re.search(r'<ul class="review-reasons">.*?</ul>', page, re.S).group(0)
        links = re.findall(r'href="([^"]+)"', listing)
        self.assertEqual(6, len(links))
        for link in links:
            path, anchor = link.split('#')
            destination = self.clients['doc-a'].get(path)
            self.assertEqual(200, destination.status_code, link)
            self.assertIn('id="%s"' % anchor, destination.text, link)
        self.assertNotIn('ещё причин:', page)

    def test_filters_are_collapsed_until_used_and_no_retired_signal_filter_exists(self):
        page = self.page()
        self.assertIn('<details class="review-filters">', page)
        self.assertNotIn('name="attention"', page)
        self.assertNotIn('>НЯ<', page)
        self.assertNotIn('>ПРОТИВ.<', page)
        self.assertNotIn('>ВОЗРАСТ<', page)
        filtered = self.clients['doc-a'].get('/?age_status=known').text
        self.assertIn('<details class="review-filters" open>', filtered)
        self.assertIn('Фильтры применены', filtered)

    def test_all_patients_remain_available_and_empty_review_list_does_not_claim_safety(self):
        page = self.page()
        self.assertIn('Демо 01', page)
        only_review = self.clients['doc-a'].get('/?show=flagged').text
        self.assertNotIn('class="who"', only_review)
        self.assertIn('Записей с причинами для проверки нет', only_review)
        self.assertIn('Отсутствие причины не означает', only_review)
        self.assertRegex(only_review, r'href="/">Все пациенты</a>')

    def test_full_name_is_escaped_and_not_truncated(self):
        name = 'Александра Вишневская-Ковальчук <script>пример</script>'
        self.db.execute('UPDATE patients SET code=? WHERE id=?', (name, 'D01'))
        page = self.page()
        self.assertIn('Александра Вишневская-Ковальчук &lt;script&gt;пример&lt;/script&gt;</a>', page)
        self.assertNotIn('<script>пример', page)

    def test_first_use_names_absence_of_patients_and_offers_invitation(self):
        from apps.compass.db import now
        self.db.execute('UPDATE care_relationships SET ends_at=?', (now(),))
        page = self.page()
        self.assertIn('У вас пока нет пациентов', page)
        self.assertIn('href="/invitations/new" data-invite-open>Пригласить пациента</a>', page)
        self.assertNotIn('По этому запросу пациентов нет', page)

    def test_retired_filter_redirect_only_preserves_supported_filters(self):
        response = self.clients['doc-a'].get('/?attention=pending&_external=1&_scheme=https&endpoint=login&q=D01')
        self.assertEqual(302, response.status_code)
        self.assertEqual('/?q=D01', response.headers['Location'])


if __name__ == '__main__':
    unittest.main()
