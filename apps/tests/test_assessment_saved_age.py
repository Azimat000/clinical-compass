"""S41: offer forms using recorded age, without redundant input fields."""
from datetime import date, timedelta
import json
import secrets
import unittest
from unittest.mock import patch
from apps.compass import assessments, records
import test_assessments as fixtures


class SavedAgeTests(unittest.TestCase):
    setUp = fixtures.AssessmentsTests.setUp
    tearDown = fixtures.AssessmentsTests.tearDown
    post = fixtures.AssessmentsTests.post
    answers = fixtures.AssessmentsTests.answers

    def offer(self, **extra):
        return self.post('doc-a', '/patients/D01/assessment-requests', {
            'assignment_key': secrets.token_hex(16), 'form_version_id': self.form['id'], **extra})

    def profile(self, status='known', years=35, birth=None):
        self.db.execute("UPDATE patients SET age_status=?,age_years=?,birth_date=?,created_at=? WHERE id='D01'",
                        (status, years, birth, records.today().isoformat()))

    def test_fields_absent_and_actual_form_submission_works_without_them(self):
        page = self.clients['doc-a'].get('/demo/D01').text
        for name in ('age_years', 'age_basis', 'age_status'):
            self.assertNotIn('name="' + name + '"', page)
        for label in ('Возраст, лет', 'Откуда возраст'):
            self.assertNotIn(label, page)
        self.assertEqual(303, self.offer().status_code)
        task = self.db.execute('SELECT * FROM assessment_requests').fetchone()
        snapshot = json.loads(task['age_snapshot_json'])
        self.assertIn('profile:D01', snapshot['saved_source_ids'])
        self.assertTrue(snapshot['possible_years'])
        self.assertEqual(303, self.post('pat-a', '/assessments/' + task['id'], self.answers()).status_code)

    def test_unknown_conflict_underage_and_invalid_saved_data_do_not_grant_access(self):
        for status,years,birth in [('unknown',None,None), ('conflicting',35,None),
                                   ('known',17,None), ('known',35,'broken')]:
            with self.subTest(status=status, years=years, birth=birth):
                self.profile(status,years,birth)
                self.assertEqual(409, self.offer().status_code)
        self.assertEqual(0,self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])

    def test_exact_birthday_is_calculated_from_saved_birthdate(self):
        with patch.object(records,'today',return_value=date(2026,10,24)):
            self.profile(years=None,birth='2008-10-25')
            self.assertEqual(409,self.offer().status_code)
        with patch.object(records,'today',return_value=date(2026,10,25)):
            self.assertEqual(303,self.offer().status_code)
            self.assertEqual(18,self.db.execute('SELECT age_years FROM assessment_requests').fetchone()[0])

    def test_uncertain_range_cannot_cross_form_age_boundary(self):
        phq = next(f for f in assessments.definitions() if f['code']=='PHQ-9')
        for years, form in [(17,self.form),(90,phq),(120,self.form)]:
            with self.subTest(years=years, form=form['code']):
                self.profile(years=years)
                self.db.execute("UPDATE patients SET created_at=? WHERE id='D01'",((records.today()-timedelta(days=1)).isoformat(),))
                self.assertEqual(409,self.offer(form_version_id=form['id']).status_code)

    def test_known_saved_record_works_with_unknown_profile_and_snapshot_changes_block_answer(self):
        self.profile('unknown',None)
        actor={'id':'doc-a','role':'doctor'}
        record={'request_key':secrets.token_hex(16),'observed_on':records.today().isoformat(),
                'age_status':'known','age_years':'35'}
        records.save(self.db,actor,'D01','visit',record)
        self.assertEqual(303,self.offer().status_code)
        task=self.db.execute('SELECT id FROM assessment_requests').fetchone()[0]
        records.save(self.db,actor,'D01','visit',{**record,'request_key':secrets.token_hex(16)})
        self.assertEqual(409,self.post('pat-a','/assessments/'+task,self.answers()).status_code)

    def test_retry_without_age_fields_preserves_one_request(self):
        key=secrets.token_hex(16)
        for _ in range(2):
            self.assertEqual(303,self.offer(assignment_key=key).status_code)
        self.assertEqual(1,self.db.execute('SELECT count(*) FROM assessment_requests').fetchone()[0])
