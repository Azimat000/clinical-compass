"""S52: a plain-text editor must preserve the attribution and semantics of old notes."""
import secrets
import unittest
from apps.compass import first_visits, records
import test_first_visits as base


class VisitTextEditorTests(unittest.TestCase):
    def setUp(self):
        self.case=base.FirstVisitTests('test_no_diagnosis_draft_retry_restart_revision_complete_without_action')
        self.case.setUp();self.addCleanup(self.case.tearDown)
        self.db,self.doctor=self.case.db,self.case.doctor
        self.client=self.case.clients['doc-a']

    def form(self, item=None, **updates):
        values=first_visits.form_values(item) if item else first_visits.initial_values(self.db,self.doctor,'FV01')
        values=first_visits.editor_values(values)
        values.setdefault('age_observed_on',values['observed_on'])
        for code in (*first_visits.CURRENT_FIELDS,*first_visits.STATIC_FIELDS):
            for suffix in ('status','source','on','basis'):
                values.pop(code+'_'+suffix,None)
        values.pop('age_basis',None)
        return {**values,'editor_mode':first_visits.TEXT_EDITOR,'request_key':secrets.token_hex(16),'state':'draft',**updates}

    def save(self,values,visit='new'):
        response=self.case.post(values,visit)
        self.assertEqual(303,response.status_code,response.text[:300])
        return self.case.rows()[0]

    def assert_simple(self,html):
        self.assertNotIn('Состояние сведений и источник',html)
        self.assertNotIn('Основание возраста',html)
        self.assertNotIn('name="age_basis"',html)
        for code in (*first_visits.CURRENT_FIELDS,*first_visits.STATIC_FIELDS):
            self.assertIn('name="'+code+'_text"',html)
            for suffix in ('status','source','on','basis'):
                self.assertNotIn('name="'+code+'_'+suffix+'"',html)

    def test_new_draft_error_and_completion_without_age_basis(self):
        self.assert_simple(self.client.get('/patients/FV01/first-visits').text)
        old=self.save(self.form(complaints_text='Текст без дополнительных полей',age_status='known',age_years='35'))
        p=old['payload'];self.assertEqual('known',p['fields']['complaints']['status'])
        self.assertEqual('physician_note',p['fields']['complaints']['source'])
        self.assertEqual('Возраст записан врачом на приёме',p['age_basis'])
        self.assert_simple(self.client.get('/patients/FV01/first-visits/'+old['visit_id']).text)
        bad=self.case.post(self.form(old,observed_on='2099-01-01',complaints_text='Не потерять текст'),old['visit_id'])
        self.assertEqual(400,bad.status_code);self.assert_simple(bad.text);self.assertIn('Не потерять текст',bad.text)
        legacy_error=self.case.post(self.case.values(observed_on='2099-01-01',safety_status='denied',safety_basis='Прямое отрицание'))
        self.assertEqual(400,legacy_error.status_code)
        self.assertIn('Явно отрицает.',legacy_error.text)
        result=self.save(self.form(old,state='completed',wellbeing='better'),old['visit_id'])
        self.assertEqual('completed',result['state'])
        self.assertEqual('better',result['payload']['wellbeing'])

    def test_unchanged_denial_conflict_document_and_age_keep_exact_metadata(self):
        self.case.post(self.case.values(state='completed',observed_on='2026-10-18',
            history_status='denied',history_source='document',history_basis='Отрицание в прежнем документе',
            family_history_status='conflicting',family_history_text='Расхождение сведений',family_history_basis='Два документа',
            age_status='known',age_years='35',age_source='document',age_basis='Документ о возрасте'))
        old=self.case.rows()[0]
        form=self.form();self.assertEqual('Явно отрицает.',form['history_text'])
        row=self.save(form)
        for code in ('history','family_history'):
            for key in ('text','status','source','basis','observed_on'):
                self.assertEqual(old['payload']['fields'][code][key],row['payload']['fields'][code][key])
            self.assertEqual(old['id'],row['payload']['fields'][code]['carried_from']['version_id'])
        self.assertEqual(old['payload']['age_basis'],row['payload']['age_basis'])
        self.assertEqual('2026-10-18',row['payload']['age_observed_on'])
        self.assertEqual(old['id'],row['payload']['age_carried_from']['version_id'])
        # Re-saving the same draft must not convert denial/conflict or reset the dates.
        updated=self.save(self.form(row),row['visit_id'])
        self.assertEqual(row['payload']['fields'],updated['payload']['fields'])
        self.assertEqual(row['payload']['age_basis'],updated['payload']['age_basis'])
        self.assertEqual(old['payload'],next(i['payload'] for i in self.case.rows() if i['id']==old['id']))

    def test_current_draft_sources_survive_and_changed_text_gets_new_attribution(self):
        self.case.post(self.case.values(complaints_status='known',complaints_text='Прежняя жалоба',
            complaints_source='document',complaints_basis='Выписка А',complaints_on='2026-10-18',
            safety_status='denied',safety_basis='Прямое отрицание',
            age_status='known',age_years='35',age_basis='Старое основание'))
        old=self.case.rows()[0]
        same=self.save(self.form(old),old['visit_id'])
        for code,field in old['payload']['fields'].items():
            self.assertEqual(field,same['payload']['fields'][code])
        self.assertEqual('Старое основание',same['payload']['age_basis'])
        changed=self.save(self.form(same,complaints_text='Новое уточнение',age_years='36'),old['visit_id'])
        field=changed['payload']['fields']['complaints']
        self.assertEqual('physician_note',field['source']);self.assertEqual(records.today().isoformat(),field['observed_on'])
        self.assertEqual('Уточнено врачом на текущем приёме',field['basis'])
        self.assertEqual('Возраст записан врачом на приёме',changed['payload']['age_basis'])
        self.assertEqual('denied',changed['payload']['fields']['safety']['status'])

    def test_clearing_and_editing_conflicting_history_does_not_silently_resolve_conflict(self):
        self.case.post(self.case.values(state='completed',history_status='conflicting',history_text='Расхождение',history_basis='Два источника'))
        row=self.save(self.form(history_text='Расхождение уточняется'))
        self.assertEqual('conflicting',row['payload']['fields']['history']['status'])
        cleared=self.save(self.form(row,history_text=''),row['visit_id'])
        self.assertEqual('unknown',cleared['payload']['fields']['history']['status'])
        self.assertNotIn('carried_from',cleared['payload']['fields']['history'])
        self.assertEqual('Расхождение',self.case.rows()[-1]['payload']['fields']['history']['text'])

    def test_retries_after_document_update_and_completion_are_stable(self):
        row=self.save(self.form(history_text='Анамнез'))
        form=self.form(row,complaints_text='Добавлена жалоба')
        saved=self.save(form,row['visit_id'])
        first_visits.save_documents(self.db,self.doctor,'FV01',row['visit_id'],{'base_revision':'2',
            'request_key':secrets.token_hex(16),'documented_facts':'Сведения','document_basis':'Выписка'})
        self.assertEqual(303,self.case.post(form,row['visit_id']).status_code)
        self.assertEqual(3,len(self.case.rows()))
        self.assertEqual(saved['payload']['fields'],self.case.rows()[0]['payload']['fields'])
        final=self.form(self.case.rows()[0],state='completed')
        self.save(final,row['visit_id']);self.assertEqual(303,self.case.post(final,row['visit_id']).status_code)
        self.assertEqual(409,self.case.post({**final,'request_key':secrets.token_hex(16)},row['visit_id']).status_code)

    def test_empty_form_is_valid_but_roles_csrf_and_foreign_provenance_still_block(self):
        self.save(self.form(state='completed'))
        self.assertEqual('unknown',self.case.rows()[0]['payload']['fields']['safety']['status'])
        self.assertEqual(403,self.case.post(self.form(),uid='pat-fv').status_code)
        self.assertEqual(404,self.case.post(self.form(),uid='doc-b').status_code)
        self.assertEqual(403,self.client.post('/patients/FV01/first-visits/new',data=self.form()).status_code)
        self.assertEqual(409,self.case.post(self.form(history_from='0'*32)).status_code)

    def test_same_day_history_edit_remains_a_physician_note(self):
        self.case.post(self.case.values(state='completed',history_status='known',history_text='Прежнее уточнение',
            history_source='physician_note',history_basis='Уточнено врачом на текущем приёме'))
        old=self.case.rows()[0]
        updated=self.save(self.form(history_text='Новое уточнение в тот же день'))
        self.assertEqual('physician_note',updated['payload']['fields']['history']['source'])
        self.assertNotIn('carried_from',updated['payload']['fields']['history'])
        self.assertEqual('Прежнее уточнение',old['payload']['fields']['history']['text'])
