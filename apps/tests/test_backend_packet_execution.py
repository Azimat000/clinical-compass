"""Packet mechanics and queue fences; fake assertions never prove model quality."""
from copy import deepcopy
from datetime import timedelta
import json
import secrets
import sqlite3
import unittest
from unittest.mock import patch

from apps.compass import backend_packet_pipeline as pipeline, backend_packet_store as storage
from apps.compass import backend_jobs as jobs, backend_analyses as analyses, backend_risk_context as risk
from apps.compass import backend_model as model, records
from apps.tests import test_backend_diagnosis_codec as mechanical
from apps.tests.diagnosis_fixtures import named_responses


class LocalModel:
    def __init__(self,responses,fail_at=None):self.responses=responses;self.calls=[];self.fail_at=fail_at
    def generate(self,data,schema,**kw):
        self.calls.append(deepcopy(data))
        if self.fail_at==len(self.calls):raise model.ModelError('transport_error')
        if data['branch']=='risk':return {'value':{'candidates':[]},'metadata':{'test_double':True}}
        value=deepcopy(self.responses[data['branch']]);allowed={uid for group in data['groups'] for uid in group['unit_ids']}
        value['quotes']=[q for q in value['quotes'] if q['unit_id'] in allowed];ids={q['id'] for q in value['quotes']}
        for f in value['facts']:
            if set(f['refs'])-ids:f.update(state='unknown',refs=[])
        d=value['duration']
        if set(d['refs'])-ids:d.update(state='unknown',value=None,refs=[])
        return {'value':value,'metadata':{'test_double':True}}


class PacketExecutionTests(unittest.TestCase):
    def setUp(self):
        self.mechanics=mechanical.NamedCodecTests();self.mechanics.setUp()
        self.f=self.mechanics.case;self.addCleanup(self.f.close)
        self.f.db.execute('UPDATE backend_job_settings SET generation_version=?',(pipeline.EXECUTION_VERSION,))

    def setup_work(self,long=False,operation='diagnosis'):
        if long:
            for i in range(40):
                records.save(self.f.db,self.f.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
                    'observed_on':records.today().isoformat(),'summary':f'Техническая синтетическая строка {i}. '+('Данных о симптомах не собирали. '*6),'wellbeing':'unknown'})
        run=analyses.create(self.f.db,self.f.user,'D01',{'contract_version':'1.0','operation':operation,'request_key':secrets.token_hex(16)})
        work=jobs.claim(self.f.db,'risk' if operation=='risk' else 'generation')
        self.assertEqual(run['run_id'],work['run']['id'])
        responses=named_responses(self.mechanics.positive())
        units=risk.prepare_snapshot(work['snapshot'])
        for value in responses.values():
            for q in value['quotes']:q['unit_id']=next(u['unit_id'] for u in units if u['text']==q['quote'])
        return run,work,LocalModel(responses),storage.Store(self.f.path,work)

    def test_long_queue_completes_all_packets_and_atomic_publication(self):
        run,work,adapter,store=self.setup_work(True)
        value=pipeline.execute('diagnosis',work['snapshot'],adapter,store)
        self.assertGreater(len(adapter.calls),2)
        self.assertEqual(len(adapter.calls),self.f.db.execute('SELECT count(*) FROM analysis_packet_results').fetchone()[0])
        self.assertEqual('running',analyses.read(self.f.db,self.f.user,'D01',run['run_id'])['status'])
        self.assertTrue(jobs.finish(self.f.db,work,value))
        result=analyses.read(self.f.db,self.f.user,'D01',run['run_id'])
        self.assertEqual('ready',result['status'])
        self.assertEqual('depressive_episode',result['result']['output']['leading']['id'])
        self.assertEqual(0,self.f.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
        self.assertEqual(0,len(self.f.db.execute('PRAGMA foreign_key_check').fetchall()))

    def test_failure_retries_only_missing_checkpoint_and_never_partial_ready(self):
        run,work,adapter,store=self.setup_work(True);adapter.fail_at=2
        with self.assertRaises(model.ModelError):pipeline.execute('diagnosis',work['snapshot'],adapter,store)
        self.assertEqual(1,self.f.db.execute('SELECT count(*) FROM analysis_packet_results').fetchone()[0])
        self.assertEqual('running',analyses.read(self.f.db,self.f.user,'D01',run['run_id'])['status'])
        jobs.finish(self.f.db,work,error='transport_error')
        self.f.db.execute("UPDATE backend_jobs SET available_at='2000'")
        second=jobs.claim(self.f.db,'generation');adapter.fail_at=None
        value=pipeline.execute('diagnosis',second['snapshot'],adapter,storage.Store(self.f.path,second))
        self.assertEqual(len(value['packet_proof']['cells'])+1,len(adapter.calls))
        self.assertTrue(jobs.finish(self.f.db,second,value))
        self.assertEqual('ready',analyses.read(self.f.db,self.f.user,'D01',run['run_id'])['status'])

    def test_tampered_or_missing_packet_proof_cannot_publish(self):
        run,work,adapter,store=self.setup_work()
        value=pipeline.execute('diagnosis',work['snapshot'],adapter,store)
        for variant in ('missing','cell','raw'):
            bad=deepcopy(value)
            if variant=='missing':bad.pop('packet_proof')
            if variant=='cell':bad['packet_proof']['cells'].pop()
            if variant=='raw':bad['diagnosis_report']['context']['raw']['facts'][0]=[]
            with self.subTest(variant=variant):
                self.assertTrue(jobs.finish(self.f.db,work,bad))
                self.assertNotEqual('ready',analyses._latest(self.f.db,run['run_id'])['status'])
                # A new lease is required for another publication attempt.
                self.f.db.execute("UPDATE backend_jobs SET available_at='2000'")
                work=jobs.claim(self.f.db,'generation')
                if work is None:break

    def test_cancellation_revocation_and_lease_fences_stop_before_next_call(self):
        for mutation in ('cancel','role','lease','relationship'):
            _,work,adapter,store=self.setup_work()
            if mutation=='cancel':jobs.cancel(self.f.db,self.f.user,'D01',work['run']['id'])
            if mutation=='role':self.f.db.execute("UPDATE users SET disabled=1 WHERE id='doc-a'")
            if mutation=='lease':self.f.db.execute("UPDATE backend_jobs SET lease_until='2000'")
            if mutation=='relationship':self.f.db.execute("UPDATE care_relationships SET ends_at='2000'")
            with self.subTest(mutation=mutation),self.assertRaises(model.ModelError):pipeline.execute('diagnosis',work['snapshot'],adapter,store)
            self.assertEqual([],adapter.calls)
            if mutation!='cancel':
                self.f.db.execute("UPDATE users SET disabled=0 WHERE id='doc-a'")
                self.f.db.execute('UPDATE care_relationships SET ends_at=NULL')
                self.f.db.execute("UPDATE backend_jobs SET state='done',token=NULL,lease_until=NULL WHERE state='running'")

    def test_packet_response_cannot_cite_a_different_packet(self):
        _,work,adapter,_=self.setup_work(True)
        planned=pipeline.plans(work['snapshot'],'diagnosis')['depressive_episode'][0]
        first=planned['packets'][0];allowed={o[0] for r in first['units'] for o in r[3]}
        outside=next(u for u in risk.prepare_snapshot(work['snapshot']) if u['unit_id'] not in allowed)
        value=deepcopy(adapter.responses['depressive_episode']);value['quotes'][0].update(unit_id=outside['unit_id'],quote=outside['text'])
        with self.assertRaisesRegex(model.ModelError,'packet_evidence_mismatch'):pipeline.check_response(work['snapshot'],'depressive_episode',first,value)

    def test_same_day_opposites_conflict_and_old_dates_do_not_fill_current_facts(self):
        _,work,adapter,_=self.setup_work(True)
        snapshot=work['snapshot'];raw=deepcopy(adapter.responses['depressive_episode'])
        units=risk.prepare_snapshot(snapshot)
        q1=raw['quotes'][0];other=next(u for u in units if u['unit_id']!=q1['unit_id'] and pipeline.eligible(u,snapshot['day']))
        second=deepcopy(raw);second['quotes'][0].update(unit_id=other['unit_id'],quote=other['text'])
        # Pure merge mechanics; semantic correctness of these fake claims is not asserted.
        fid=raw['facts'][0]['id'];raw['facts'][0].update(state='present',refs=[q1['id']]);second['facts'][0].update(state='denied',refs=[second['quotes'][0]['id']])
        merged=pipeline.merge_branch(snapshot,'depressive_episode',[{'response':{'value':raw}},{'response':{'value':second}}])
        self.assertEqual('conflicting',next(f for f in merged['facts'] if f['id']==fid)['state'])
        old=deepcopy(snapshot)
        # Modify the extracted unit metadata only through a pure test stub.
        old_units=deepcopy(units)
        next(u for u in old_units if u['unit_id']==q1['unit_id'])['metadata']['event_at']='2020-01-01'
        with patch.object(pipeline.risk,'prepare_snapshot',return_value=old_units):
            merged=pipeline.merge_branch(old,'depressive_episode',[{'response':{'value':raw}}])
        self.assertEqual('unknown',next(f for f in merged['facts'] if f['id']==fid)['state'])

    def test_risk_partial_model_failure_keeps_only_independent_structured_result(self):
        _,work,adapter,store=self.setup_work(True,'risk');adapter.fail_at=2
        value=pipeline.execute('risk',work['snapshot'],adapter,store)
        report=value['risk_context_report']
        self.assertEqual('not_evaluated',report['model_evaluation']);self.assertEqual([],report['model_candidates'])
        self.assertTrue(report['errors'])
        self.assertTrue(jobs.finish(self.f.db,work,value))

    def test_new_data_stops_further_calls_before_publication(self):
        _,work,adapter,store=self.setup_work()
        records.save(self.f.db,self.f.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
            'observed_on':records.today().isoformat(),'summary':'Новое синтетическое уточнение после старта анализа.','wellbeing':'unknown'})
        with self.assertRaisesRegex(model.ModelError,'cancelled'):pipeline.execute('diagnosis',work['snapshot'],adapter,store)
        self.assertEqual([],adapter.calls)

    def test_unknown_packet_does_not_erase_a_positive_safety_assertion(self):
        _,work,adapter,_=self.setup_work()
        positive=deepcopy(adapter.responses['depressive_episode'])
        fact=next(f for f in positive['facts'] if f['id']=='mania_hypomania');fact.update(state='present')
        unknown=deepcopy(positive)
        next(f for f in unknown['facts'] if f['id']=='mania_hypomania').update(state='unknown')
        merged=pipeline.merge_branch(work['snapshot'],'depressive_episode',[{'response':{'value':positive}},{'response':{'value':unknown}}])
        self.assertEqual('present',next(f for f in merged['facts'] if f['id']=='mania_hypomania')['state'])

    def test_unadmitted_risk_model_never_erases_independent_rules(self):
        _,work,_,_=self.setup_work(operation='risk')
        with patch.object(pipeline,'QUALITY',__import__('pathlib').Path('/nonexistent-quality.json')), \
             patch.object(model,'DeepSeek',side_effect=AssertionError('No provider call')):
            value=pipeline.execute('risk',work['snapshot'])
        self.assertEqual(pipeline.risk.rules.evaluate(work['snapshot']),value['risk_context_report']['structured'])
        self.assertEqual('not_evaluated',value['risk_context_report']['model_evaluation'])
        self.assertEqual('packet_quality_not_admitted',value['packet_proof']['incomplete'])

    def test_checkpoint_rows_are_immutable_and_new_lease_is_longer_than_deadline(self):
        _,work,adapter,store=self.setup_work()
        value=pipeline.execute('diagnosis',work['snapshot'],adapter,store)
        lease=self.f.db.execute('SELECT lease_until FROM backend_jobs').fetchone()[0]
        started=self.f.db.execute('SELECT started_at FROM backend_job_attempts').fetchone()[0]
        seconds=(__import__('datetime').datetime.fromisoformat(lease)-__import__('datetime').datetime.fromisoformat(started)).total_seconds()
        self.assertGreaterEqual(seconds,239);self.assertLessEqual(seconds,240)
        for sql in ('UPDATE analysis_packet_results SET response_json=\'{}\'','DELETE FROM analysis_packet_results'):
            with self.assertRaises(sqlite3.IntegrityError):self.f.db.execute(sql)
        self.assertEqual(4000000,pipeline.config().total_micro_usd)
        self.assertEqual(20000,pipeline.config().per_call_micro_usd)

if __name__=='__main__':unittest.main()
