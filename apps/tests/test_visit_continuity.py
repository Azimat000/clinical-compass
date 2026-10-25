"""S51: optional encounter notes, attributed history and a separate physician trend."""
import json
import secrets
import unittest
from apps.compass import ages, first_visits, records
import test_first_visits as base


class VisitContinuityTests(unittest.TestCase):
    def setUp(self):
        self.case = base.FirstVisitTests('test_no_diagnosis_draft_retry_restart_revision_complete_without_action')
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.db, self.doctor = self.case.db, self.case.doctor
        self.client = self.case.clients['doc-a']

    def values(self, **overrides):
        values = self.case.values(note_schema=first_visits.NOTE_SCHEMA)
        for code in (*first_visits.CURRENT_FIELDS, *first_visits.STATIC_FIELDS):
            values[code + '_status'] = 'auto'
        return {**values, **overrides}

    def save(self, values, visit='new'):
        response = self.case.post(values, visit)
        self.assertEqual(303, response.status_code, response.text[:500])
        return self.case.rows()[0]

    def initial(self):
        return first_visits.initial_values(self.db, self.doctor, 'FV01')

    def test_sparse_and_empty_notes_complete_without_inventing_negative_findings(self):
        first = self.save(self.values(state='completed', complaints_text='Трудно засыпать'))
        self.assertEqual('known', first['payload']['fields']['complaints']['status'])
        self.assertEqual('Беседа на приёме', first['payload']['fields']['complaints']['basis'])
        self.assertEqual('unknown', first['payload']['fields']['safety']['status'])
        self.assertEqual('unknown', first['payload']['wellbeing'])
        self.assertNotIn('medications', first['payload']['fields'])
        second = self.save(self.values(state='completed'))
        self.assertTrue(second['payload']['not_collected'])
        self.assertTrue(all(f['status'] == 'unknown' for f in second['payload']['fields'].values()))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_completed_history_carries_all_static_sections_but_never_current_findings(self):
        values = self.values(state='completed', observed_on='2026-10-18', wellbeing='worse',
                             age_status='known', age_years='35', age_basis='Беседа')
        for code in (*first_visits.STATIC_FIELDS, *first_visits.CURRENT_FIELDS):
            values[code + '_text'] = 'Синтетическое: ' + code
        original = self.save(values)
        # Unfinished changes cannot overwrite the completed history used for a new encounter.
        self.save(self.values(history_text='Несохранённое в завершённом приёме', wellbeing='better'))
        carried = self.initial()
        self.assertEqual('repeat', carried['visit_kind'])
        self.assertEqual('unknown', carried['wellbeing'])
        for code in first_visits.CURRENT_FIELDS:
            self.assertNotIn(code + '_text', carried)
        for code in first_visits.STATIC_FIELDS:
            self.assertEqual('Синтетическое: ' + code, carried[code + '_text'])
            self.assertEqual(original['id'], carried[code + '_from'])
            self.assertEqual('2026-10-18', carried[code + '_on'])
        self.assertEqual('2026-10-18', carried['age_observed_on'])
        saved = self.save({**self.values(), **carried, 'state': 'completed', 'request_key': secrets.token_hex(16)})
        for code in first_visits.STATIC_FIELDS:
            self.assertEqual(original['id'], saved['payload']['fields'][code]['carried_from']['version_id'])
        source = next(s for s in ages.view(self.db, self.db.execute("SELECT * FROM patients WHERE id='FV01'").fetchone())['sources'] if s['id'] == saved['id'])
        self.assertEqual('2026-10-18', source['observed_on'])
        self.assertEqual(original['payload'], next(i for i in self.case.rows() if i['id'] == original['id'])['payload'])

    def test_changed_static_and_explicit_clear_survive_following_encounters(self):
        original = self.save(self.values(state='completed', observed_on='2026-10-18', history_text='Исходный анамнез',
                                         allergies_status='denied'))
        form = {**self.values(), **self.initial(), 'request_key': secrets.token_hex(16), 'state': 'completed',
                'history_text': 'Уточнённый анамнез', 'allergies_status': 'unknown', 'allergies_text': ''}
        updated = self.save(form)
        field = updated['payload']['fields']['history']
        self.assertNotIn('carried_from', field)
        self.assertEqual(records.today().isoformat(), field['observed_on'])
        self.assertEqual('doctor', field['source'])
        self.assertEqual('Уточнено врачом на текущем приёме', field['basis'])
        carried = self.initial()
        self.assertEqual('Уточнённый анамнез', carried['history_text'])
        self.assertEqual('unknown', carried['allergies_status'])
        self.assertNotIn('allergies_from', carried)
        self.assertEqual('denied', original['payload']['fields']['allergies']['status'])

    def test_retries_versions_documents_and_old_medication_facts_are_preserved(self):
        old = self.save(self.case.values(medications_status='known', medications_text='Прежние факты о препаратах',
                                        medications_basis='Старая беседа', action_draft='Старая заметка'))
        form = {**first_visits.form_values(old), **self.values(), 'base_revision': '1', 'wellbeing': 'same'}
        form.pop('medications_text', None)
        # Browser omits the complete retired field.
        form = {k:v for k,v in form.items() if not k.startswith('medications_')}
        updated = self.save(form, old['visit_id'])
        self.assertEqual(old['payload']['fields']['medications'], updated['payload']['fields']['medications'])
        self.assertEqual('Старая заметка', updated['payload']['action_draft'])
        first_visits.save_documents(self.db, self.doctor, 'FV01', old['visit_id'], {'request_key':secrets.token_hex(16),
            'base_revision':'2', 'documented_facts':'Новый документ', 'document_basis':'Документ А'})
        self.assertEqual(303, self.case.post(form, old['visit_id']).status_code)
        self.assertEqual('same', self.case.rows()[0]['payload']['wellbeing'])
        self.assertEqual(409, self.case.post({**form,'request_key':secrets.token_hex(16)}, old['visit_id']).status_code)
        self.assertEqual(3, len(self.case.rows()))

    def test_trend_in_each_summary_and_version_is_separate_from_patient_diary(self):
        ids=[]
        for trend in ('worse','same','better'):
            item=self.save(self.values(wellbeing=trend,state='completed',mental_status_text='<script>text</script>'))
            ids.append(item['id'])
        html=self.client.get('/demo/FV01').text
        for value in ('Хуже','Без изменений','Лучше','Динамика по оценке врача','отдельно от самоотчёта пациента'):
            self.assertIn(value,html)
        for id in ids:
            self.assertIn('id="visit-source-'+id+'"',html)
        self.assertIn('&lt;script&gt;text&lt;/script&gt;',html)
        self.assertNotIn('<script>text</script>',html)
        self.assertEqual(0,self.db.execute("SELECT count(*) FROM clinical_entries WHERE patient_id='FV01'").fetchone()[0])
        self.assertEqual(403,self.case.clients['pat-fv'].get('/patients/FV01/first-visits').status_code)
        self.assertEqual(404,self.case.clients['doc-b'].get('/patients/FV01/first-visits').status_code)

    def test_invalid_trend_sources_future_dates_and_foreign_provenance_keep_input(self):
        for updates in ({'wellbeing':'magic'}, {'safety_status':'denied','safety_text':'Есть сведения'},
                        {'mental_status_source':'document','mental_status_text':'Текст'},
                        {'history_from':'0'*32}, {'age_observed_on':'2099-01-01'},
                        {'observed_on':'2026-10-18','history_on':'2026-10-19'}):
            with self.subTest(updates=updates):
                result=self.case.post(self.values(complaints_text='Сохранить введённое',**updates))
                self.assertIn(result.status_code,(400,409))
                self.assertIn('Сохранить введённое',result.text)
        self.assertEqual([],self.case.rows())

    def test_unknown_static_does_not_mean_denial_and_long_text_is_not_lost(self):
        value='Ж'*2000
        self.save(self.values(state='completed', history_text=value, family_history_status='conflicting',
                              family_history_text='Разные сведения'))
        form=self.client.get('/patients/FV01/first-visits').text
        self.assertIn(value,form)
        self.assertIn('Разные сведения',form)
        self.assertNotIn('name="medications_text"',form)
        self.assertNotIn('name="action_draft"',form)
        self.assertIn('name="mental_status_text"',form)
        self.assertIn('name="wellbeing"',form)
        self.assertIn('Пустые разделы останутся без данных',form)

    def test_legacy_empty_completed_note_does_not_erase_earlier_known_history(self):
        self.save(self.case.values(state='completed',history_status='known',history_text='Прежняя история',history_basis='Беседа'))
        self.save(self.case.values(state='completed'))
        self.assertEqual('Прежняя история',self.initial()['history_text'])
