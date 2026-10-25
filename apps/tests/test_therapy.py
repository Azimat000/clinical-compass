"""Source-backed physician review: uncertainty must survive the whole workflow."""
import json
import secrets
import unittest
from unittest.mock import patch
import test_decisions
from apps.compass import decisions


class TherapyTests(unittest.TestCase):
    setUp = test_decisions.DecisionTests.setUp
    tearDown = test_decisions.DecisionTests.tearDown
    post = test_decisions.DecisionTests.post
    offer = test_decisions.DecisionTests.offer
    link = test_decisions.DecisionTests.link
    values = test_decisions.DecisionTests.values
    draft = test_decisions.DecisionTests.draft
    confirm = test_decisions.DecisionTests.confirm

    def test_unknowns_saved_as_unknown_not_drug_clearance(self):
        p = self.draft()
        review = json.loads(p['payload_json'])['therapy_review']
        self.assertEqual(8, len(review['unresolved']))
        self.assertFalse(review['eligibility_established'])
        self.assertFalse(review['automatic_recommendation'])
        self.assertEqual('insufficient_data', review['conclusion'])
        # A physician may approve a manual plan to obtain missing data; no drug is generated.
        self.assertEqual(303, self.confirm(p).status_code)
        own = self.clients['doc-a'].get('/api/patients/D01/decisions').json['decisions'][0]
        patient = self.clients['pat-a'].get('/api/patients/D01/decisions').json['decisions'][0]
        self.assertEqual(review, own['payload']['therapy_review'])
        self.assertNotIn('therapy_review', patient['payload'])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM therapy_courses').fetchone()[0])

    def test_every_unknown_conflicting_or_concern_blocks_completed_review(self):
        full = {'review_' + a['id']: 'reviewed' for a in decisions.reference()['review_areas']}
        for area in decisions.reference()['review_areas']:
            for status in ('unknown', 'conflicting', 'concern'):
                with self.subTest(area=area['id'], status=status):
                    form = self.values(**{**full, 'review_' + area['id']: status,
                                          'aviandr_conclusion': 'individual_review'})
                    r = self.post('doc-a', '/patients/D01/decisions', form)
                    self.assertEqual(409, r.status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_full_physician_review_still_does_not_establish_suitability(self):
        fields = {'review_' + a['id']: 'reviewed' for a in decisions.reference()['review_areas']}
        p = self.draft(aviandr_conclusion='individual_review', **fields)
        review = json.loads(p['payload_json'])['therapy_review']
        self.assertFalse(review['eligibility_established'])
        self.assertEqual([], review['unresolved'])
        self.assertEqual([], review['concerns'])
        self.assertEqual(303, self.confirm(p).status_code)

    def test_negative_consideration_retains_specific_risk(self):
        p = self.draft(aviandr_conclusion='not_selected', review_contraindications='concern',
                       note_contraindications='Синтетика: указана эпилепсия; листок §2',
                       aviandr_basis='Авиандр не выбран: противопоказание в листке; нужен иной план врача.')
        review = json.loads(p['payload_json'])['therapy_review']
        self.assertIn('contraindications', review['concerns'])
        self.assertEqual(303, self.confirm(p).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM therapy_courses').fetchone()[0])

    def test_missing_version_notes_and_invalid_states_are_rejected(self):
        variants = ({'therapy_reference': ''}, {'therapy_reference': '2026-10-19.1'},
                    {'aviandr_conclusion': 'auto_approve'}, {'aviandr_basis': ''},
                    {'note_organs': ''}, {'note_organs': 'x'*1501},
                    {'review_interactions': 'compatible'}, {'note_adverse': 'bad\0note'})
        for fields in variants:
            with self.subTest(fields=str(fields)[:80]):
                r = self.post('doc-a', '/patients/D01/decisions', self.values(**fields))
                self.assertIn(r.status_code, (400, 409))
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])

    def test_retry_cannot_replace_review_and_source_change_invalidates_project(self):
        form = self.values()
        self.assertEqual(303, self.post('doc-a', '/patients/D01/decisions', form).status_code)
        self.assertEqual(409, self.post('doc-a', '/patients/D01/decisions',
                                       {**form, 'review_age': 'concern'}).status_code)
        p = self.db.execute('SELECT * FROM proposals').fetchone()
        updated = decisions.reference()
        updated['version'] = 'future-version'
        with patch.object(decisions, 'reference', return_value=updated):
            self.assertEqual(409, self.confirm(p).status_code)
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])

    def test_review_html_escapes_notes_and_preserves_error_values(self):
        p = self.draft(note_adverse='<script>synthetic()</script>')
        self.assertEqual(303, self.confirm(p).status_code)
        html = self.clients['doc-a'].get('/patients/D01/decisions').get_data(as_text=True)
        self.assertIn('&lt;script&gt;synthetic()&lt;/script&gt;', html)
        self.assertNotIn('<script>synthetic()', html)
        self.assertIn('review_indication', html)
        self.assertNotIn('#age-review', html)
        r = self.post('doc-a', '/patients/D01/decisions', self.values(note_age='Сохранить при ошибке', aviandr_basis=''))
        self.assertEqual(400, r.status_code)
        self.assertIn('Сохранить при ошибке', r.get_data(as_text=True))

    def test_each_synthetic_case_can_document_consideration_without_automatic_treatment(self):
        # Not a clinical oracle: exercise all seeded profiles without changing their source dataset.
        for i in range(1, 7):
            patient_id = f'D0{i}'
            if patient_id != 'D01':
                self.db.execute('INSERT INTO care_relationships(id,patient_id,doctor_id,starts_at) VALUES(?,?,?,?)',
                                (secrets.token_hex(16), patient_id, 'doc-a', '2026-01-01T00:00:00+00:00'))
            result = decisions.draft(self.db, {'id': 'doc-a', 'role': 'doctor'}, patient_id,
                                     self.values(aviandr_basis=f'{patient_id}: синтетика; недостаточно сведений, назначение не предложено.'))
            payload = json.loads(self.db.execute('SELECT payload_json FROM proposals WHERE id=?', (result,)).fetchone()[0])
            self.assertEqual('insufficient_data', payload['therapy_review']['conclusion'])
            self.assertFalse(payload['automatic'])
        self.assertEqual(6, self.db.execute('SELECT count(*) FROM proposals').fetchone()[0])
        self.assertEqual(0, self.db.execute('SELECT count(*) FROM care_actions').fetchone()[0])
