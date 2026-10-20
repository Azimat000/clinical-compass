"""Closed official KR receipt admission; no network or original document copies."""
import copy,json,shutil,tempfile,unittest
from pathlib import Path
from apps.compass.retrieval_corpus import (PROJECT_ROOT,CorpusError,admission_reasons,
    build_manifest,indexable_cards,moment,publish_snapshot,reference_reasons,sha)
from apps.compass.retrieval_primary import (GUIDELINE_POLICY,GUIDELINE_PREFIX,
    GUIDELINE_STORAGE,GUIDELINE_IDENTITIES,POLICY,PREFIX,validate_primary)


class GuidelineReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        paths=[GUIDELINE_POLICY]+[str(p.relative_to(PROJECT_ROOT)) for p in (PROJECT_ROOT/GUIDELINE_PREFIX).iterdir()]
        paths+=['evidence/S17J02B03B/'+n for n in ['research.md','rights-decision.md','source-review.json','content-review.json']]
        for relative in paths:
            target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((PROJECT_ROOT/relative).read_bytes())
        self.registry=json.loads((self.root/GUIDELINE_PREFIX/'registry.json').read_text())
        self.item=self.registry['sources'][0]
        self.at=moment('2026-10-20T22:15:30+00:00')

    def save(self,path,obj):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

    def test_only_two_explicit_official_facts_admitted_without_originals(self):
        for item in self.registry['sources']:
            self.assertTrue(validate_primary(item,self.root))
            self.assertEqual(admission_reasons(item,self.at,evidence_root=self.root),[])
        originals={r['path']:r['document_type'] for r in self.registry['sources']}
        cards={r['artifact_path']:r['document_id'] for r in self.registry['sources']}
        manifest,blobs=build_manifest(self.root,self.registry,self.at.isoformat(),allowlist=originals,reference_allowlist=cards)
        self.assertEqual(len(blobs),2)
        path,_=publish_snapshot(self.root/'store',manifest,blobs)
        self.assertFalse(list(path.glob('*.pdf')))
        self.assertEqual(len(indexable_cards(path,self.registry,self.at.isoformat(),evidence_root=self.root)['cards']),2)

    def test_identity_type_url_and_storage_are_not_general_permissions(self):
        for field,value in [('document_id','KR999_1'),('source_url',self.item['source_url']+'&other=1'),('document_type','instrument_form'),('original_storage','verified_primary_receipt'),('representation','full_pdf'),('locator_kind','html_section')]:
            with self.subTest(field=field):
                item=copy.deepcopy(self.item);item[field]=value
                with self.assertRaises(CorpusError):validate_primary(item,self.root)

    def test_revoked_removed_and_cross_domain_pins_refused(self):
        original=json.loads((self.root/GUIDELINE_POLICY).read_text())
        for mutate in [lambda p:p['sources'][0].update(status='revoked'),lambda p:p['sources'].pop(0),lambda p:p['sources'].append(dict(p['sources'][0],document_id='DASS42_GUIDANCE'))]:
            pin=copy.deepcopy(original);mutate(pin);self.save(GUIDELINE_POLICY,pin)
            with self.assertRaises(CorpusError):validate_primary(self.item,self.root)
        self.save(GUIDELINE_POLICY,original)
        # The DASS policy is neither consulted nor changed by guideline admission.
        self.assertFalse((self.root/POLICY).exists())
        self.assertTrue(validate_primary(self.item,self.root))

    def test_tampered_receipt_report_and_artifact_withdraw_admission(self):
        for relative in [self.item['path'],'evidence/S17J02B03B/source-review.json']:
            original=(self.root/relative).read_bytes();(self.root/relative).write_bytes(original+b' ')
            self.assertTrue(admission_reasons(self.item,self.at,evidence_root=self.root))
            (self.root/relative).write_bytes(original)
        data=(self.root/self.item['artifact_path']).read_bytes()
        self.assertEqual(reference_reasons(self.item,data+b' '),['citation_review_mismatch'])

    def test_rehashed_unverified_TLS_report_still_rejected(self):
        item=copy.deepcopy(self.item);report_path=item['verification']['evidence'][0]
        report=json.loads((self.root/report_path).read_text());report['primary_sources'][item['document_id']]['tls_verified']=False
        self.save(report_path,report);rh=sha((self.root/report_path).read_bytes())
        item['verification']['evidence_sha256']=rh
        receipt=json.loads((self.root/item['path']).read_text());receipt['verification_sha256']=rh;self.save(item['path'],receipt)
        item['receipt_sha256']=sha((self.root/item['path']).read_bytes())
        pins=json.loads((self.root/GUIDELINE_POLICY).read_text());pins['sources'][0]['receipt_sha256']=item['receipt_sha256'];self.save(GUIDELINE_POLICY,pins)
        with self.assertRaisesRegex(CorpusError,'primary_acquisition_not_verified'):validate_primary(item,self.root)

    def test_guideline_cannot_inherit_DASS_resource_binding_or_quote(self):
        pins=json.loads((self.root/GUIDELINE_POLICY).read_text());pins['sources'][0]['resource_bindings']=[dict(path='apps/compass/resources/dass42-ru-v1.json',sha256='0'*64)];self.save(GUIDELINE_POLICY,pins)
        with self.assertRaisesRegex(CorpusError,'guideline_cannot_bind_instrument'):validate_primary(self.item,self.root)
        bundle=json.loads((self.root/self.item['artifact_path']).read_text());f=bundle['fragments'][0];f.update(claim_type='fact_with_quote',quote='Artificial quote')
        self.assertIn('primary_quotes_not_allowed',reference_reasons(self.item,json.dumps(bundle,ensure_ascii=False).encode()))

    def test_source_expiry_is_not_renewed_by_receipt(self):
        self.assertIn('review_expired_or_invalid',admission_reasons(self.item,moment(self.item['review_due_at']),evidence_root=self.root))


if __name__=='__main__':unittest.main()
