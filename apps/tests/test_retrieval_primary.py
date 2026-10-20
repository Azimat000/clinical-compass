"""Synthetic proof fixtures only; no network or medical/rights approval."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.compass.retrieval_corpus import (PROJECT_ROOT, CorpusError, digest, eligible_sources,
    indexable_cards, publish_snapshot, sha, reference_reasons)
from apps.compass.retrieval_primary import IDENTITIES, PREFIX, POLICY, STORAGE
from apps.tests.test_retrieval_packages import AT, save, policy, build


def make_primary(root):
    resource_path = 'apps/compass/resources/dass42-ru-v1.json'
    resource = (PROJECT_ROOT/resource_path).read_bytes()
    target=root/resource_path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(resource)
    report_path=PREFIX+'artificial-review.json'
    report={'primary_sources':{},'documents':{}}
    records=[]
    for doc,(kind,locator,urls) in IDENTITIES.items():
        source_sha=json.loads(resource)['source']['sha256'] if doc=='DASS42_RU_FORM' else sha(('ARTIFICIAL '+doc).encode())
        url=next(iter(urls));version='Artificial provenance fixture, not real source verification'
        fragment=dict(fragment_id=doc+'-F01',page=1 if locator=='pdf_page' else None,
            section='Artificial exact section',claim_type='fact',paraphrase='Artificial authored reference; not a clinical fact.',
            quote=None,required_context=[],purpose='Structural source-identity test',volume_justification='One artificial fact')
        bundle=dict(schema_version=1,representation='reviewed_cards',document_id=doc,source_sha256=source_sha,
            source_version=version,source_url=url,document_type=kind,attribution=dict(title='Artificial',authors='Artificial',source='Artificial',locator='Artificial'),fragments=[fragment])
        artifact=PREFIX+doc+'.cards.json';save(root,artifact,bundle);ah=sha((root/artifact).read_bytes())
        decision=dict(source_sha256=source_sha,artifact_sha256=ah,fragment_ids=[fragment['fragment_id']],
            quoted_characters=0,basis='GK1259_5_FACTS',text_and_context_verified=True)
        report['documents'][doc]=decision
        verified='2026-10-20T22:00:00+03:00'
        report['primary_sources'][doc]=dict(source_url=url,source_version=version,checked_at=verified,sha256=source_sha,
            byte_length=123,media_type='application/pdf' if locator=='pdf_page' else 'text/html',locator_kind=locator,
            verified=True,tls_verified=True,resource_match_verified=True,resource_sha256=sha(resource),fixture='ARTIFICIAL ONLY')
        item=dict(document_id=doc,document_family='DASS42',document_type=kind,source_url=url,source_version=version,
            sha256=source_sha,path=PREFIX+doc+'.receipt.json',artifact_path=artifact,artifact_sha256=ah,
            original_storage=STORAGE,locator_kind=locator,byte_length=123,media_type=report['primary_sources'][doc]['media_type'],
            status='approved',official_status='current',official_origin_verified=True,publisher='Artificial',
            admission_id='Artificial '+doc,decision_origin='Artificial isolated proof, not clinical evidence',
            population=dict(verified=True,text='Artificial source limitations',evidence=[report_path]),
            indications=dict(verified=True,text='Instrument reference only',evidence=[report_path]),
            verified_at=verified,review_due_at='2026-10-21T22:00:00+03:00',representation='reviewed_cards',
            rights=dict(status='verified',representation='reviewed_cards',scopes=['local_store','local_index','display_reference'],
                index_fields=['paraphrase'],evidence=[report_path],content_review=dict(decision,
                    purpose_and_volume_reviewed=True,attribution_reviewed=True,record_path=report_path)))
        records.append(item)
    save(root,report_path,report);rh=sha((root/report_path).read_bytes());pins=[]
    for item in records:
        item['rights']['evidence_sha256']={report_path:rh}
        item['verification']={k:item[k] for k in ['sha256','document_type','source_version','source_url','publisher']}
        item['verification'].update(checked_at=item['verified_at'],evidence=[report_path],evidence_sha256=rh)
        receipt=dict(schema_version=1,document_id=item['document_id'],source_url=item['source_url'],source_sha256=item['sha256'],
            source_version=item['source_version'],checked_at=item['verified_at'],byte_length=item['byte_length'],
            media_type=item['media_type'],locator_kind=item['locator_kind'],verification_path=report_path,verification_sha256=rh)
        save(root,item['path'],receipt);item['receipt_sha256']=sha((root/item['path']).read_bytes())
        keys=['document_id','document_type','source_url','source_version','sha256','artifact_path','artifact_sha256',
              'path','receipt_sha256','locator_kind','byte_length','media_type','verified_at']
        pin={k:item[k] for k in keys};pin['status']='approved'
        pin['resource_bindings']=[dict(path=resource_path,sha256=sha(resource))] if item['document_id'] in {'DASS42_RU_FORM','DASS42_EN_KEY'} else []
        pins.append(pin)
    save(root,POLICY,dict(schema_version=1,sources=pins))
    save(root,PREFIX+'registry.json',dict(schema_version=1,sources=records))
    return records


def rebind_reports(root, records):
    """Rehash synthetic proof layers, so negative tests reach semantic checks."""
    path=PREFIX+'artificial-review.json';rh=sha((root/path).read_bytes())
    pins=json.loads((root/POLICY).read_bytes())
    for item in records:
        item['verification']['evidence_sha256']=rh;item['rights']['evidence_sha256']={path:rh}
        receipt=json.loads((root/item['path']).read_bytes());receipt['verification_sha256']=rh;save(root,item['path'],receipt)
        item['receipt_sha256']=sha((root/item['path']).read_bytes())
        next(p for p in pins['sources'] if p['document_id']==item['document_id'])['receipt_sha256']=item['receipt_sha256']
    save(root,POLICY,pins);save(root,PREFIX+'registry.json',dict(schema_version=1,sources=records))


class PrimaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.records=make_primary(self.root);policy(self.root,['DASS42'])

    def publish(self):
        registry,manifest,blobs=build(self.root)
        return registry,manifest,publish_snapshot(self.root/'store',manifest,blobs)[0]

    def test_exact_six_receipts_export_only_authored_facts_without_network(self):
        with patch('socket.socket',side_effect=AssertionError('network forbidden')):
            registry,manifest,path=self.publish()
            self.assertEqual(len(indexable_cards(path,registry,AT,evidence_root=self.root)['cards']),6)
            self.assertEqual(len(list(path.glob('*.pdf'))),0)
            self.assertEqual(len(list(path.glob('*.receipt.json'))),0)
            self.assertFalse(publish_snapshot(self.root/'store',*build(self.root)[1:])[1])
            self.assertTrue(all(s['disposition']=='admitted' for s in manifest['sources']))

    def test_type_identity_url_storage_version_sha_and_artifact_are_pinned(self):
        original=deepcopy(self.records[0])
        for field,value in [('document_type','clinical_guideline'),('document_id','DASS21'),('source_url','https://dass.psy.unsw.edu.au/other.htm'),
            ('source_url',original['source_url']+'?download=1'),('source_version','wrong'),('sha256','0'*64),
            ('representation','full_pdf'),('original_storage','full_pdf'),('path',PREFIX+'other.json'),('artifact_sha256','0'*64)]:
            with self.subTest(field=field,value=value):
                records=deepcopy(self.records);records[0][field]=value
                save(self.root,PREFIX+'registry.json',dict(schema_version=1,sources=records))
                manifest=build(self.root)[1]
                self.assertEqual(manifest['sources'][0]['disposition'],'quarantined')
        save(self.root,PREFIX+'registry.json',dict(schema_version=1,sources=self.records))

    def test_tls_or_resource_match_not_verified_is_not_official_admission(self):
        path=PREFIX+'artificial-review.json';old=(self.root/path).read_bytes()
        for field,reason in [('tls_verified','primary_acquisition_not_verified'),('resource_match_verified','primary_resource_match_unverified')]:
            data=json.loads(old);data['primary_sources']['DASS42_RU_FORM'][field]=False;save(self.root,path,data)
            rebind_reports(self.root,self.records)
            source=self.publish()[1]['sources'][0]
            self.assertEqual(source['disposition'],'quarantined')
            self.assertTrue(any(reason in r for r in source['reasons']),source['reasons'])
        (self.root/path).write_bytes(old);rebind_reports(self.root,self.records)

    def test_receipt_report_local_form_and_policy_tamper_revoke_after_snapshot(self):
        registry,manifest,path=self.publish()
        for relative in [self.records[0]['path'],PREFIX+'artificial-review.json',POLICY,'apps/compass/resources/dass42-ru-v1.json']:
            with self.subTest(relative=relative):
                target=self.root/relative;old=target.read_bytes();target.write_bytes(old+b' ')
                result=eligible_sources(path,registry,AT,evidence_root=self.root)
                # JSON policy whitespace has no semantic change; pin revocation tested below.
                if relative!=POLICY:self.assertIn('DASS42_RU_FORM',result['refused'])
                target.write_bytes(old)
        data=json.loads((self.root/POLICY).read_bytes());data['sources'][0]['status']='revoked';save(self.root,POLICY,data)
        self.assertIn('DASS42_RU_FORM',eligible_sources(path,registry,AT,evidence_root=self.root)['refused'])

    def test_rights_expiry_and_removed_pin_fail_closed(self):
        registry,manifest,path=self.publish()
        revoked=deepcopy(registry);revoked['sources'][0]['rights']['status']='unknown'
        self.assertIn('DASS42_RU_FORM',eligible_sources(path,revoked,AT,evidence_root=self.root)['refused'])
        self.assertEqual(eligible_sources(path,registry,'2026-10-21T22:00:00+03:00',evidence_root=self.root)['admitted'],[])
        data=json.loads((self.root/POLICY).read_bytes());data['sources'].pop(0);save(self.root,POLICY,data)
        self.assertIn('DASS42_RU_FORM',eligible_sources(path,registry,AT,evidence_root=self.root)['refused'])

    def test_receipt_cannot_escape_registered_root_or_be_symlink(self):
        p=self.root/self.records[0]['path'];old=p.read_bytes();other=self.root/'outside.json';other.write_bytes(old)
        p.unlink();p.symlink_to(other)
        self.assertEqual(self.publish()[1]['sources'][0]['disposition'],'quarantined')

    def test_html_sections_have_no_invented_pdf_page_and_new_sources_no_quotes(self):
        item=next(r for r in self.records if r['document_id']=='DASS42_GUIDANCE')
        bundle=json.loads((self.root/item['artifact_path']).read_bytes())
        self.assertIsNone(bundle['fragments'][0]['page'])
        bundle['fragments'][0]['page']=1
        self.assertIn('citation_fragment_schema',reference_reasons(item,json.dumps(bundle).encode()))
        bundle=json.loads((self.root/item['artifact_path']).read_bytes());bundle['fragments'][0].update(claim_type='fact_with_quote',quote='not permitted')
        self.assertIn('primary_quotes_not_allowed',reference_reasons(item,json.dumps(bundle).encode()))

if __name__=='__main__':unittest.main()
