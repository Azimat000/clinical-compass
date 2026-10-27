"""Independent mechanics; synthetic technical pass is never clinical release."""
from copy import deepcopy
from datetime import datetime,timedelta
import unittest
from apps.compass import backend_medication_regimens as safety
from apps.compass import backend_therapy_context as contexts

class RegimenTests(unittest.TestCase):
    def setUp(self):
        self.catalog=safety.release();self.at=datetime.fromisoformat('2026-10-27T14:00:00+03:00')
        self.patient={'mode':'synthetic_only','synthetic':True}
        for k in contexts.FLAGS:self.fact(k,False)
        for k,v in {'age':40,'allergies':[],'allergies_complete':True,'medications':[],
            'medications_complete':True,'response':'effective','tolerability':'good',
            'goal':'initiation','prior_first_line':'ineffective'}.items():self.fact(k,v)
        self.candidate={'product_id':'elicea','form':'film_coated_tablet','unit':'mg','strength_mg':10,
            'daily_dose_mg':10,'times_per_day':1,'indication':'adult_depression','phase':'initiation'}
    def fact(self,k,v):self.patient[k]={'value':v,'refs':['synthetic:physician:'+k]}
    def result(self):return safety.evaluate(self.candidate,self.patient,at=self.at)
    def gate(self,key):return next(c for c in self.result()['checks'] if c['code']==key)
    def med(self,**kw):
        c=self.candidate
        m=dict(product_id=c['product_id'],ingredient=self.catalog['products'][c['product_id']]['ingredient'],
            state='current',prescribed=True,actual=True,refs=['synthetic:physician:med'],
            **{k:c[k] for k in ('daily_dose_mg','strength_mg','times_per_day','unit','form')})
        m.update(kw);self.fact('medications',[m])
    def test_positive_start_each_product_has_complete_named_components(self):
        for pid,dose,strength,freq,indication in [('elicea',10,10,1,'adult_depression'),('aleval',50,50,1,'adult_depression'),('aviandr',40,20,2,'adult_gad')]:
            self.candidate.update(product_id=pid,daily_dose_mg=dose,strength_mg=strength,times_per_day=freq,indication=indication)
            r=self.result();self.assertEqual('pass',r['state'],r);self.assertTrue(r['synthetic_eligible'])
            self.assertFalse(r['eligible']);self.assertFalse(r['clinical_release']);self.assertFalse(r['applied'])
            self.assertEqual('unknown',r['release_gates']['registration_legal_status'])
            self.assertGreaterEqual(len(self.catalog['products'][pid]['excipients']),6)
            self.assertTrue(all(c['state']=='pass' for c in r['checks']))
            self.assertTrue(safety.verify(self.candidate,self.patient,r,at=self.at))
    def test_exact_continuation_differs_from_duplicate(self):
        self.candidate['phase']='maintenance';self.fact('goal','maintenance');self.med()
        self.assertTrue(self.result()['synthetic_eligible'])
        self.med(actual=False);self.assertEqual('block',self.result()['state'])
        self.med();m=deepcopy(self.patient['medications']['value']);self.fact('medications',m+m)
        self.assertEqual('block',self.result()['state'])
    def test_continuation_numeric_equivalence_and_wrong_actual_dose(self):
        self.candidate['phase']='maintenance';self.fact('goal','maintenance');self.med(daily_dose_mg=10.0)
        self.assertTrue(self.result()['synthetic_eligible'])
        self.med(daily_dose_mg=5);self.assertEqual('block',self.result()['state'])
    def test_unknowns_and_positive_conditions_never_clear(self):
        for pid in self.catalog['products']:
            self.candidate['product_id']=pid
            for key in self.catalog['products'][pid]['required_facts']:
                for value in (None,'conflicting',True):
                    self.fact(key,value);self.assertFalse(self.result()['synthetic_eligible'],(pid,key,value))
                self.fact(key,False)
    def test_all_excipients_are_checked_for_allergy(self):
        for pid,p in self.catalog['products'].items():
            self.candidate['product_id']=pid
            for code in p['excipients']:
                self.fact('allergies',[code]);self.assertEqual('block',self.gate('allergies')['state'])
        self.fact('allergies',[]);self.fact('allergies_complete',None)
        self.assertEqual('unknown',self.gate('allergies_complete')['state'])
    def test_maoi_pimozide_unknown_other_and_recent_stop(self):
        for code,state in [('irreversible_nonselective_maoi','block'),('pimozide','block'),('qt_prolonging_drug','block'),('unknown_drug','unknown')]:
            self.med(product_id=None,ingredient=code);self.assertEqual(state,self.gate('medication_0')['state'])
        self.med(state='recently_stopped');self.assertEqual('unknown',self.gate('medication_0')['state'])
    def test_initial_dose_not_top_of_range_and_phase_not_changed(self):
        self.candidate['daily_dose_mg']=20;self.assertEqual('block',self.gate('initial_dose')['state'])
        self.candidate['daily_dose_mg']=10
        for phase in ('change','stop','maintenance'):
            self.candidate['phase']=phase;self.fact('goal',phase)
            self.assertFalse(self.result()['synthetic_eligible'])
    def test_aviandr_not_universal_first_line_or_at_eighteen(self):
        self.candidate.update(product_id='aviandr',daily_dose_mg=40,strength_mg=20,times_per_day=2,indication='adult_gad')
        self.fact('prior_first_line','not_tried');self.assertEqual('unknown',self.gate('treatment_line')['state'])
        self.fact('prior_first_line','ineffective');self.fact('age',18)
        self.assertEqual('unknown',self.gate('age')['state'])
    def test_maintenance_requires_response_and_tolerance(self):
        self.candidate['phase']='maintenance';self.fact('goal','maintenance');self.med()
        for key,value in [('response','partial'),('response','none'),('response','unknown'),('tolerability','adverse'),('tolerability','unknown')]:
            self.fact(key,value);self.assertFalse(self.result()['synthetic_eligible'])
            self.fact(key,'effective' if key=='response' else 'good')
    def test_expiry_tampering_real_data_and_units(self):
        report=self.result();report['synthetic_eligible']=False
        with self.assertRaises(ValueError):safety.verify(self.candidate,self.patient,report,at=self.at)
        self.at+=timedelta(days=2);self.assertFalse(self.result()['synthetic_eligible'])
        self.at-=timedelta(days=2);self.patient['synthetic']=False
        self.assertEqual('block',self.result()['state'])
        self.patient['synthetic']=True
        for key,value in [('unit','ml'),('form','solution'),('strength_mg',True),('daily_dose_mg','10 мг')]:
            c=deepcopy(self.candidate);self.candidate[key]=value
            self.assertFalse(self.result()['synthetic_eligible']);self.candidate=c

if __name__=='__main__':unittest.main()
