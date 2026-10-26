"""Named codec, clean fixture isolation and cost sizing; no real model quality claim."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from apps.compass import backend_diagnosis_codec as codec, backend_diagnosis_service as service
from apps.compass import backend_risk_context as context, backend_model as model
from apps.tests.diagnosis_fixtures import CleanDiagnosticCase, BranchModel, named_responses

ROOT=Path(__file__).resolve().parents[2]

class NamedCodecTests(unittest.TestCase):
    def setUp(self):
        self.case=CleanDiagnosticCase();self.addCleanup(self.case.close)
        self.case.populate({'note':'Авторское текущее основание механического теста: 14 дней и 6 месяцев. Генерализованная общая тревога; из-за тревоги сосредоточение и засыпание; соматическая причина.'})
        self.snapshot=self.case.snapshot()
        self.raw={'quotes':[],'facts':[[] for _ in range(56)],
                  'durations':{k:{'value':None,'refs':[]} for k in service.legacy.KINDS[:2]},'leading':None}

    def positive(self,kinds=('depressive_episode',)):
        u=next(u for u in context.prepare_snapshot(self.snapshot) if u['code']=='summary')
        raw=deepcopy(self.raw);raw['quotes']=[{'u':u['unit_id'],'q':u['text']}]
        catalog=service.criteria.release()
        for i,(kind,fid) in enumerate(service.fact_index(catalog)):
            if kind not in kinds:continue
            condition=catalog['conditions'][kind]
            denied=any(c['state']=='denied' and fid in c['facts'] for c in condition['checks'])
            raw['facts'][i]=[-1 if denied else 1]
            raw['durations'][kind]={'value':condition['duration']['minimum'],'refs':[1]}
        return raw

    def test_explicit_names_order_independent_and_all_unknown_no_leading(self):
        responses=named_responses(self.raw)
        for part in responses.values():part['facts'].reverse()
        result=service.named_interpret(self.snapshot,responses)
        self.assertEqual('insufficient_data',result['disposition']);self.assertIsNone(result['leading'])
        self.assertTrue(all(f['state']=='unknown' for h in result['hypotheses'][:2] for f in h['facts']))
        self.assertTrue(all(h['distinguishing_questions'] for h in result['hypotheses']))

    def test_missing_duplicate_and_unknown_ids_reject_without_positional_guess(self):
        good=named_responses(self.raw)
        for variant in ('missing','duplicate','unknown','leading','position'):
            value=deepcopy(good);part=value['depressive_episode']
            if variant=='missing':part['facts'].pop()
            if variant=='duplicate':part['facts'][1]=deepcopy(part['facts'][0])
            if variant=='unknown':part['facts'][0]['id']='invented'
            if variant=='leading':part['leading']='depressive_episode'
            if variant=='position':part['facts']=[[]]*21
            with self.assertRaises(ValueError):codec.normalize(value)

    def test_two_full_calls_identical_lossless_units_and_explicit_schemas(self):
        adapter=BranchModel(named_responses(self.positive()))
        report=service.analyze_snapshot(self.snapshot,adapter,synthetic=True)
        self.assertEqual('depressive_episode',report['context']['leading']);self.assertEqual(2,len(adapter.calls))
        first,second=adapter.calls
        self.assertEqual(first[0]['units'],second[0]['units'])
        decoded=[row[:4]+first[0]['metadata'][row[4]] for row in first[0]['units']]
        self.assertEqual(context.model_payload(context.prepare_snapshot(self.snapshot))['units'],decoded)
        self.assertEqual(context.model_payload(context.prepare_snapshot(self.snapshot))['columns'],
                         first[0]['columns'][:4]+first[0]['metadata_columns'])
        self.assertEqual({'questionnaires','wellbeing','anamnesis','visits'},
                         {c for u in context.prepare_snapshot(self.snapshot) for c in u['categories']})
        for payload,schema,kw in adapter.calls:
            self.assertTrue(kw['synthetic']);self.assertIn('Example JSON',payload['task'])
            self.assertEqual(set(payload['facts']),set(schema['properties']['facts']['items']['properties']['id']['enum']))
            self.assertNotIn('check_columns',payload)
            for private in ('source_ref','source_sha256','author_id','patient_id'):
                self.assertNotIn(private,json.dumps(payload))

    def test_both_supported_branches_need_physician_comparison_no_arbitrary_leading(self):
        value=service.named_interpret(self.snapshot,named_responses(self.positive(service.legacy.KINDS[:2])))
        self.assertIsNone(value['leading']);self.assertEqual('insufficient_data',value['disposition'])
        self.assertTrue(all(h['outcome']=='criteria_supported_unreviewed' for h in value['hypotheses'][:2]))

    def test_quote_duplicates_unknown_state_and_unused_quote_fail(self):
        good=named_responses(self.positive())
        for variant in ('same_id','same_text','bad_ref'):
            value=deepcopy(good);part=value['depressive_episode']
            if variant=='same_id':part['quotes'].append(deepcopy(part['quotes'][0]))
            if variant=='same_text':part['quotes'].append({**part['quotes'][0],'id':'q2'})
            if variant=='bad_ref':part['facts'][0]['refs']=['q8']
            with self.assertRaises(ValueError):codec.normalize(value)

    def test_unused_quotes_are_provenance_checked_without_inventing_facts(self):
        value=named_responses(self.positive())
        unit=context.prepare_snapshot(self.snapshot)
        q=next(u for u in unit if u['code']=='summary')
        extra={'id':'q2','unit_id':q['unit_id'],'quote':q['text'][:10]}
        value['depressive_episode']['quotes'].append(extra)
        result=service.named_interpret(self.snapshot,value)
        self.assertEqual(1,len(result['raw']['quotes']))
        extra['quote']='выдуманная неиспользуемая цитата'
        with self.assertRaises(ValueError):service.named_interpret(self.snapshot,value)

    def test_missingness_citation_never_becomes_positive_or_negative_fact(self):
        value=named_responses(self.positive())
        value['depressive_episode']['facts'][0]['state']='unknown'
        result=service.named_interpret(self.snapshot,value)
        fact=result['hypotheses'][0]['facts'][0]
        self.assertEqual('unknown',fact['state']);self.assertEqual([],fact['refs'])
        self.assertTrue(fact['uncertainty_refs']);self.assertIsNone(result['leading'])
        raw=deepcopy(result['raw']);raw['uncertainty_refs'][0]['field']='low_mood'
        with self.assertRaises(ValueError):service.interpret(self.snapshot,raw)

    def test_qualifier_guards_do_not_erase_positive_causes_or_invent_denials(self):
        self.assertTrue(codec.qualifier_missing('generalized_anxiety','worry_concentration','conflicting',['Трудно сосредоточиться.'],{'value':None}))
        self.assertFalse(codec.qualifier_missing('generalized_anxiety','worry_concentration','denied',['Нет трудностей сосредоточения из-за тревоги.'],{'value':7}))
        self.assertTrue(codec.qualifier_missing('generalized_anxiety','somatic_cause','denied',['Исключена органическая причина.'],{'value':7}))
        self.assertFalse(codec.qualifier_missing('generalized_anxiety','somatic_cause','present',['Врач указал тиреотоксикоз причиной.'],{'value':7}))
        self.assertTrue(codec.qualifier_missing('generalized_anxiety','generalized_anxiety','present',['Тревога.'],{'value':None}))
        self.assertFalse(codec.qualifier_missing('generalized_anxiety','generalized_anxiety','present',['Выраженная общая тревога.'],{'value':7}))

    def test_negative_causes_need_target_but_positive_causes_are_never_suppressed(self):
        raw=self.positive();catalog=service.criteria.release()
        i=service.fact_index(catalog).index(('generalized_anxiety','medication_cause'))
        raw['facts'][i]=[-1]
        result=service.named_interpret(self.snapshot,named_responses(raw))
        fact=next(f for f in result['hypotheses'][1]['facts'] if f['id']=='medication_cause')
        self.assertEqual('unknown',fact['state']);self.assertEqual('target_not_established',fact['qualifier_guard']['reason'])
        raw['facts'][i]=[1]
        result=service.named_interpret(self.snapshot,named_responses(raw))
        self.assertEqual('unsupported',result['disposition'])
        self.assertEqual('present',next(f for f in result['hypotheses'][1]['facts'] if f['id']=='medication_cause')['state'])

    def test_complete_pipeline_timeout_prevents_a_second_branch_after_deadline(self):
        adapter=BranchModel(named_responses(self.raw));clock=[0.0];original=adapter.generate
        def generate(*args,**kw):
            response=original(*args,**kw);clock[0]=61.0;return response
        with patch.object(service.time,'monotonic',side_effect=lambda:clock[0]),patch.object(adapter,'generate',side_effect=generate):
            with self.assertRaisesRegex(model.ModelError,'timeout'):
                service.analyze_snapshot(self.snapshot,adapter,synthetic=True)
        self.assertEqual(1,len(adapter.calls))

    def test_literal_duration_rejects_conversion_zero_rounding_and_dates(self):
        self.assertTrue(codec.literal_duration(5,'months',['В течение пяти месяцев.']))
        self.assertTrue(codec.literal_duration(14,'days',['Ровно 14 дней.']))
        self.assertFalse(codec.literal_duration(240,'days',['Тревога 8 месяцев.']))
        self.assertFalse(codec.literal_duration(0,'months',['Настроение снижено 17 дней.']))
        self.assertFalse(codec.literal_duration(27,'days',['Дата 2026-10-27.']))
        self.assertFalse(codec.literal_duration(3,'months',['Диапазон 2–3 месяца.']))
        value=named_responses(self.positive())
        value['depressive_episode']['duration']['value']=240
        with self.assertRaisesRegex(ValueError,'duration_not_literal'):codec.normalize(value)

    def test_duration_requires_explicit_compatible_state_no_automatic_timestamp(self):
        good=named_responses(self.positive())
        for variant in ('missing_ref','unknown_value','conflict_one_ref','boolean'):
            value=deepcopy(good);d=value['depressive_episode']['duration']
            if variant=='missing_ref':d['refs']=[]
            if variant=='unknown_value':d['state']='unknown'
            if variant=='conflict_one_ref':d.update(state='conflicting',value=None)
            if variant=='boolean':d['value']=True
            with self.assertRaises(ValueError):codec.normalize(value)

    def test_forged_exact_quote_and_second_branch_failure_never_publish_partial(self):
        value=named_responses(self.positive());value['depressive_episode']['quotes'][0]['quote']='выдуманный фрагмент'
        with self.assertRaises(ValueError):service.named_interpret(self.snapshot,value)
        adapter=BranchModel(named_responses(self.positive()));generate=adapter.generate
        def fail_second(data,schema,**kw):
            if data['branch']=='generalized_anxiety':raise model.ModelError('timeout')
            return generate(data,schema,**kw)
        before=self.case.db.execute('SELECT count(*) FROM analysis_result_versions').fetchone()[0]
        with patch.object(adapter,'generate',side_effect=fail_second):
            with self.assertRaisesRegex(model.ModelError,'timeout'):
                service.analyze_snapshot(self.snapshot,adapter,synthetic=True)
        self.assertEqual(before,self.case.db.execute('SELECT count(*) FROM analysis_result_versions').fetchone()[0])
        self.assertEqual(0,self.case.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_sources_changed_after_first_branch_abort_before_second_call(self):
        adapter=BranchModel(named_responses(self.positive()));release=service.release()
        changed={**release,'codec_sha256':'changed'}
        with patch.object(service,'release',side_effect=[release,changed]):
            with self.assertRaisesRegex(model.ModelError,'sources_or_engine_changed'):
                service.analyze_snapshot(self.snapshot,adapter,synthetic=True)
        self.assertEqual(1,len(adapter.calls))

    def test_model_boundary_rejects_real_data_before_adapter_call(self):
        value=deepcopy(self.snapshot);value['patients'][0]['synthetic']=0
        adapter=BranchModel(named_responses(self.raw))
        with self.assertRaises(ValueError):service.analyze_snapshot(value,adapter,synthetic=True)
        self.assertEqual([],adapter.calls)


class CleanCorpusTests(unittest.TestCase):
    def test_all_new_cases_are_fresh_and_have_only_authored_notes_and_empty_defaults(self):
        for name in ('development','holdout'):
            cases=json.loads((ROOT/f'evidence/BE10B02/revision-v2/{name}.json').read_text())
            for case in cases['cases']:
                with self.subTest(case=case['id']):
                    fixture=CleanDiagnosticCase()
                    try:
                        fixture.populate(case);snapshot=fixture.snapshot()
                        fixture.assert_clean(case)
                        self.assertTrue(all(snapshot['patient_history']['counts'][k]>0 for k in context.CATEGORIES))
                        self.assertEqual([],snapshot['encounters'])
                        self.assertFalse(any(r['code']=='synthetic_profile_snapshot' for r in snapshot['observations']))
                        if case['id']!='H04':
                            self.assertTrue(all(v is None for v in json.loads(snapshot['assessments'][0]['answers_json'])))
                        for kind in service.criteria.release()['conditions']:
                            cfg=model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=codec.MAX_OUTPUT_TOKENS)
                            metrics=model.preflight(service.payload(snapshot,kind),codec.schema(kind),cfg)
                            self.assertLessEqual(metrics['reservation_micro_usd'],20000)
                    finally:fixture.close()

    def test_profile_or_accidental_wellbeing_contamination_detected(self):
        fixture=CleanDiagnosticCase()
        try:
            case={'note':'Авторская запись без психиатрического анамнеза.'};fixture.populate(case)
            fixture.db.execute("INSERT INTO encounters(id,patient_id,occurred_at,narrative,origin) VALUES('bad','D01','2026-10-26','Чужой старый ГТР','unapproved')")
            with self.assertRaises(AssertionError):fixture.assert_clean(case)
        finally:fixture.close()

if __name__=='__main__':unittest.main()
