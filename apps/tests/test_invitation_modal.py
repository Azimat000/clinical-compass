"""Invitation entry point keeps role boundaries and pending invitations private."""
import unittest
import test_access


class InvitationModalTests(unittest.TestCase):
    setUp = test_access.AccessTests.setUp
    tearDown = test_access.AccessTests.tearDown
    offer = test_access.AccessTests.offer

    def test_fallback_requires_doctor_and_does_not_create_invitation(self):
        self.assertEqual(302, self.app.test_client().get('/invitations/new').status_code)
        self.assertEqual(403, self.clients['pat-a'].get('/invitations/new').status_code)
        response = self.clients['doc-a'].get('/invitations/new')
        self.assertEqual(200, response.status_code)
        self.assertIn('action="/invitations"', response.text)
        self.assertNotIn('<dialog', response.text)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_invitations').fetchone()[0])

    def test_pending_invitations_are_only_shown_to_their_doctor(self):
        self.offer('doc-a', 'D01')
        self.offer('doc-b', 'D02')
        for uid, own, other in [('doc-a', 'D01', 'D02'), ('doc-b', 'D02', 'D01')]:
            for path in ('/', '/invitations/new'):
                text = self.clients[uid].get(path).text.split('id="invite-waiting-title"', 1)[1]
                self.assertIn('translate="no">' + own + '</span>', text)
                self.assertNotIn('translate="no">' + other + '</span>', text)


if __name__ == '__main__':
    unittest.main()
