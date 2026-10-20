"""Evaluator tests use microfixtures, never retrieval on the frozen control set."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from evaluate_retrieval import (ROOT, SAFETY, evaluate, load_frozen, miniature,
                               self_test, validate_dataset)


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.predictions, self.fragments = miniature()
        self.cases[0]['expected']['sufficient_sets'] = [['a']]
        self.predictions[0]['hits'] = self.predictions[0]['hits'][:1]

    def result(self):
        return evaluate(self.cases, self.predictions, self.fragments)

    def test_perfect_microfixture_and_no_release_claim(self):
        r = self.result()
        self.assertTrue(r['passed'])
        self.assertFalse(r['release_approved'])
        self.assertIn('G07', r['not_measured'])
        self.assertEqual(r['overall']['answerable'], 1)
        self.assertEqual(r['overall']['required_refusals'], 1)

    def test_multipart_rank_is_completion_position(self):
        c, p, f = miniature()
        r = evaluate(c, p, f)
        self.assertEqual(r['cases'][0]['rank'], 2)
        self.assertEqual(r['overall']['mrr_at_5'], 0.5)
        self.assertFalse(r['gates']['G02'])

    def test_incomplete_multiset_is_not_relevant(self):
        self.cases[0]['expected']['sufficient_sets'] = [['a', 'b']]
        r = self.result()
        self.assertEqual(r['overall']['recall_at_5'], 0)
        self.assertEqual(r['cases'][0]['fn'], ['b'])
        self.assertFalse(r['gates']['G03'])

    def test_alternative_complete_set(self):
        self.cases[0]['expected']['sufficient_sets'] = [['a', 'b'], ['distractor']]
        self.predictions[0]['hits'] = [copy.deepcopy(self.fragments[2])]
        r = self.result()
        self.assertTrue(r['passed'])
        self.assertEqual(r['cases'][0]['fn'], [])

    def test_every_citation_field_is_checked(self):
        for field in self.fragments[0]:
            with self.subTest(field=field):
                c, p, f = miniature()
                p[0]['hits'][0][field] = 'tampered'
                self.assertFalse(evaluate(c, p, f)['gates']['G03'])

    def test_boolean_page_is_not_numeric_page(self):
        self.predictions[0]['hits'][0]['page'] = True
        self.assertFalse(self.result()['passed'])

    def test_late_wrong_citation_fails_despite_rank_one(self):
        self.predictions[0]['hits'] += [copy.deepcopy(self.fragments[2])]
        self.predictions[0]['hits'][-1]['page'] = 500
        r = self.result()
        self.assertEqual(r['overall']['recall_at_5'], 1)
        self.assertFalse(r['gates']['G02'])

    def test_wrong_refusal_reduces_recall(self):
        self.predictions[0].update(status='NO_EVIDENCE', reason_code='none', hits=[])
        r = self.result()
        self.assertEqual(r['overall']['recall_at_5'], 0)
        self.assertFalse(r['gates']['G03'])

    def test_correct_refusal_cannot_raise_recall(self):
        self.predictions[0]['hits'] = []
        r = self.result()
        self.assertEqual(r['overall']['correct_refusals'], 1)
        self.assertEqual(r['overall']['recall_at_5'], 0)

    def test_all_safety_effects_fail(self):
        for key in SAFETY:
            with self.subTest(key=key):
                c, p, f = miniature()
                p[0]['safety'][key] = True
                self.assertFalse(evaluate(c, p, f)['gates']['G03'])

    def test_leak_on_refusal(self):
        self.predictions[1]['hits'] = [copy.deepcopy(self.fragments[0])]
        self.assertFalse(self.result()['passed'])

    def test_unknown_source(self):
        self.predictions[0]['hits'][0]['fragment_id'] = 'not-admitted'
        self.assertFalse(self.result()['passed'])

    def test_missing_prediction(self):
        self.predictions.pop()
        self.assertFalse(self.result()['passed'])

    def test_duplicate_and_extra_prediction_rejected(self):
        for cid in ('mini-found', 'unknown'):
            extra = copy.deepcopy(self.predictions[0])
            extra['id'] = cid
            with self.assertRaises(ValueError):
                evaluate(self.cases, self.predictions + [extra], self.fragments)

    def test_duplicate_hit_fails(self):
        self.predictions[0]['hits'] *= 2
        self.assertFalse(self.result()['passed'])

    def test_unknown_payload_field_is_not_ignored(self):
        self.predictions[0]['medical_history'] = 'leak'
        self.assertFalse(self.result()['passed'])

    def test_versions_required(self):
        self.predictions[0]['versions']['corpus'] = 'old'
        r = self.result()
        self.assertFalse(r['passed'])
        self.assertEqual(r['overall']['recall_at_5'], 0)

    def test_empty_dataset_never_passes(self):
        self.assertFalse(evaluate([], [], self.fragments)['passed'])

    def test_refusals_only_not_a_ranking_pass(self):
        r = evaluate(self.cases[1:], self.predictions[1:], self.fragments)
        self.assertTrue(r['passed'])
        self.assertIsNone(r['gates']['G02'])
        self.assertFalse(r['rank_metrics_applicable'])

    def test_no_predictions_fails(self):
        self.assertFalse(evaluate(self.cases, [], self.fragments)['passed'])

    def test_self_test(self):
        self.assertEqual(self_test()['status'], 'PASS')

    def test_frozen_dataset_structure_and_negative_labels(self):
        parts, fragments, gates, _ = load_frozen(
            ROOT / 'data/synthetic/retrieval', ROOT / 'evidence/S17J01/dataset-manifest.json')
        docs = json.loads((ROOT / 'data/synthetic/retrieval/documents.json').read_text())
        for mutation, error in (
            (lambda p: p['control'][0].update(family=p['development'][0]['family']), 'family_overlap'),
            (lambda p: p['control'].__delitem__(slice(30, 60)), 'insufficient_cases'),
            (lambda p: p['control'][0]['expected'].update(sufficient_sets=[['missing']]), 'unknown_gold_fragment'),
            (lambda p: [c.update(categories=['depression']) for c in p['control']], 'category_coverage'),
        ):
            with self.subTest(error=error):
                changed = copy.deepcopy(parts)
                mutation(changed)
                self.assertTrue(any(error in e for e in validate_dataset(changed, docs, fragments, gates)))

    def test_manifest_hash_tampering_rejected(self):
        manifest = json.loads((ROOT / 'evidence/S17J01/dataset-manifest.json').read_text())
        manifest['frozen_files'][0]['sha256'] = '0'*64
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.json'
            p.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Frozen file changed'):
                load_frozen(ROOT / 'data/synthetic/retrieval', p)


if __name__ == '__main__':
    unittest.main(verbosity=2)
