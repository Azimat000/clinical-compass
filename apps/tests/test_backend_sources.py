"""BE03: real files/SQLite/HTTP, explicit isolated metadata fixtures, no clinician."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from apps.compass import backend_sources as sources, backend_analyses as analyses
from apps.compass.retrieval_corpus import digest, sha
from apps.tests import test_access, test_backend_contracts


class SourceCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.at = datetime(2026, 10, 26, 17, tzinfo=timezone.utc)
        self.catalog = json.loads((sources.ROOT / sources.CATALOG).read_text())
        registry = json.loads((sources.ROOT / sources.REGISTRY).read_text())
        registry['sources'] = [i for i in registry['sources'] if i['document_id'] in {'KR301_3', 'KR457_3'}]
        # Test-only administrator metadata. Real originals/cards/rights evidence
        # stay byte-exact. These dates/statuses are NEVER applied to project data.
        self.registry = registry
        paths = {sources.CATALOG, sources.REGISTRY}
        for item, pin in zip(registry['sources'], self.catalog['sources']):
            pin = next(p for p in self.catalog['sources'] if p['id'] == item['document_id'])
            item['verified_at'] = item['verification']['checked_at'] = '2026-10-26T00:00:00+00:00'
            item['review_due_at'] = '2026-10-28T00:00:00+00:00'
            pin['registry_sha256'] = digest(item)
            pin['verification']['current_status'] = 'current'
            paths.update([item['path'], item['artifact_path'], pin['verification']['path']])
            paths.update(item['rights']['evidence'])
            paths.update(item['verification']['evidence'])
        for relative in paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sources.ROOT / relative, destination)
        self.save()

    def save(self):
        (self.root / sources.CATALOG).write_text(json.dumps(self.catalog))
        (self.root / sources.REGISTRY).write_text(json.dumps(self.registry))

    def capture(self):
        return sources.capture(root=self.root, at=self.at)

    def require(self, report, cid=None, **kw):
        cid = cid or self.catalog['claims'][0]['id']
        claim = report['claims'][cid]
        return sources.require(report, [cid], claim['binding']['operation'],
                               **{'age_min': 35, 'age_max': 35, 'condition': 'F32', **kw})

    def test_limited_real_catalog_has_three_operations_and_exact_primary_bindings(self):
        report = sources.capture(at=self.at)
        self.assertEqual({'risk', 'diagnosis', 'plan'}, {c['binding']['operation'] for c in report['claims'].values()})
        self.assertEqual(2, len(report['sources']))
        self.assertEqual(6, len(sources.references(report)))
        self.assertRegex(report['engine_sha256'], r'^[0-9a-f]{64}$')
        for entry in report['sources'].values():
            self.assertIn('api.ashx?id=', entry['source']['source_url'])
            self.assertEqual([], entry['reasons'])
            self.assertEqual('2026-10-21T22:32:00+03:00', entry['source']['review_due_at'])
        for c in report['claims'].values():
            self.assertGreater(c['binding']['page'], 0)
            self.assertTrue(c['binding']['section'])
            self.assertEqual(c['binding']['text_sha256'], sha(c['text'].encode()))
        self.assertIsNone(self.require(report))
        expired = sources.capture(at=datetime(2026, 10, 28, tzinfo=timezone.utc))
        with self.assertRaises(sources.SourceError):
            self.require(expired)

    def test_valid_source_fixture_allows_exact_binding_for_each_operation(self):
        report = self.capture()
        self.assertTrue(all(not e['reasons'] for e in report['sources'].values()), report)
        for cid, claim in report['claims'].items():
            condition = 'F41.1' if claim['binding']['source_id'] == 'KR457_3' else 'F32'
            self.require(report, cid, condition=condition)
        self.assertEqual(report, self.capture())

    def test_removed_changed_pdf_cards_rights_and_proof_block(self):
        pin = self.catalog['sources'][0]
        item = next(i for i in self.registry['sources'] if i['document_id'] == pin['id'])
        for relative in [item['path'], item['artifact_path'], item['rights']['evidence'][0],
                         item['verification']['evidence'][0], pin['verification']['path']]:
            p = self.root / relative
            original = p.read_bytes()
            with self.subTest(path=relative, change='missing'):
                p.unlink()
                with self.assertRaises(sources.SourceError): self.require(self.capture())
            p.write_bytes(original + b' ')
            with self.subTest(path=relative, change='changed'):
                with self.assertRaises(sources.SourceError): self.require(self.capture())
            p.write_bytes(original)
        self.assertIsNone(self.require(self.capture()))

    def test_revocation_replacement_removal_expiry_future_and_unknown_status(self):
        original_c, original_r = deepcopy(self.catalog), deepcopy(self.registry)
        actions = [lambda: self.catalog['sources'][0].update(status='revoked'),
                   lambda: self.catalog['sources'][0]['verification'].update(current_status='withdrawn'),
                   lambda: self.catalog['sources'][0]['verification'].update(current_status='unknown'),
                   lambda: self.catalog['sources'][0]['verification'].update(review_due_at='2026-10-26T00:00:00+00:00'),
                   lambda: self.catalog['sources'][0]['verification'].update(checked_at='2026-10-27T00:00:00+00:00'),
                   lambda: self.registry['sources'].pop(0),
                   lambda: self.registry['sources'][0].update(source_version='replacement'),
                   lambda: self.registry['sources'][0].update(status='superseded')]
        for action in actions:
            self.catalog, self.registry = deepcopy(original_c), deepcopy(original_r)
            action(); self.save()
            with self.assertRaises(sources.SourceError): self.require(self.capture())
        self.catalog, self.registry = original_c, original_r
        self.save()
        report = sources.capture(root=self.root, at=datetime(2026, 10, 29, tzinfo=timezone.utc))
        with self.assertRaises(sources.SourceError): self.require(report)

    def test_claim_content_page_operation_population_indication_and_unknowns(self):
        report = self.capture()
        for context in [{'age_min': None}, {'age_min': 17}, {'age_max': 121},
                        {'age_min': True}, {'age_min': 40, 'age_max': 35},
                        {'condition': None}, {'condition': 'F99'}, {'mode': 'clinical'}]:
            with self.subTest(context=context), self.assertRaises(sources.SourceError):
                self.require(report, **context)
        cid = self.catalog['claims'][0]['id']
        for ids, op in [([], 'risk'), (['forged'], 'risk'), ([cid], 'risk')]:
            with self.assertRaises(sources.SourceError):
                sources.require(report, ids, op, age_min=35, age_max=35, condition='F32')
        for key, value in [('text_sha256', '0'*64), ('page', 999), ('section', 'invented')]:
            original = self.catalog['claims'][0][key]
            self.catalog['claims'][0][key] = value; self.save()
            with self.assertRaises(sources.SourceError): self.require(self.capture())
            self.catalog['claims'][0][key] = original

    def test_no_review_author_or_signature_can_enable_clinical_release(self):
        for change in [{'mode': 'clinical'}, {'clinical_review': {'reviewed_by': 'Invented physician'}},
                       {'reviewed_by': 'Invented'}, {'signature': 'fake'}]:
            original = deepcopy(self.catalog)
            self.catalog.update(change); self.save()
            with self.assertRaises(sources.SourceError): self.capture()
            self.catalog = original
        self.catalog['claims'] = []; self.save()
        with self.assertRaises(sources.SourceError): self.capture()

    def test_exact_result_link_and_changed_snapshot_checked_again_at_use(self):
        report = self.capture()
        cid = self.catalog['claims'][0]['id']
        result = {'output': {'leading': {'text': report['claims'][cid]['text'], 'source_ids': [cid]}, 'alternatives': []}}
        with patch.object(sources, 'clock', return_value=self.at):
            sources.check_result(report, 'diagnosis', result, root=self.root,
                                 context={'age_min':35, 'age_max':35, 'condition':'F32'})
            with self.assertRaises(sources.SourceError):
                sources.check_result(report, 'diagnosis', result, root=self.root)
            result['output']['leading']['text'] += ' forged recommendation'
            with self.assertRaises(sources.SourceError):
                sources.check_result(report, 'diagnosis', result, root=self.root,
                                     context={'age_min':35,'age_max':35,'condition':'F32'})
            self.catalog['sources'][0]['status'] = 'revoked'; self.save()
            with self.assertRaises(sources.SourceError):
                sources.check_result(report, 'diagnosis', result, root=self.root)
        self.assertNotEqual(report, self.capture())
        self.assertEqual('registered', report['sources']['KR301_3']['pin']['status'])


class SourceBoundaryTests(unittest.TestCase):
    setUp = test_backend_contracts.BackendContractTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    body = test_backend_contracts.BackendContractTests.body
    start = test_backend_contracts.BackendContractTests.start
    result = test_backend_contracts.BackendContractTests.result
    ready = test_backend_contracts.BackendContractTests.ready

    def test_sqlite_ready_boundary_blocks_unregistered_and_unverified_claims(self):
        for operation in ['risk', 'diagnosis', 'plan']:
            # BE01 format-only diagnosis fixture lets the plan reach its real
            # source gate, instead of failing earlier for missing diagnosis.
            diagnosis = self.ready('diagnosis')['run_id'] if operation == 'plan' else None
            run = self.start(operation)
            result = self.result(operation, diagnosis)
            with self.assertRaises(analyses.AnalysisError) as caught:
                analyses.advance(self.db,self.user,'D01',run['run_id'],2,'ready',result=result)
            self.assertEqual('source_unavailable', caught.exception.code)
            self.assertEqual(2, analyses._latest(self.db, run['run_id'])['revision'])
            cid = next(c['id'] for c in json.loads((sources.ROOT/sources.CATALOG).read_text())['claims'] if c['operation']==operation)
            output = result['output']
            finding = output['patterns'][0] if operation=='risk' else output['leading'] if operation=='diagnosis' else output['items'][0]
            finding['source_ids'] = [cid]
            finding['text'] = sources.capture()['claims'][cid]['text']
            with self.assertRaises(analyses.AnalysisError):
                analyses.advance(self.db,self.user,'D01',run['run_id'],2,'ready',result=result)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_real_http_missing_catalog_safe_error_and_revocation_stale_history_frozen(self):
        client = self.clients['doc-a']
        response = client.post('/api/v1/patients/D01/analyses', json=self.body(),
                               headers={'X-CSRF-Token':test_access.csrf(client)})
        self.assertEqual(202,response.status_code)
        run = response.json
        saved = self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(run['snapshot_id'],)).fetchone()[0]
        with patch.object(sources,'CATALOG','data/backend/missing.json'):
            stale = client.get(response.headers['Location'])
            self.assertEqual(200,stale.status_code)
            self.assertEqual('stale',stale.json['status'])
            failed = client.post('/api/v1/patients/D01/analyses',json=self.body(),
                                 headers={'X-CSRF-Token':test_access.csrf(client)})
            self.assertEqual(409,failed.status_code)
            self.assertEqual('source_unavailable',failed.json['error'])
        self.assertEqual(saved,self.db.execute('SELECT payload_json FROM analysis_input_snapshots WHERE id=?',(run['snapshot_id'],)).fetchone()[0])
        self.assertEqual('queued',analyses._latest(self.db,run['run_id'])['status'])
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0])

    def test_no_pattern_cannot_bypass_source_and_unimplemented_rule_checks(self):
        run = self.start()
        result = self.result()
        result['output'] = {'assessment': 'no_pattern_found', 'patterns': []}
        with self.assertRaises(analyses.AnalysisError) as caught:
            analyses.advance(self.db, self.user, 'D01', run['run_id'], 2, 'ready', result=result)
        self.assertEqual('source_unavailable', caught.exception.code)
        self.assertIn('negative_risk_rule_not_implemented', str(caught.exception))
        self.assertEqual(2, analyses._latest(self.db, run['run_id'])['revision'])
