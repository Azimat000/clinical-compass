"""Documents are outside the product; old data stays intact."""
import unittest
import test_access
import test_decisions

class RemovedDocumentsTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_access.AccessTests.tearDown
    post = test_access.AccessTests.post
    offer = test_access.AccessTests.offer
    link = test_access.AccessTests.link

    def test_document_routes_are_not_registered(self):
        rules = {r.rule for r in self.app.url_map.iter_rules()}
        for route in ('/patients/<patient_id>/imports',
                      '/patients/<patient_id>/imports/<import_id>/review',
                      '/patients/<patient_id>/first-visits/<visit_id>/documents',
                      '/api/patients/<patient_id>/documents', '/api/documents/<document_id>'):
            self.assertNotIn(route, rules)
        before = [tuple(r) for r in self.db.execute('SELECT * FROM documents')]
        for who in ('doc-a', 'pat-a'):
            for path in ('/patients/D01/imports', '/api/patients/D01/documents', '/api/documents/doc1'):
                self.assertEqual(404, self.clients[who].get(path).status_code)
            self.assertEqual(404, self.post(who, '/patients/D01/imports', {'source_text':'must not save'}).status_code)
        self.assertEqual(before, [tuple(r) for r in self.db.execute('SELECT * FROM documents')])

    def test_cabinets_keep_working_without_document_links(self):
        for who in ('doc-a', 'pat-a'):
            for path in ('/', '/demo/D01', '/patients/D01/decisions', '/patients/D01/communication'):
                r = self.clients[who].get(path, follow_redirects=True)
                self.assertEqual(200, r.status_code)
                page = r.get_data(as_text=True)
                self.assertNotIn('>Документы<', page)
                self.assertNotIn('/imports', page)
        self.assertEqual(200, self.clients['doc-a'].get('/patients/D01/first-visits').status_code)
