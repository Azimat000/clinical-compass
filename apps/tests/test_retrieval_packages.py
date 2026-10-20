"""Synthetic local packages; no clinical facts or genuine registrations."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.compass.retrieval_corpus import (CorpusError, build_manifest, digest,
    eligible_sources, indexable_cards, load_snapshot, publish_snapshot, sha)
from apps.compass.retrieval_packages import package_registry

AT = '2026-10-20T23:40:00+03:00'


def save(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def artificial_package(root, pid='NEW', count=1, official_host='grls.rosminzdrav.ru'):
    prefix = 'data/retrieval/packages/' + pid
    records = []
    for n in range(count):
        doc = pid + str(n)
        source = prefix + '/' + doc + '.pdf'
        artifact = prefix + '/' + doc + '.json'
        review_path = prefix + '/' + doc + '-review.json'
        source_data = ('%PDF-1.4\nARTIFICIAL source ' + doc).encode()
        (root / prefix).mkdir(parents=True, exist_ok=True)
        (root / source).write_bytes(source_data)
        bundle = dict(schema_version=1, representation='reviewed_cards', document_id=doc,
            source_sha256=sha(source_data), source_version='artificial-v1',
            source_url='https://' + official_host + '/artificial-' + doc + '.pdf',
            document_type='medication_instruction',
            attribution=dict(title='Artificial test', authors='Test author', source='Test fixture', locator='p1'),
            fragments=[dict(fragment_id=doc+'-F1', page=1, section='Artificial section', claim_type='fact',
                paraphrase='Artificial independently authored fact ' + doc, quote=None,
                required_context=[], purpose='Technical test', volume_justification='Artificial test only')])
        save(root, artifact, bundle)
        artifact_hash = sha((root / artifact).read_bytes())
        decision = dict(source_sha256=sha(source_data), artifact_sha256=artifact_hash,
                        fragment_ids=[doc+'-F1'], quoted_characters=0,
                        basis='GK1259_5_FACTS', text_and_context_verified=True)
        save(root, review_path, {'documents': {doc: decision}, 'notice': 'Artificial approval, not legal or clinical evidence'})
        report_hash = sha((root / review_path).read_bytes())
        item = dict(document_id=doc, document_family='Artificial', path=source, sha256=sha(source_data),
            artifact_path=artifact, artifact_sha256=artifact_hash, representation='reviewed_cards',
            publisher='Artificial publisher', source_url=bundle['source_url'], source_version='artificial-v1',
            document_type='medication_instruction', status='approved', admission_id='TEST-'+doc,
            decision_origin='Artificial lifecycle fixture', official_origin_verified=True, official_status='current',
            population=dict(verified=True,text='Test adults',evidence=[review_path]),
            indications=dict(verified=True,text='Artificial indication',evidence=[review_path]),
            verified_at='2026-10-20T22:00:00+03:00',review_due_at='2026-10-21T22:00:00+03:00',
            rights=dict(status='verified',representation='reviewed_cards',scopes=['local_store','local_index','display_reference'],
                index_fields=['paraphrase'],evidence=[review_path],evidence_sha256={review_path:report_hash},
                content_review=dict(decision,purpose_and_volume_reviewed=True,attribution_reviewed=True,record_path=review_path)))
        item['verification'] = {k:item[k] for k in ('sha256','document_type','source_version','source_url','publisher')}
        item['verification'].update(checked_at=item['verified_at'],evidence=[review_path],evidence_sha256=report_hash)
        records.append(item)
    save(root,prefix+'/registry.json',dict(schema_version=1,sources=records))
    return records


def policy(root, pids):
    save(root,'data/retrieval/admission-packages.json',dict(schema_version=1,enabled=pids,
        packages=[dict(id=pid,root='data/retrieval/packages/'+pid,
                       registry='data/retrieval/packages/'+pid+'/registry.json') for pid in pids]))


def build(root, at=AT):
    registry, originals, cards = package_registry(root)
    manifest, blobs = build_manifest(root,registry,at,allowlist=originals,reference_allowlist=cards)
    return registry, manifest, blobs


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records = artificial_package(self.root, count=4)
        policy(self.root,['NEW'])

    def publish(self):
        registry, manifest, blobs = build(self.root)
        path, created = publish_snapshot(self.root/'store',manifest,blobs)
        return registry,manifest,path,created

    def test_four_new_sources_repeat_and_no_network(self):
        with patch('socket.socket',side_effect=AssertionError('network forbidden')):
            registry,manifest,path,created = self.publish()
            self.assertTrue(created)
            self.assertEqual(len(indexable_cards(path,registry,AT,evidence_root=self.root)['cards']),4)
            self.assertEqual(len(list(path.glob('*.pdf'))),0)
            self.assertFalse(publish_snapshot(self.root/'store',*build(self.root)[1:])[1])
            self.assertEqual(load_snapshot(path),manifest)

    def test_two_registered_packages_and_unregistered_rejection(self):
        artificial_package(self.root,'NEXT',2); policy(self.root,['NEW','NEXT'])
        self.assertEqual(len(build(self.root)[1]['sources']),6)
        for pid in ['MISSING','../NEW','https://example.test','/etc/passwd']:
            with self.subTest(pid=pid),self.assertRaises(CorpusError):package_registry(self.root,[pid])

    def test_official_GRLS_gov_host_keeps_full_admission_checks(self):
        artificial_package(self.root,'GOV',official_host='grls.rosminzdrav.gov.ru');policy(self.root,['GOV'])
        registry,manifest,path,_=self.publish()
        self.assertEqual(len(indexable_cards(path,registry,AT,evidence_root=self.root)['cards']),1)
        item=registry['sources'][0];item['rights']['status']='unknown'
        save(self.root,'data/retrieval/packages/GOV/registry.json',dict(schema_version=1,sources=[item]))
        self.assertEqual(build(self.root)[1]['sources'][0]['disposition'],'quarantined')

    def test_package_root_and_path_escape_rejected(self):
        path=self.root/'data/retrieval/admission-packages.json'
        original=path.read_bytes(); value=json.loads(original)
        for target in ['.', 'data/retrieval', '/etc', 'data/retrieval/packages/NEW/..']:
            value['packages'][0]['root']=target;path.write_text(json.dumps(value))
            with self.assertRaises(CorpusError):package_registry(self.root)
        path.write_bytes(original)
        reg=self.root/'data/retrieval/packages/NEW/registry.json'; value=json.loads(reg.read_bytes())
        for target in ['../outside.pdf','/etc/passwd','data/retrieval/packages/NEXT/a.pdf']:
            value['sources'][0]['path']=target;reg.write_text(json.dumps(value))
            with self.assertRaises(CorpusError):package_registry(self.root)

    def test_unknown_rights_quarantine_without_damage_to_old_snapshot(self):
        registry,manifest,old,_=self.publish(); original={p.name:sha(p.read_bytes()) for p in old.iterdir()}
        regpath='data/retrieval/packages/NEW/registry.json'
        self.records[0]['rights']['status']='unknown';save(self.root,regpath,dict(schema_version=1,sources=self.records))
        registry,new,blobs=build(self.root)
        self.assertEqual(new['sources'][0]['disposition'],'quarantined')
        self.assertNotIn(self.records[0]['artifact_sha256'],blobs)
        self.assertIn('rights_unverified',eligible_sources(old,registry,AT,evidence_root=self.root)['refused']['NEW0'])
        publish_snapshot(self.root/'store',new,blobs)
        self.assertEqual(original,{p.name:sha(p.read_bytes()) for p in old.iterdir()})
        self.assertEqual(load_snapshot(old),manifest)

    def test_tampered_missing_and_symlink_package_files(self):
        item=self.records[0]; path=self.root/item['artifact_path']; original=path.read_bytes()
        path.write_text('{}');self.assertEqual(build(self.root)[1]['sources'][0]['disposition'],'quarantined')
        path.unlink();self.assertEqual(build(self.root)[1]['sources'][0]['disposition'],'quarantined')
        target=self.root/'outside.json';target.write_bytes(original);path.symlink_to(target)
        self.assertIn('symlink_not_allowed',build(self.root)[1]['sources'][0]['reasons'])

    def test_symlink_registry_rejected(self):
        path=self.root/'data/retrieval/packages/NEW/registry.json';target=self.root/'other.json'
        path.rename(target);path.symlink_to(target)
        with self.assertRaises(CorpusError):package_registry(self.root)

    def test_review_and_expiry_not_bypassed_by_registration(self):
        for field in ['rights','verification']:
            path=self.root/self.records[0][field]['evidence'][0]
            before=path.read_bytes();path.write_text('changed evidence')
            self.assertEqual(build(self.root)[1]['sources'][0]['disposition'],'quarantined');path.write_bytes(before)
        self.assertTrue(all(s['disposition']=='quarantined' for s in build(self.root,'2026-10-22T00:00:00+03:00')[1]['sources']))

    def test_failure_in_staging_never_exposes_partial_version(self):
        registry,manifest,old,_=self.publish(); before=load_snapshot(old)
        artificial_package(self.root,'NEXT');policy(self.root,['NEW','NEXT'])
        _,new,blobs=build(self.root)
        with patch('apps.compass.retrieval_corpus.os.rename',side_effect=OSError('simulated disk error')):
            with self.assertRaises(OSError):publish_snapshot(self.root/'store',new,blobs)
        self.assertFalse((self.root/'store'/new['corpus_version']).exists())
        self.assertFalse(list((self.root/'store').glob('.building-*')))
        self.assertEqual(load_snapshot(old),before)

    def test_fact_collection_larger_than_initial_five_with_new_review(self):
        item=self.records[0];bundle=json.loads((self.root/item['artifact_path']).read_text())
        bundle['fragments']=[dict(bundle['fragments'][0],fragment_id='NEW0-F'+str(i)) for i in range(8)]
        save(self.root,item['artifact_path'],bundle);item['artifact_sha256']=sha((self.root/item['artifact_path']).read_bytes())
        review=item['rights']['content_review'];review['artifact_sha256']=item['artifact_sha256'];review['fragment_ids']=[f['fragment_id'] for f in bundle['fragments']]
        decision={k:review[k] for k in ['artifact_sha256','fragment_ids','quoted_characters','basis']}
        decision.update(source_sha256=item['sha256'],text_and_context_verified=True)
        save(self.root,review['record_path'],{'documents':{item['document_id']:decision}})
        h=sha((self.root/review['record_path']).read_bytes());item['verification']['evidence_sha256']=h
        item['rights']['evidence_sha256'][review['record_path']]=h
        save(self.root,'data/retrieval/packages/NEW/registry.json',dict(schema_version=1,sources=self.records))
        registry,_,path,_=self.publish()
        self.assertEqual(len(indexable_cards(path,registry,AT,evidence_root=self.root)['cards']),11)

    def replacement(self):
        previous=self.records[0];item=deepcopy(previous)
        prefix='data/retrieval/packages/REVISED'
        item['artifact_path']=prefix+'/updated.json'
        bundle=json.loads((self.root/previous['artifact_path']).read_text())
        bundle['fragments'][0]['paraphrase']='A newly reviewed artificial fact.'
        save(self.root,item['artifact_path'],bundle)
        item['artifact_sha256']=sha((self.root/item['artifact_path']).read_bytes())
        review=item['rights']['content_review'];review['artifact_sha256']=item['artifact_sha256']
        review['record_path']=prefix+'/review.json'
        decision={k:review[k] for k in ['artifact_sha256','fragment_ids','quoted_characters','basis']}
        decision.update(source_sha256=item['sha256'],text_and_context_verified=True)
        save(self.root,review['record_path'],{'documents':{item['document_id']:decision}})
        h=sha((self.root/review['record_path']).read_bytes())
        item['rights']['evidence']=[review['record_path']];item['rights']['evidence_sha256']={review['record_path']:h}
        item['verification'].update(evidence=[review['record_path']],evidence_sha256=h)
        save(self.root,prefix+'/registry.json',dict(schema_version=1,sources=[item]))
        policy(self.root,['NEW','REVISED'])
        path='data/retrieval/admission-packages.json';config=json.loads((self.root/path).read_text())
        config['packages'][1]['replaces']={item['document_id']:digest(previous)}
        save(self.root,path,config)
        return item,config

    def test_explicit_replacement_reuses_original_and_preserves_other_sources(self):
        registry,manifest,old,_=self.publish();old_bytes={p.name:sha(p.read_bytes()) for p in old.iterdir()}
        item,config=self.replacement()
        current,new,blobs=build(self.root)
        self.assertEqual(len(current['sources']),4)
        self.assertEqual(current['sources'][0]['artifact_sha256'],item['artifact_sha256'])
        self.assertEqual(current['sources'][1:],self.records[1:])
        self.assertEqual(current['sources'][0]['path'],self.records[0]['path'])
        self.assertFalse(list((self.root/'data/retrieval/packages/REVISED').glob('*.pdf')))
        from apps.compass.retrieval_packages import package_registry
        self.assertEqual(digest(current),digest(package_registry(self.root,['REVISED','NEW'])[0]))
        publish_snapshot(self.root/'store',new,blobs)
        self.assertEqual(old_bytes,{p.name:sha(p.read_bytes()) for p in old.iterdir()})
        self.assertIn('NEW0',eligible_sources(old,current,AT,evidence_root=self.root)['refused'])

    def test_implicit_or_stale_replacement_is_rejected(self):
        item,config=self.replacement()
        path='data/retrieval/admission-packages.json'
        for replacement in [{},{item['document_id']:'0'*64}]:
            config['packages'][1]['replaces']=replacement;save(self.root,path,config)
            with self.assertRaises(CorpusError):build(self.root)

    def test_bad_replacement_quarantines_without_old_source_fallback(self):
        item,config=self.replacement();item['rights']['status']='unknown'
        save(self.root,'data/retrieval/packages/REVISED/registry.json',dict(schema_version=1,sources=[item]))
        current,manifest,blobs=build(self.root)
        entry=next(e for e in manifest['sources'] if e['document_id']==item['document_id'])
        self.assertEqual(entry['disposition'],'quarantined')
        self.assertNotIn(item['artifact_sha256'],blobs)
        self.assertNotIn(self.records[0]['artifact_sha256'],blobs)
        self.assertEqual(sum(e['disposition']=='admitted' for e in manifest['sources']),3)


if __name__ == '__main__':unittest.main()
