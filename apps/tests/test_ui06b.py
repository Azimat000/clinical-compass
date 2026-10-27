"""UI06B: the patient's screen of doctor-confirmed decisions (templates/plan.html at /patients/<id>/decisions)."""
import re
import secrets
import unittest

from apps.compass import decisions
import test_access
import test_decisions

URL = '/patients/D01/decisions'
EMPTY = 'Врач пока не подтвердил план. Это не означает, что плана не будет.'


class PlanScreenTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def page(self, path=URL, who='pat-a', status=200):
        response = self.clients[who].get(path)
        self.assertEqual(status, response.status_code, path)
        return response.get_data(as_text=True)

    def approved(self, text, kind='plan_change', **extra):
        proposal = self.draft(kind=kind, content=text, **extra)
        self.assertEqual(303, self.confirm(proposal).status_code)
        return proposal

    # ---- вкладка и пустой план ----

    def test_tab_leads_to_the_screen_and_marks_it_current(self):
        page = self.page(URL)
        nav = re.search(r'<nav class="p-tabs" aria-label="Разделы кабинета">.*?</nav>', page, re.S).group(0)
        self.assertEqual(1, nav.count('aria-current="page"'))
        self.assertRegex(nav, r'<a href="%s" aria-current="page">План</a>' % URL)
        self.assertIn('<h1>План</h1>', page)
        for path in ('/demo/D01', '/demo/D01/diary', '/patients/D01/communication'):
            self.assertIn('<a href="%s">План</a>' % URL, self.page(path), path)

    def test_empty_plan_says_so_in_words_and_without_a_promise(self):
        page = self.page()
        self.assertIn(EMPTY, page)
        self.assertIn('Кабинет не оказывает экстренную помощь', page)
        self.assertNotIn('Последнее подтверждённое', page)
        self.assertNotIn('Ранее подтверждённые', page)
        self.assertNotRegex(page, r'врач (увидит|ответит|свяжется|посмотрит)')

    def test_open_and_rejected_drafts_leave_the_plan_empty(self):
        self.draft(content='ОТКРЫТЫЙ-ПРОЕКТ')
        rejected = self.draft(content='ОТКЛОНЁННЫЙ-ПРОЕКТ')
        self.assertEqual(303, self.confirm(rejected, 'rejected', rationale='ОТКАЗ-ВРАЧА').status_code)
        page = self.page()
        self.assertIn(EMPTY, page)
        for text in ('ОТКРЫТЫЙ-ПРОЕКТ', 'ОТКЛОНЁННЫЙ-ПРОЕКТ', 'ОТКАЗ-ВРАЧА', 'Проект'):
            self.assertNotIn(text, page)

    # ---- порядок и состав ----

    def test_latest_confirmed_decision_is_first_then_the_history(self):
        self.approved('ПЕРВОЕ-РЕШЕНИЕ', kind='therapy_start')
        self.approved('ВТОРОЕ-РЕШЕНИЕ', kind='referral')
        self.draft(content='ЖДЁТ-ВРАЧА')
        self.approved('ТРЕТЬЕ-РЕШЕНИЕ', kind='plan_change')
        page = self.page()
        head, tail = page.split('Ранее подтверждённые решения')
        self.assertIn('Последнее подтверждённое решение', head)
        self.assertIn('ТРЕТЬЕ-РЕШЕНИЕ', head)
        self.assertNotIn('ВТОРОЕ-РЕШЕНИЕ', head)
        self.assertLess(tail.index('ВТОРОЕ-РЕШЕНИЕ'), tail.index('ПЕРВОЕ-РЕШЕНИЕ'))
        self.assertNotIn('ЖДЁТ-ВРАЧА', page)
        for kind in ('Изменение плана', 'Направление', 'Назначение терапии'):
            self.assertIn('<h3 class="plan-kind">%s</h3>' % kind, page)

    def test_every_decision_names_the_kind_the_doctor_and_the_confirmation_time(self):
        proposal = self.approved('ОДНО-РЕШЕНИЕ')
        page = self.page()
        stamp = self.db.execute('SELECT confirmed_at FROM doctor_confirmations WHERE proposal_id=?', (proposal['id'],)).fetchone()[0]
        self.assertIn('Подтверждено врачом', page)
        self.assertIn('<b translate="no">doc-a</b>', page)
        self.assertIn('<time class="num" datetime="%s">' % stamp, page)
        self.assertRegex(page, r'\d\d\.\d\d\.\d{4}\xa0\d\d:\d\d\xa0МСК')
        self.assertNotIn('Ранее подтверждённые', page)

    def test_old_decisions_fold_after_current_actions_without_losing_history(self):
        for number in range(8):
            self.approved('РЕШЕНИЕ-№%d.' % number)
        page = self.page()
        self.assertIn('Ранее подтверждённые решения (7)', page)
        self.assertIn('<details class="fold plan-history" id="plan-history">', page)
        self.assertLess(page.index('id="medications"'), page.index('id="plan-history"'))
        self.assertLess(page.index('id="recommendations"'), page.index('id="plan-history"'))
        self.assertEqual(8, page.count('class="plan-entry'))
        self.assertEqual(8, len(set(re.findall(r'id="plan-([0-9a-f]{32})"', page))))

    def test_missing_doctor_name_is_said_in_words(self):
        self.approved('БЕЗ-ИМЕНИ')
        self.db.execute("UPDATE users SET display_name='' WHERE id='doc-a'")
        self.db.commit()
        self.assertIn('врач (имя не указано)', self.page())

    # ---- что пациент не получает ----

    def test_doctor_only_fields_never_reach_the_patient_page(self):
        secrets_in_draft = {'basis': 'ТАЙНА-ОСНОВАНИЕ', 'uncertainties': 'ТАЙНА-НЕОПРЕДЕЛЁННОСТЬ',
                            'route_evidence': 'ТАЙНА-ДОКАЗАТЕЛЬСТВО', 'route_unavailable': 'ТАЙНА-РЕЗЕРВ',
                            'route_severity': 'ТАЙНА-ТЯЖЕСТЬ', 'route_specialty': 'ТАЙНА-СПЕЦИАЛИСТ',
                            'aviandr_basis': 'ТАЙНА-АВИАНДР'}
        notes = {'note_' + a['id']: 'ТАЙНА-ЗАМЕТКА-' + a['id'] for a in decisions.reference()['review_areas']}
        proposal = self.draft(kind='referral', content='ВИДИМОЕ-НАПРАВЛЕНИЕ', **secrets_in_draft, **notes)
        self.assertEqual(303, self.confirm(proposal, rationale='ТАЙНА-ОБОСНОВАНИЕ-ВРАЧА').status_code)
        therapy = self.draft(kind='therapy_start', content='ВИДИМАЯ-ТЕРАПИЯ', **secrets_in_draft, **notes)
        self.assertEqual(303, self.confirm(therapy, rationale='ТАЙНА-ОБОСНОВАНИЕ-ВРАЧА-2').status_code)
        self.draft(kind='plan_change', content='ТАЙНА-ЧЕРНОВИК')
        rejected = self.draft(kind='therapy_change', content='ТАЙНА-ОТКЛОНЁННЫЙ')
        self.assertEqual(303, self.confirm(rejected, 'rejected', rationale='ТАЙНА-ОТКАЗ').status_code)
        page = self.page()
        self.assertIn('ВИДИМОЕ-НАПРАВЛЕНИЕ', page)
        self.assertIn('ВИДИМАЯ-ТЕРАПИЯ', page)
        self.assertNotIn('ТАЙНА', page)
        for word in ('therapy_review', 'routing_review', 'route', 'rationale', 'basis', 'Авиандр', 'Проект', 'Отклон',
                     'input_snapshot', 'reference', 'proposal'):
            self.assertNotIn(word, page, word)
        # технические номера записей и врачей не выводятся, кроме якорей решений
        self.assertNotIn('doc-a</a>', page)
        self.assertNotIn('actor', page)

    def test_text_is_escaped_and_long_unbroken_text_wraps(self):
        long_word = 'Д' * 3900
        self.approved('<script>alert(1)</script> & ' + long_word)
        page = self.page()
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; &amp; ' + long_word, page)
        self.assertRegex(page, r'<p class="plan-text keep">')

    # ---- границы ----

    def test_the_screen_is_a_plain_patient_page(self):
        self.approved('СТРАНИЦА')
        response = self.clients['pat-a'].get(URL)
        page = response.get_data(as_text=True)
        self.assertEqual('no-store', response.headers['Cache-Control'])
        self.assertNotIn(' style=', page)
        self.assertEqual(['<script src="/static/doctor_forms.js" defer></script>'],
                         re.findall(r'<script\b[^>]*>.*?</script>', page, re.S))
        ids = re.findall(r'\sid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('Кабинет не оказывает экстренную помощь', page)
        self.assertIn('не обеспечивает экстренную помощь', page)  # общая подпись кабинета
        self.assertNotRegex(page, r'врач (увидит|ответит|свяжется|посмотрит)')
        self.assertNotIn('communication#plan-items', page)

    def test_other_roles_and_patients_keep_their_old_answers(self):
        proposal = self.approved('ЧУЖОЕ')
        self.assertEqual(404, self.clients['pat-b'].get(URL).status_code)
        self.assertEqual(404, self.clients['doc-b'].get(URL).status_code)
        self.assertEqual(302, self.app.test_client().get(URL).status_code)  # без входа — на страницу входа
        self.assertEqual(403, self.post('pat-a', URL, self.values()).status_code)
        self.assertEqual(403, self.clients['pat-a'].get(URL + '?revise=' + proposal['id']).status_code)
        self.assertEqual(403, self.post('pat-a', f'{URL}/{proposal["id"]}/confirm',
                                         {'decision': 'approved', 'version': '1', 'rationale': 'x', 'reviewed': 'yes'}).status_code)
        doctor = self.page(URL, who='doc-a')
        self.assertIn('Подтверждено врачом', doctor)
        self.assertNotIn('class="plan-entry', doctor)
        self.assertIn('Новый проект', self.page(URL + '?revise=' + proposal['id'], who='doc-a'))

    def test_json_clients_and_api_are_unchanged(self):
        self.approved('ДЛЯ-API')
        technical = self.clients['pat-a'].get(URL, headers={'Accept': 'application/json'})
        self.assertEqual(503, technical.status_code)
        self.assertEqual('interface_removed', technical.json['status'])
        self.assertEqual({'status', 'message', 'csrf'}, set(technical.json))
        self.assertNotIn('ДЛЯ-API', technical.text)
        data = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions']
        self.assertEqual(1, len(data))
        self.assertEqual('approved', data[0]['decision'])
        self.assertTrue({'reference', 'input_snapshot', 'therapy_review', 'routing_review'}.isdisjoint(data[0]))
        self.assertNotIn('therapy_review', data[0]['payload'])


if __name__ == '__main__':
    unittest.main()
