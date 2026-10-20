"""COVERAGE-1 checks provenance, fail-closed gaps, never clinical assertions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from apps.tests import test_retrieval_packages as fixtures
from apps.compass.retrieval_corpus import CorpusError, digest, moment, publish_snapshot, sha
from apps.tests.test_retrieval_primary import make_primary
from apps.compass.retrieval_primary import PREFIX
from apps.compass.retrieval_policies import aspect_mode, instrument_requirements
from test_retrieval_policies import install_policy_fixture
from check_retrieval_coverage import (ROOT, MATRIX, MEDICATIONS, FREEZE, EVIDENCE,
                                     assess, card_catalog, scope, validate_review)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in [MATRIX, MEDICATIONS, FREEZE, EVIDENCE]:
            target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/relative).read_bytes())
        self.frozen,self.matrix,self.meds,self.units=scope(self.root)
        self.records=fixtures.artificial_package(self.root,count=len(self.meds['medications']))
        for item,med in zip(self.records,self.meds['medications']):
            target=med['registration_targets'][0] if med['registration_targets'] else {}
            item['medication_identity']=dict(inn=med['inn'],trade_name=target.get('trade_name','Artificial '+med['id']),
                registration=target.get('registration','ARTIFICIAL-'+med['id']),form=target.get('form','Artificial tablet'),
                strength=target.get('strengths',['Artificial strength'])[0],route=target.get('route','Artificial oral route'),official_url='https://grls.rosminzdrav.ru/artificial')
        fixtures.save(self.root,'data/retrieval/packages/NEW/registry.json',dict(schema_version=1,sources=self.records))
        self.primary=make_primary(self.root)
        self.policy_refs=install_policy_fixture(self.root,self.frozen,self.units)
        fixtures.policy(self.root,['NEW','DASS42'])
        self.refresh_snapshot()
        self.evidence=json.loads((self.root/EVIDENCE).read_text())
        # Real reviews refer to the real source catalog, never to this fixture.
        self.evidence['units']={}

    def refresh_snapshot(self):
        self.registry,manifest,blobs=fixtures.build(self.root)
        self.snapshot=publish_snapshot(self.root/'store',manifest,blobs)[0]

    def result(self):
        fixtures.save(self.root,EVIDENCE,self.evidence)
        return assess(self.root,self.snapshot,fixtures.AT)

    def report_for(self,uid):
        unit=self.units[uid]
        idx=0 if unit['kind']=='cell' else [m['id'] for m in self.meds['medications']].index(unit['medication']['id'])
        item=self.records[idx]
        fragment=json.loads((self.root/item['artifact_path']).read_text())['fragments'][0]
        ref=dict(document_id=item['document_id'],fragment_id=fragment['fragment_id'],page=fragment['page'],
                 section=fragment['section'],source_version=item['source_version'],source_sha256=item['sha256'],
                 artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(fragment))
        report=dict(schema_version=2,scope_version=self.frozen['scope_version'],unit_id=uid,
            requirement_sha256=digest(unit['requirement']),verdict='sufficient',reviewer='Artificial reviewer',
            origin='Artificial tests, not medical approval',sufficiency_explanation='Artificial structure fixture only',
            checked_at='2026-10-20T22:00:00+03:00',review_due_at='2026-10-21T22:00:00+03:00',
            aspects={})
        for a in unit['aspects']:
            mode=aspect_mode(unit,a)
            refs=[] if mode=='policy' else [deepcopy(ref)]
            required=instrument_requirements(unit,a)
            if required is not None:
                refs=[]
                for primary in self.primary:
                    if primary['document_id'] not in required:continue
                    f=json.loads((self.root/primary['artifact_path']).read_text())['fragments'][0]
                    refs.append(dict(document_id=primary['document_id'],fragment_id=f['fragment_id'],page=f['page'],section=f['section'],source_version=primary['source_version'],source_sha256=primary['sha256'],artifact_sha256=primary['artifact_sha256'],fragment_sha256=digest(f)))
            report['aspects'][a]=dict(source_references=refs,policy_references=[deepcopy(self.policy_refs[a])] if mode!='clinical' else [])
        if unit['kind']=='dossier':report['medication_identity']=deepcopy(item['medication_identity'])
        if uid.endswith('/safety_updates_and_version_status'):
            report['safety_check']=dict(checked_sources=['https://grls.rosminzdrav.ru/','https://roszdravnadzor.gov.ru/'],
                scope='Artificial bounded check',result='Artificial test outcome; not evidence of no alerts',
                checked_at=report['checked_at'],review_due_at=report['review_due_at'])
        return report

    def put_report(self,uid,report):
        relative='reviews/'+uid.replace('/','-')+'.json'
        fixtures.save(self.root,relative,report)
        self.evidence['units'][uid]=dict(review_path=relative,review_sha256=sha((self.root/relative).read_bytes()))

    def complete_fixture(self):
        for uid in self.units:self.put_report(uid,self.report_for(uid))

    def test_real_scope_denominators_not_card_count(self):
        result=self.result()
        self.assertEqual(result['status'],'NOT_READY')
        self.assertEqual(result['counts']['cells'],dict(complete=0,required=58))
        self.assertEqual(result['counts']['dossier_sections'],dict(complete=0,required=90))
        self.assertEqual(result['counts']['medications'],dict(complete=0,required=9))
        self.assertEqual(len(result['gaps']),148)
        self.assertEqual(set(c['domain'] for c in self.matrix['cells']),{f'D{i:02}' for i in range(1,13)})

    def test_complete_artificial_attestations_only_structure_ready(self):
        self.complete_fixture();result=self.result()
        self.assertEqual(result['status'],'READY',result['gaps'][:1])
        self.assertEqual(result['clinical_approval'],'NOT_ASSESSED_BY_THIS_TOOL')
        self.assertIn('NOT_TESTED',result['refusal_behavior'])
        self.assertTrue(all(v['complete']==v['required'] for v in result['counts'].values()))

    def test_one_missing_unit_blocks_complete_fixture(self):
        self.complete_fixture();uid=next(iter(self.units));del self.evidence['units'][uid]
        result=self.result();self.assertEqual(result['status'],'NOT_READY')
        self.assertEqual(result['gaps'],[dict(unit_id=uid,kind='cell',reason='sufficiency_evidence_missing')])

    def test_ready_flag_never_replaces_evidence(self):
        self.evidence['ready']=True
        self.assertEqual(self.result()['status'],'NOT_READY')
        self.assertIn('coverage_evidence_schema',self.result()['errors'])

    def test_scope_change_and_empty_denominator_rejected(self):
        path=self.root/MATRIX;data=json.loads(path.read_text());data['cells']=[]
        fixtures.save(self.root,MATRIX,data)
        self.assertTrue(any('frozen_scope_changed' in r for r in self.result()['errors']))
        frozen=json.loads((self.root/FREEZE).read_text());frozen['files'][MATRIX]=sha(path.read_bytes());frozen['required_cells']=0
        fixtures.save(self.root,FREEZE,frozen)
        self.assertIn('empty_denominator',self.result()['errors'])
        (self.root/MATRIX).write_bytes((ROOT/MATRIX).read_bytes())
        frozen=json.loads((ROOT/FREEZE).read_text())
        data=json.loads((self.root/MEDICATIONS).read_text());data['medications'][0]['registration_targets']=[]
        fixtures.save(self.root,MEDICATIONS,data)
        frozen['files'][MEDICATIONS]=sha((self.root/MEDICATIONS).read_bytes());fixtures.save(self.root,FREEZE,frozen)
        self.assertIn('medication_research_target_missing',self.result()['errors'])

    def test_wrong_page_version_hash_or_unadmitted_card_is_gap(self):
        uid=next(iter(self.units));original=self.report_for(uid);aspect=next(iter(original['aspects']))
        for field,value in [('page',999),('source_version','wrong'),('source_sha256','0'*64),('fragment_sha256','0'*64),('fragment_id','missing')]:
            with self.subTest(field=field):
                report=deepcopy(original);report['aspects'][aspect]['source_references'][0][field]=value;self.put_report(uid,report)
                self.assertEqual(self.result()['counts']['cells']['complete'],0)
                self.assertTrue(self.result()['gaps'][0]['reason'].startswith('reference_'))

    def test_missing_aspect_and_expired_or_unverified_review(self):
        uid=next(iter(self.units));original=self.report_for(uid)
        for key,value in [('aspects',{}),('verdict','not_reviewed'),('reviewer',''),('review_due_at',original['checked_at']),('requirement_sha256','0'*64)]:
            with self.subTest(key=key):
                report=deepcopy(original);report[key]=value;self.put_report(uid,report)
                self.assertEqual(self.result()['counts']['cells']['complete'],0)

    def test_review_tampering_and_escaping_paths(self):
        uid=next(iter(self.units));self.put_report(uid,self.report_for(uid))
        pointer=self.evidence['units'][uid];(self.root/pointer['review_path']).write_text('{}')
        self.assertEqual(self.result()['gaps'][0]['reason'],'review_integrity')
        for path in ['../outside.json','/etc/passwd']:
            pointer['review_path']=path
            self.assertEqual(self.result()['counts']['cells']['complete'],0)

    def test_rights_revoked_after_snapshot_invalidates_coverage(self):
        uid='D02-depression-symptoms';self.put_report(uid,self.report_for(uid))
        self.assertEqual(self.result()['counts']['cells']['complete'],1)
        self.records[0]['rights']['status']='revoked'
        fixtures.save(self.root,'data/retrieval/packages/NEW/registry.json',dict(schema_version=1,sources=self.records))
        result=self.result();self.assertEqual(result['counts']['cells']['complete'],0)
        self.assertIn('NEW0',result['refused_sources'])

    def test_missing_exact_medication_identity_and_safety_check(self):
        med=self.meds['medications'][0]
        uid=med['id']+'/'+self.meds['required_sections'][0]
        report=self.report_for(uid);report['medication_identity']['registration']=''
        self.put_report(uid,report)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'medication_identity_unverified')
        report=self.report_for(uid);report['medication_identity']['strength']='Artificial unsupported strength'
        self.put_report(uid,report)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'medication_target_mismatch')
        uid=med['id']+'/safety_updates_and_version_status';report=self.report_for(uid)
        report['safety_check']['checked_sources']=[];self.put_report(uid,report)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'safety_check_incomplete')

    def test_mixed_dossier_identities_block_medication(self):
        self.complete_fixture();med=self.meds['medications'][0]
        # Different valid source identity in another section is not one dossier.
        extra=fixtures.artificial_package(self.root,'NEXT')
        item=extra[0];item['medication_identity']=deepcopy(self.records[0]['medication_identity'])
        item['medication_identity']['strength']=med['registration_targets'][0]['strengths'][1]
        fixtures.save(self.root,'data/retrieval/packages/NEXT/registry.json',dict(schema_version=1,sources=extra))
        fixtures.policy(self.root,['NEW','NEXT','DASS42'])
        self.refresh_snapshot()
        uid=med['id']+'/'+self.meds['required_sections'][0]
        report=self.report_for(uid);report['medication_identity']=item['medication_identity']
        fragment=json.loads((self.root/item['artifact_path']).read_text())['fragments'][0]
        ref=dict(document_id=item['document_id'],fragment_id=fragment['fragment_id'],page=fragment['page'],
            section=fragment['section'],source_version=item['source_version'],source_sha256=item['sha256'],
            artifact_sha256=item['artifact_sha256'],fragment_sha256=digest(fragment))
        report['aspects']={a:dict(source_references=[deepcopy(ref)],policy_references=[]) for a in report['aspects']};self.put_report(uid,report)
        result=self.result()
        self.assertEqual(result['status'],'NOT_READY')
        self.assertEqual(result['counts']['medications']['complete'],8)
        self.assertEqual(sum(g['reason']=='dossier_identity_conflict' for g in result['gaps']),10)
        self.assertEqual(result['counts']['cells']['complete'],20)

    def test_no_snapshot_or_unknown_evidence_cannot_be_ready(self):
        self.complete_fixture();fixtures.save(self.root,EVIDENCE,self.evidence)
        self.assertEqual(assess(self.root,None,fixtures.AT)['status'],'NOT_READY')
        self.evidence['units']['made_up']={}
        self.assertIn('evidence_unknown_unit',self.result()['errors'])

    def test_invalid_audit_time_fails_closed(self):
        self.assertEqual(assess(self.root,self.snapshot,'unknown')['status'],'NOT_READY')

    def test_patient_leaflet_cannot_replace_professional_dossier(self):
        uid=self.meds['medications'][0]['id']+'/'+self.meds['required_sections'][0]
        report=self.report_for(uid);self.put_report(uid,report)
        catalog,_=card_catalog(self.snapshot,self.registry,moment(fixtures.AT),self.root)
        for item,fragment in catalog.values():item['document_type']='patient_leaflet'
        with self.assertRaisesRegex(CorpusError,'professional_dossier_source_missing'):
            validate_review(self.root,uid,self.units[uid],self.evidence['units'][uid],catalog,self.frozen,moment(fixtures.AT))

    def test_policy_only_cannot_be_filled_with_a_clinical_card(self):
        uid='D02-depression-symptoms';r=self.report_for(uid)
        r['aspects']['missing_data']=deepcopy(r['aspects']['symptoms'])
        self.put_report(uid,r)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'policy_must_have_separate_origin')

    def test_mixed_instrument_aspect_requires_both_origins(self):
        uid='D12-depression-scale_interpretation';original=self.report_for(uid)
        for key in ['source_references','policy_references']:
            r=deepcopy(original);r['aspects']['three_separate_scores_for_physician'][key]=[];self.put_report(uid,r)
            self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'mixed_evidence_requires_both_origins')

    def test_DASS_sources_cannot_replace_medication_or_other_clinical_knowledge(self):
        uid='D02-depression-symptoms';r=self.report_for(uid)
        dass=self.report_for('D12-depression-scale_identity')['aspects']['recall_period']['source_references']
        r['aspects']['symptoms']['source_references']=dass;self.put_report(uid,r)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'primary_source_scope_mismatch')

    def test_KR_cannot_masquerade_as_exact_DASS_validation(self):
        uid='D12-depression-scale_identity';r=self.report_for(uid)
        old=self.report_for('D02-depression-symptoms')['aspects']['symptoms']['source_references']
        r['aspects']['validation_population']['source_references']=old;self.put_report(uid,r)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'exact_instrument_primary_source_missing')

    def test_same_age_aspect_in_FU08_cannot_use_DASS_source_or_policy(self):
        uid='D01-generalized_anxiety_disorder-FU08';original=self.report_for(uid)
        dass=self.report_for('D12-depression-scale_identity')['aspects']['age_boundary']
        r=deepcopy(original);r['aspects']['age_boundary']['source_references']=dass['source_references'];self.put_report(uid,r)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'primary_source_scope_mismatch')
        r=deepcopy(original);r['aspects']['age_boundary']=dass;self.put_report(uid,r)
        self.assertEqual(next(g for g in self.result()['gaps'] if g['unit_id']==uid)['reason'],'policy_cannot_replace_clinical_source')

    def test_v1_remains_readable_for_clinical_only_but_cannot_hide_policy_origin(self):
        catalog,_=card_catalog(self.snapshot,self.registry,moment(fixtures.AT),self.root)
        for uid,valid in [('D01-depression-context',True),('D02-depression-symptoms',False)]:
            r=self.report_for(uid);r['schema_version']=1
            r['aspects']={a:e['source_references'] for a,e in r['aspects'].items()};self.put_report(uid,r)
            if valid:
                validate_review(self.root,uid,self.units[uid],self.evidence['units'][uid],catalog,self.frozen,moment(fixtures.AT))
            else:
                with self.assertRaisesRegex(CorpusError,'separate_policy_evidence_required'):
                    validate_review(self.root,uid,self.units[uid],self.evidence['units'][uid],catalog,self.frozen,moment(fixtures.AT))
            self.evidence['units'].clear()

    def test_cell_attestations_cannot_bypass_required_dossiers(self):
        for uid,unit in self.units.items():
            if unit['kind']=='cell':self.put_report(uid,self.report_for(uid))
        result=self.result()
        self.assertEqual(result['counts']['cells']['complete'],20)
        blocked=[g for g in result['gaps'] if g['reason']=='required_dossiers_incomplete']
        self.assertEqual(len(blocked),38)
        self.assertTrue(all(len(g['missing_dossiers'])==9 for g in blocked))

    def test_one_missing_dossier_section_withdraws_dependent_cells(self):
        self.complete_fixture()
        uid=self.meds['medications'][0]['id']+'/monitoring'
        del self.evidence['units'][uid]
        result=self.result()
        self.assertEqual(result['counts']['cells']['complete'],20)
        self.assertEqual(result['counts']['medications']['complete'],8)
        self.assertEqual(sum(g['reason']=='required_dossiers_incomplete' for g in result['gaps']),38)


if __name__ == '__main__':unittest.main()
