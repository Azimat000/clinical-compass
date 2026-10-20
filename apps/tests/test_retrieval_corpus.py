"""Corpus lifecycle tests use artificial PDF bytes, never clinical assertions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from apps.compass.retrieval_corpus import (CorpusError,
    build_manifest, digest, eligible_sources as check_eligible_sources, load_snapshot, moment,
    publish_snapshot, sha)


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / 'original.pdf'
        self.original.write_bytes(b'%PDF-1.4\nartificial lifecycle fixture\n')
        self.allowlist = {'original.pdf': 'patient_leaflet'}
        self.at = '2026-10-20T12:00:00+03:00'
        self.item = dict(document_id='D1', document_family='F1', path='original.pdf',
            sha256=sha(self.original.read_bytes()), publisher='Test publisher',
            source_url='https://grls.rosminzdrav.ru/synthetic-fixture.pdf', source_version='v1',
            document_type='patient_leaflet', admission_id='A1', decision_origin='Test review',
            official_origin_verified=True, official_status='current', status='approved',
            population={'verified': True, 'text': 'Test adults', 'evidence': ['test']},
            indications={'verified': True, 'text': 'Test indication', 'evidence': ['test']},
            rights={'status': 'verified', 'scopes': ['local_store','local_index','display_excerpt'], 'evidence': ['test']},
            verified_at='2026-10-20T10:00:00+03:00', review_due_at='2026-10-21T10:00:00+03:00')
        self.item['verification'] = {k: self.item[k] for k in ('sha256','document_type','source_version','source_url','publisher')}
        (self.root / 'review.md').write_text('Artificial review evidence')
        self.item['verification'].update(checked_at=self.item['verified_at'],
            evidence=['review.md'], evidence_sha256=sha((self.root/'review.md').read_bytes()))
        self.registry = {'schema_version': 1, 'sources': [self.item]}

    def eligible_sources(self, path, registry, at):
        return check_eligible_sources(path, registry, at, evidence_root=self.root)

    def build(self, archive=False):
        return build_manifest(self.root, self.registry, self.at, archive=archive, allowlist=self.allowlist)

    def publish(self, archive=False):
        manifest, blobs = self.build(archive)
        path, _ = publish_snapshot(self.root / 'store', manifest, blobs)
        return path

    def test_changed_or_missing_review_blocks_snapshot(self):
        path = self.publish()
        (self.root/'review.md').write_text('Changed review')
        result = self.eligible_sources(path, self.registry, self.at)
        self.assertIn('verification_evidence_integrity', result['refused']['D1'])
        (self.root/'review.md').unlink()
        self.assert_quarantine('verification_evidence_integrity')

    def test_review_evidence_paths_fail_closed(self):
        for value in (['../review.md'], ['/etc/passwd'], ['https://example.test'], [{}], 'review.md', []):
            with self.subTest(value=value):
                self.item['verification']['evidence'] = value
                manifest, blobs = self.build()
                self.assertEqual(manifest['sources'][0]['disposition'], 'quarantined')
                self.assertFalse(blobs)

    def test_malformed_document_type_quarantined(self):
        self.item['document_type'] = {'unknown': 'type'}
        self.assert_quarantine('official_url_missing')

    def test_valid_import_and_repeat(self):
        manifest, blobs = self.build()
        path, created = publish_snapshot(self.root/'store', manifest, blobs)
        self.assertTrue(created)
        self.assertFalse(publish_snapshot(self.root/'store', manifest, blobs)[1])
        self.assertEqual(len(list((self.root/'store').iterdir())), 1)
        self.assertEqual(load_snapshot(path), manifest)
        self.assertEqual(self.eligible_sources(path,self.registry,self.at)['status'],'AVAILABLE')

    def test_later_repeat_before_expiry_same_version(self):
        first=self.build()[0]
        self.at='2026-10-20T14:00:00+03:00'
        self.assertEqual(first,self.build()[0])

    def test_malformed_rights_fail_closed(self):
        for scopes in (None,{},[{}],42):
            self.item['rights']['scopes']=scopes
            self.assert_quarantine('rights_unverified')

    def test_symlink_destination(self):
        (self.root/'actual').mkdir();(self.root/'link').symlink_to(self.root/'actual')
        manifest,blobs=self.build()
        with self.assertRaises(CorpusError):publish_snapshot(self.root/'link',manifest,blobs)

    def test_publish_rejects_version_traversal_before_write(self):
        manifest,blobs=self.build();manifest['corpus_version']='../escape'
        with self.assertRaises(CorpusError):publish_snapshot(self.root/'store',manifest,blobs)
        self.assertFalse((self.root/'store').exists())

    def test_publish_rejects_invalid_blob_before_write(self):
        manifest,blobs=self.build();blobs[self.item['sha256']]=b'wrong bytes'
        with self.assertRaises(CorpusError):publish_snapshot(self.root/'store',manifest,blobs)
        self.assertFalse((self.root/'store').exists())

    def test_archive_never_current(self):
        path = self.publish(archive=True)
        self.assertEqual(load_snapshot(path)['sources'][0]['disposition'],'archived')
        self.assertFalse(self.eligible_sources(path,self.registry,self.at)['admitted'])

    def test_archive_preserves_quarantined_original(self):
        self.item['rights']['status']='unknown'
        path=self.publish(archive=True)
        self.assertTrue((path/(self.item['sha256']+'.pdf')).is_file())
        self.assertIn('rights_unverified',load_snapshot(path)['sources'][0]['reasons'])
        self.assertFalse(self.eligible_sources(path,self.registry,self.at)['admitted'])

    def assert_quarantine(self, reason):
        manifest, blobs=self.build()
        self.assertEqual(manifest['sources'][0]['disposition'],'quarantined')
        self.assertIn(reason,manifest['sources'][0]['reasons'])
        self.assertFalse(blobs)

    def test_modified_bytes(self):
        self.original.write_bytes(b'%PDF-1.4\nreplacement')
        self.assert_quarantine('sha_mismatch')
        self.assertFalse(self.build(archive=True)[1])

    def test_wrong_type(self):
        self.item['document_type']='sm_p_c'
        self.assert_quarantine('document_type_mismatch')

    def test_pdf_header(self):
        self.original.write_bytes(b'not PDF')
        self.assert_quarantine('not_pdf')

    def test_rights_lost_after_import(self):
        path=self.publish()
        self.item['rights']['status']='revoked'
        result=self.eligible_sources(path,self.registry,self.at)
        self.assertFalse(result['admitted'])
        self.assertIn('rights_unverified',result['refused']['D1'])
        self.assertEqual(load_snapshot(path)['sources'][0]['disposition'],'admitted')

    def test_review_expiry_at_exact_boundary(self):
        path=self.publish()
        result=self.eligible_sources(path,self.registry,self.item['review_due_at'])
        self.assertIn('review_expired_or_invalid',result['refused']['D1'])

    def test_future_review(self):
        self.item['verified_at']='2026-10-20T13:00:00+03:00'
        self.assert_quarantine('review_expired_or_invalid')

    def test_revocation_and_official_status(self):
        for field,value,reason in [('status','revoked','admission_revoked'),('official_status','outdated','official_status_unverified')]:
            with self.subTest(field=field):
                old=self.item[field];self.item[field]=value
                self.assert_quarantine(reason);self.item[field]=old

    def test_lifecycle_all_metadata_rechecked(self):
        path=self.publish()
        original=deepcopy(self.registry)
        changes=[('status','revoked'),('status','archived'),('official_status','withdrawn'),
                 ('population',{'verified':False}),('indications',{}),
                 ('source_version','v2'),('verification',{}),('publisher','changed')]
        for field,value in changes:
            with self.subTest(field=field,value=value):
                current=deepcopy(original);current['sources'][0][field]=value
                self.assertFalse(self.eligible_sources(path,current,self.at)['admitted'])

    def test_removed_source(self):
        path=self.publish()
        other=deepcopy(self.item);other.update(document_id='D2',path='other.pdf',sha256='0'*64)
        self.assertIn('source_removed',self.eligible_sources(path,{'schema_version':1,'sources':[other]},self.at)['refused']['D1'])

    def test_all_sources_removed(self):
        path=self.publish()
        result=self.eligible_sources(path,{'schema_version':1,'sources':[]},self.at)
        self.assertEqual(result['status'],'NO_ADMITTED_SOURCE')
        self.assertIn('source_removed',result['refused']['D1'])

    def test_manufacturer_cannot_replace_official_grls(self):
        self.item['source_url']='https://sotex.ru/leaflet.pdf'
        self.item['verification']['source_url']=self.item['source_url']
        self.assert_quarantine('official_url_missing')

    def test_unknown_metadata(self):
        for field in ('publisher','source_version','admission_id','decision_origin'):
            with self.subTest(field=field):
                old=self.item.pop(field);self.assert_quarantine('metadata_missing:'+field);self.item[field]=old

    def test_rights_require_each_scope(self):
        for scope in list(self.item['rights']['scopes']):
            self.item['rights']['scopes'].remove(scope)
            self.assert_quarantine('rights_unverified')
            self.item['rights']['scopes'].append(scope)

    def test_proof_bound_to_bytes_type_and_version(self):
        for key in ('sha256','document_type','source_version','source_url','publisher'):
            with self.subTest(key=key):
                old=self.item['verification'][key];self.item['verification'][key]='different'
                self.assert_quarantine('verification_mismatch:'+key);self.item['verification'][key]=old

    def test_duplicate_id_with_changed_content(self):
        other=deepcopy(self.item);other['sha256']='0'*64;other['path']='different.pdf'
        self.registry['sources'].append(other)
        with self.assertRaisesRegex(CorpusError,'duplicate_source'):self.build()

    def test_duplicate_bytes_different_id(self):
        other=deepcopy(self.item);other['document_id']='D2';other['path']='different.pdf'
        self.registry['sources'].append(other)
        with self.assertRaisesRegex(CorpusError,'duplicate_source'):self.build()

    def test_path_traversal_and_url(self):
        for path in ('../original.pdf','/etc/passwd','https://example.test/doc.pdf'):
            self.item['path']=path;self.assert_quarantine('path_not_allowed')

    def test_symlink_source(self):
        self.original.rename(self.root/'real.pdf');self.original.symlink_to(self.root/'real.pdf')
        self.assert_quarantine('symlink_not_allowed')

    def test_missing_original(self):
        self.original.unlink();self.assert_quarantine('source_missing')

    def test_corrupt_stored_blob(self):
        path=self.publish();(path/(self.item['sha256']+'.pdf')).write_bytes(b'corrupt')
        with self.assertRaises(CorpusError):self.eligible_sources(path,self.registry,self.at)

    def test_corrupt_manifest(self):
        path=self.publish();p=path/'manifest.json';manifest=json.loads(p.read_text())
        manifest['sources'][0]['source']['source_version']='v2';p.write_text(json.dumps(manifest))
        with self.assertRaises(CorpusError):load_snapshot(path)

    def test_invalid_manifest_json_types_fail_closed(self):
        path = self.publish()
        for value in (None, [], 0, 'invalid'):
            (path/'manifest.json').write_text(json.dumps(value))
            with self.assertRaises(CorpusError):
                load_snapshot(path)

    def test_unknown_disposition_rejected_even_with_consistent_hash(self):
        manifest, blobs = self.build()
        manifest['sources'][0]['disposition'] = 'unknown'
        manifest['corpus_version'] = digest({k:v for k,v in manifest.items() if k != 'corpus_version'})
        with self.assertRaises(CorpusError):
            publish_snapshot(self.root/'store', manifest, blobs)

    def test_extra_blob_and_no_silent_overwrite(self):
        path=self.publish();(path/'extra.pdf').write_bytes(b'extra')
        manifest,blobs=self.build()
        with self.assertRaises(CorpusError):publish_snapshot(self.root/'store',manifest,blobs)

    def test_symlink_snapshot(self):
        path=self.publish();moved=path.with_name('moved');path.rename(moved);path.symlink_to(moved)
        with self.assertRaises(CorpusError):load_snapshot(path)

    def test_timezone_required(self):
        with self.assertRaises(CorpusError):moment('2026-10-20T10:00:00')

    def test_version_changes_with_policy_or_time(self):
        old=self.build()[0]['corpus_version']
        self.item['status']='quarantine'
        self.assertNotEqual(old,self.build()[0]['corpus_version'])

    def test_no_network_even_for_official_source_url(self):
        from unittest.mock import patch
        with patch('socket.socket',side_effect=AssertionError('network forbidden')):
            path=self.publish()
            self.assertEqual(self.eligible_sources(path,self.registry,self.at)['status'],'AVAILABLE')


if __name__ == '__main__':
    unittest.main()
