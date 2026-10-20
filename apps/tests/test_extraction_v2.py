"""General literal scope regressions, no clinical labels or medical gold."""
import time
import unittest
from apps.compass import extraction


class LiteralV2Tests(unittest.TestCase):
    def values(self,text,field):
        result=extraction.extract(text)
        for c in result['candidates']:
            self.assertEqual(c['quote'],text[c['span']['start']:c['span']['end']])
            self.assertIn(c['field'],extraction.FIELDS)
            self.assertIn(c['assertion'],extraction.ASSERTIONS)
        return [(c['assertion'],c['value']) for c in result['candidates'] if c['field']==field]

    def test_units_do_not_match_years_or_word_prefixes(self):
        self.assertEqual([],self.values('31 год; 35 года. 12 грамматика.','dose'))
        self.assertEqual([('present',{'value':12,'unit':'mg'})],self.values('12 мг.','dose'))
        self.assertEqual([('present',{'value':0.5,'unit':'tablet'})],self.values('1/2 таблетки.','dose'))
        for text in ('-8 мг.','−8 мг.','1/0 таблетки.'):
            self.assertEqual([('invalid',None)],self.values(text,'dose'))

    def test_negation_scope_is_not_shared_across_objects_or_sentences(self):
        t='Беременность отрицает, кормление грудью: да. Лекарственная аллергия: да, название аллергена неизвестно.'
        self.assertEqual([('negated',False)],self.values(t,'pregnancy_status'))
        self.assertEqual([('present',True)],self.values(t,'lactation_status'))
        for sep in ('\u2028','\u2029'):
            self.assertEqual([('present',True)],self.values('Сыпь отрицает'+sep+'Беременность: да.','pregnancy_status'))
        self.assertEqual([('present',True)],self.values(t,'medication_allergy'))
        self.assertEqual([('listed','Авиандр')],self.values('Тошноту отрицает. Авиандр в списке.','medication'))

    def test_third_party_age_dose_and_medication_are_not_patient_values(self):
        text='У матери 68 лет. Сосед принимает Авиандр 7 мг. Пациенту 36 лет.'
        self.assertEqual([('third_party',68),('present',36)],self.values(text,'age_years'))
        self.assertEqual([('third_party','Авиандр')],self.values(text,'medication'))
        self.assertEqual([('third_party',{'value':7,'unit':'mg'})],self.values(text,'dose'))

    def test_different_drugs_or_historical_doses_are_not_current_conflicts(self):
        t='Препарат X 4 мг. Препарат Y 9 мг.'
        self.assertEqual([('present',{'value':4,'unit':'mg'}),('present',{'value':9,'unit':'mg'})],self.values(t,'dose'))
        self.assertEqual([('historical',{'value':4,'unit':'mg'}),('present',{'value':9,'unit':'mg'})],self.values('Ранее Авиандр 4 мг. Сейчас Авиандр 9 мг.','dose'))

    def test_question_unknown_and_own_historical_speech_are_not_current_alarms(self):
        self.assertEqual([('unknown',None)],self.values('Есть мысли причинить себе вред?','self_harm_report'))
        self.assertEqual([('unknown',None)],self.values('Не отрицает мысли причинить себе вред.','self_harm_report'))
        self.assertEqual([('negated',False)],self.values('Сегодня отрицает мысли о причинении себе вреда.','self_harm_report'))
        self.assertEqual([('historical',True)],self.values('Ранее хотел причинить себе вред.','historical_self_harm_report'))
        self.assertEqual([('third_party',True)],self.values('Друг хотел причинить себе вред.','third_party_self_harm_report'))
        self.assertEqual([('unknown',None)],self.values('Он хотел причинить себе вред.','self_harm_report'))

    def test_unicode_offsets_date_roles_and_invalid_date(self):
        t='🧭 Получено 12.10.2026. Начало приёма 31.02.2026. Возраст неизвестен.'
        self.assertEqual([('present','2026-10-12')],self.values(t,'received_date'))
        self.assertEqual([('invalid',None)],self.values(t,'medication_start'))
        self.assertEqual([('unknown',None)],self.values(t,'age_years'))
        self.assertEqual([('invalid',None)],self.values('132 года.','age_years'))

    def test_cancellations_and_non_due_tasks_are_source_facts_only(self):
        self.assertEqual([('cancelled_proposal','Авиандр')],self.values('Проект Авиандр 3 мг перечёркнут, назначения не было.','medication'))
        self.assertEqual([('not_due',None)],self.values('Вечер ещё не наступил.','adherence_evening'))
        self.assertEqual('literal-v2',extraction.extract('Без распознанных полей')['version'])

    def test_explicit_nonconfirmation_family_morphology_and_absence(self):
        self.assertEqual([('unknown',None)],self.values('Беременность не подтверждена, анализ неизвестен.','pregnancy_status'))
        self.assertEqual([('third_party',True)],self.values('У сестры суицидальные мысли.','third_party_self_harm_report'))
        self.assertEqual([('negated','тошнота')],self.values('Тошнота отсутствует.','symptom'))
        self.assertEqual([('unknown',None)],self.values('Сведения об аллергии отсутствуют.','medication_allergy'))
        self.assertEqual([('negated',False)],self.values('Есть желание причинить себе вред? Ответ: «Нет, отрицаю».','self_harm_report'))

    def test_corrections_unknown_forms_and_ledger_do_not_create_known_conflicts(self):
        self.assertEqual([('invalid',None),('present',22)],self.values('«20 лет» вписано ошибочно; верно «22 года».','age_years'))
        self.assertEqual([('unknown',None)],self.values('О беременности пациентки данных нет.','pregnancy_status'))
        self.assertEqual([('unknown',None)],self.values('Есть ли сыпь?','symptom'))
        self.assertEqual([('suspected','F41.1'),('suspected','F32.0')],self.values('Рассматриваются F41.1 либо F32.0.','diagnosis'))
        text='препарат X | 4 мг | 1 раз в сутки | действующий\nпрепарат Y | 7 мл | 2 раза в сутки | отменён'
        self.assertEqual([('present',{'value':4,'unit':'mg'}),('stopped',{'value':7,'unit':'ml'})],self.values(text,'dose'))
        self.assertEqual([('not_due',None)],self.values('Приём намечен на 2027-04-12, ещё не состоялся.','event_date'))

    def test_adversarial_unknown_subject_and_negated_cancellation(self):
        for t,f in [('Беременность не исключена.','pregnancy_status'),('Лекарственная аллергия не исключена.','medication_allergy'),('Нет сведений, есть ли беременность.','pregnancy_status'),('Неизвестно, есть ли одышка.','dyspnea'),('Сведений о сыпи нет.','symptom'),('Сыпь могла быть, но никто не уверен.','symptom')]:
            self.assertEqual([('unknown',None)],self.values(t,f),(t,f))
        self.assertEqual([('present',True)],self.values('У матери аллергии нет, у пациентки лекарственная аллергия есть.','medication_allergy'))
        self.assertEqual([('patient_reported','Авиандр')],self.values('Мать сообщает: пациент принимает Авиандр.','medication'))
        self.assertEqual([('third_party','Авиандр')],self.values('Брат пациента принимает Авиандр.','medication'))
        self.assertEqual([('third_party',True)],self.values('У пациентки сестра сообщает про суицидальные мысли.','third_party_self_harm_report'))
        for t in ('Приём Авиандра не подтверждён.','Пациент не уверен, что принимает Авиандр.','Возможно, пациент принимает Авиандр.'):
            self.assertEqual([('unknown',None)],self.values(t,'medication'),t)
        self.assertEqual([('listed','препарат X')],self.values('Препарат X не отменён, доза 4 мг.','medication'))

    def test_common_scope_rules_apply_to_every_boolean_and_risk_branch(self):
        for t,f in [('Есть ли беременность?','pregnancy_status'),('Лекарственную аллергию отрицает?','medication_allergy'),('Суицидальные мысли не исключены.','self_harm_report'),('Вероятно, сейчас есть суицидальные мысли.','self_harm_report')]:
            self.assertEqual([('unknown',None)],self.values(t,f),(t,f))
        self.assertEqual([('third_party',True)],self.values('У брата одышка.','dyspnea'))
        self.assertEqual([('third_party',True)],self.values('Мать жалуется на тошноту.','nausea'))

    def test_disclosed_jury_temporal_and_inflection_regressions(self):
        self.assertEqual([('present',{'value':4,'unit':'mg'}),('present',{'value':8,'unit':'mg'})],self.values('Пациент принимает препарат X по 4 мг утром и 8 мг вечером.','dose'))
        self.assertTrue(all(s=='conflicting' for s,_ in self.values('Препарат X 4 мг утром и 8 мг утром.','dose')))
        self.assertTrue(all(s=='conflicting' for s,_ in self.values('Препарат X 4 мг и 8 мг утром.','dose')))
        text='В 18 лет отмечал тревогу. Сейчас 32 года.'
        self.assertEqual([('historical',18),('present',32)],self.values(text,'age_years'))
        self.assertEqual([('historical',True)],self.values(text,'anxiety'))
        text='Сегодня суицидальных мыслей нет, однако вчера были.'
        self.assertEqual([('negated',False)],self.values(text,'self_harm_report'))
        self.assertEqual([('historical',True)],self.values(text,'historical_self_harm_report'))
        for field in ('pregnancy_status','lactation_status','medication_allergy'):
            self.assertEqual([('negated',False)],self.values('Беременности нет. Лактации нет. Аллергии на лекарства нет.',field))

    def test_long_input_is_bounded_and_has_exact_quotes(self):
        text=('Авиандр в списке, '*650)[:23000]
        started=time.perf_counter()
        self.values(text,'medication')
        self.assertLess(time.perf_counter()-started,3.0)
        with self.assertRaises(extraction.ExtractionError):extraction.extract('9'*101+' мг')


if __name__=='__main__':unittest.main()
