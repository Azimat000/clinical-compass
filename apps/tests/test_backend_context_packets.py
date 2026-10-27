"""Lossless packet boundaries are a transport property, not medical validation."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from apps.compass import backend_context_packets as packets, backend_model as model

SCHEMA={'type':'object','properties':{},'required':[],'additionalProperties':False}


def payload(count=30, length=90):
    return {'task':'Synthetic transport test. No clinical inference.', 'version':'test',
        'columns':['unit_id','text','categories','code','metadata_index'],
        'metadata_columns':['event_at','current_revision','status'],
        'metadata':[['2026-10-01',False,'unknown'],['2026-10-27',True,'known'],[None,None,'missing']],
        'units':[['u'+str(i),'Строка №'+str(i)+' е\u0308 🙂\n'+'x'*length,['wellbeing'],'summary',i%3] for i in range(count)]}


class ContextPacketTests(unittest.TestCase):
    def setUp(self):
        self.config=model.Config(model='deepseek-flash',max_input_bytes=2200,max_output_tokens=32)

    def test_complete_ordered_unicode_history_and_metadata_roundtrip(self):
        source=payload();source['metadata'].append(['unused-preserved',False,'known'])
        before=deepcopy(source);plan=packets.prepare(source,SCHEMA,self.config)
        self.assertGreater(len(plan['packets']),1)
        self.assertEqual(source,packets.restore(plan,expected_sha256=packets.digest(source)))
        self.assertEqual(before,source)
        all_ids=[uid for _,uid in sorted((o[1],o[0]) for p in plan['packets'] for r in p['units'] for o in r[3])]
        self.assertEqual([r[0] for r in source['units']],all_ids)
        for p in plan['packets']:
            self.assertLessEqual(model.preflight(p,SCHEMA,self.config)['input_bytes'],2200)
            self.assertTrue(p['task'].startswith(packets.PREFIX))

    def test_exact_duplicates_share_text_but_never_identity_or_revision(self):
        source=payload(4);source['units'][1][1]=source['units'][0][1]
        plan=packets.prepare(source,SCHEMA,self.config)
        p=plan['packets'][0]
        first=p['units'][0][3]
        self.assertEqual(2,len(first))
        self.assertNotEqual(first[0][0],first[1][0])
        self.assertNotEqual(first[0][2],first[1][2])
        self.assertEqual(source,packets.restore(plan,expected_sha256=packets.digest(source)))

    def test_budget_limit_can_split_before_byte_limit(self):
        cfg=model.Config(model='deepseek-flash',max_input_bytes=16000,max_output_tokens=32,per_call_micro_usd=2400,total_micro_usd=1000000)
        plan=packets.prepare(payload(),SCHEMA,cfg)
        self.assertGreater(len(plan['packets']),1)
        self.assertTrue(all(m['reservation_micro_usd']<=2400 for m in plan['measurements']))
        self.assertLess(max(m['input_bytes'] for m in plan['measurements']),16000)
        self.assertEqual(sum(m['reservation_micro_usd'] for m in plan['measurements']),plan['total_reservation_micro_usd'])
        self.assertEqual(cfg.total_micro_usd,1000000)

    def test_single_oversize_record_is_rejected_whole_and_named_by_index(self):
        source=payload(3);source['units'][1][1]='NEVER TRUNCATE '*2000
        before=deepcopy(source)
        with self.assertRaises(packets.PacketError) as caught:packets.prepare(source,SCHEMA,self.config)
        self.assertEqual('unit_exceeds_limit',caught.exception.code)
        self.assertEqual(1,caught.exception.unit_index)
        self.assertNotIn('TRUNCATE',str(caught.exception))
        self.assertEqual(before,source)

    def test_packet_count_bound_and_base_bound_fail_before_any_execution(self):
        with self.assertRaisesRegex(packets.PacketError,'packet_count_exceeded'):
            packets.prepare(payload(),SCHEMA,self.config,max_packets=1)
        source=payload();source['task']='x'*10000
        with self.assertRaisesRegex(packets.PacketError,'base_exceeds_limit'):
            packets.prepare(source,SCHEMA,self.config)
        for bad in [True,0,65,'4']:
            with self.assertRaisesRegex(packets.PacketError,'invalid_packet_limit'):
                packets.prepare(payload(),SCHEMA,self.config,max_packets=bad)

    def test_empty_complete_input_is_still_one_verified_packet(self):
        source=payload(0);plan=packets.prepare(source,SCHEMA,self.config)
        self.assertEqual(1,len(plan['packets']))
        self.assertEqual(source,packets.restore(plan,expected_sha256=packets.digest(source)))

    def test_missing_duplicate_reordered_modified_packets_and_text_reject(self):
        source=payload();plan=packets.prepare(source,SCHEMA,self.config);expected=packets.digest(source)
        for variant in ['missing','duplicate','reorder','text','metadata','base','wrong_source','row']:
            with self.subTest(variant=variant):
                bad=deepcopy(plan)
                if variant=='missing':bad['packets'].pop();bad['packet_sha256'].pop()
                if variant=='duplicate':bad['packets'].append(deepcopy(bad['packets'][0]));bad['packet_sha256'].append(bad['packet_sha256'][0])
                if variant=='reorder':bad['packets'].reverse();bad['packet_sha256'].reverse()
                if variant=='text':bad['packets'][0]['texts'][0]+='tampered'
                if variant=='metadata':bad['original_metadata'][0][1]=True
                if variant=='base':bad['base']['version']='tampered'
                if variant=='wrong_source':bad['source_sha256']='0'*64
                if variant=='row':bad['packets'][0]['units'][0][0]=9999
                with self.assertRaises(packets.PacketError):packets.restore(bad,expected_sha256=expected)

    def test_rehashing_tampered_text_does_not_defeat_pinned_source_digest(self):
        source=payload();plan=packets.prepare(source,SCHEMA,self.config)
        plan['packets'][0]['texts'][0]+='malformed'
        plan['packet_sha256'][0]=packets.digest(plan['packets'][0])
        with self.assertRaisesRegex(packets.PacketError,'source_integrity'):
            packets.restore(plan,expected_sha256=packets.digest(source))

    def test_rehashed_packet_cannot_remove_transport_instructions(self):
        source=payload();plan=packets.prepare(source,SCHEMA,self.config)
        plan['packets'][0]['task']=source['task']
        plan['packet_sha256'][0]=packets.digest(plan['packets'][0])
        with self.assertRaisesRegex(packets.PacketError,'packet_base_mismatch'):
            packets.restore(plan,expected_sha256=packets.digest(source))

    def test_invalid_original_ids_metadata_and_nonfinite_values_fail(self):
        for variant in ['duplicate_id','metadata','bool_index','nonfinite','reserved','columns']:
            source=payload()
            if variant=='duplicate_id':source['units'][1][0]=source['units'][0][0]
            if variant=='metadata':source['metadata'][0].pop()
            if variant=='bool_index':source['units'][0][4]=True
            if variant=='nonfinite':source['test']=float('nan')
            if variant=='reserved':source['transport']={}
            if variant=='columns':source['columns'].pop()
            with self.subTest(variant=variant), self.assertRaises(packets.PacketError):
                packets.prepare(source,SCHEMA,self.config)

    def test_planner_never_calls_model_transport_or_budget(self):
        with patch.object(model.DeepSeek, 'generate', side_effect=AssertionError('No model execution')), \
             patch.object(model.Budget, 'reserve', side_effect=AssertionError('No paid reservation')), \
             patch.object(model, 'https_transport', side_effect=AssertionError('No network')):
            plan=packets.prepare(payload(),SCHEMA,self.config)
            self.assertEqual(payload(),packets.restore(plan,expected_sha256=packets.digest(payload())))

    def test_deterministic_plan_and_independent_source_digest_required(self):
        source=payload();a=packets.prepare(source,SCHEMA,self.config)
        self.assertEqual(a,packets.prepare(deepcopy(source),SCHEMA,self.config))
        with self.assertRaises(packets.PacketError):packets.restore(a,expected_sha256='1'*64)


if __name__=='__main__':unittest.main()
