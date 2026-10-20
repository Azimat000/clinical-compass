"""Two-origin evidence tests: artificial attestations are never clinical truth."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from apps.tests.test_retrieval_packages import AT, save
from apps.compass.retrieval_corpus import CorpusError,digest,moment,sha
from apps.compass.retrieval_policies import (REGISTRY, RECORD_PREFIX, SPEC, POLICY_IDS,
    aspect_mode,validate_policy_reference)
from check_retrieval_coverage import ROOT,scope,MATRIX,MEDICATIONS,FREEZE


def install_policy_fixture(root, frozen, units):
    """Synthetic declared project constraints for a temporary coverage fixture."""
    save(root,'artificial-marker.json',{'fixture':'No actual policy, medical or runtime approval'})
    spec='Artificial project constraints, not real policy:\n'+'\n'.join('# policy:'+p+'\nArtificial constraint\n' for p in sorted(POLICY_IDS))
    path=root/SPEC;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(spec)
    pins=[]
    for pid in sorted(POLICY_IDS):
        bindings=[dict(unit_id=uid,aspect=pid,requirement_sha256=digest(unit['requirement'])) for uid,unit in units.items()
                  if pid in unit['aspects'] and aspect_mode(unit,pid)!='clinical']
        record=dict(schema_version=1,policy_id=pid,scope_version=frozen['scope_version'],statement='Artificial constraint',
            origin='HAC_PROJECT_POLICY',reviewer='Artificial policy author, not a physician',
            checked_at='2026-10-20T22:00:00+03:00',review_due_at='2026-10-21T22:00:00+03:00',
            assurance='documented_constraint',bindings=bindings,support=[dict(path=SPEC,sha256=sha(path.read_bytes()),locator='# policy:'+pid)],verification=None)
        relative=RECORD_PREFIX+pid+'.json';save(root,relative,record)
        pins.append(dict(policy_id=pid,record_path=relative,record_sha256=sha((root/relative).read_bytes()),status='approved'))
    save(root,REGISTRY,dict(schema_version=1,scope_version=frozen['scope_version'],policies=pins))
    return {row['policy_id']:{'policy_id':row['policy_id'],'record_sha256':row['record_sha256']} for row in pins}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for relative in [MATRIX,MEDICATIONS,FREEZE]:
            p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/relative).read_bytes())
        self.frozen,self.matrix,self.meds,self.units=scope(self.root)
        self.refs=install_policy_fixture(self.root,self.frozen,self.units)
        self.uid='D02-depression-symptoms';self.aspect='missing_data';self.unit=self.units[self.uid]

    def validate(self,ref=None):
        return validate_policy_reference(self.root,ref or self.refs[self.aspect],self.uid,self.unit,self.aspect,self.frozen,moment(AT))

    def mutate_record(self,operation):
        path=RECORD_PREFIX+self.aspect+'.json';value=json.loads((self.root/path).read_bytes());operation(value);save(self.root,path,value)
        registry=json.loads((self.root/REGISTRY).read_bytes());pin=next(p for p in registry['policies'] if p['policy_id']==self.aspect)
        pin['record_sha256']=sha((self.root/path).read_bytes());save(self.root,REGISTRY,registry)
        self.refs[self.aspect]['record_sha256']=pin['record_sha256']

    def test_declared_policy_has_explicit_own_origin_and_assurance(self):
        value=self.validate();self.assertEqual(value['origin'],'HAC_PROJECT_POLICY')
        self.assertEqual(value['assurance'],'documented_constraint');self.assertIsNone(value['verification'])

    def test_policy_cannot_support_medical_or_dossier_aspect(self):
        for uid,aspect in [('D02-depression-symptoms','symptoms'),('D03-depression-remission','source_definition')]:
            with self.subTest(uid=uid),self.assertRaisesRegex(CorpusError,'policy_cannot_replace_clinical_source'):
                validate_policy_reference(self.root,self.refs['missing_data'],uid,self.units[uid],aspect,self.frozen,moment(AT))
        unit=dict(kind='dossier',aspects=['missing_data'],requirement={'artificial':'not a cell'})
        with self.assertRaises(CorpusError):validate_policy_reference(self.root,self.refs['missing_data'],'drug/section',unit,'missing_data',self.frozen,moment(AT))

    def test_record_or_spec_bytes_change_invalidates_reference(self):
        for path in [RECORD_PREFIX+self.aspect+'.json',SPEC]:
            with self.subTest(path=path):
                old=(self.root/path).read_bytes();(self.root/path).write_bytes(old+b' ')
                with self.assertRaises(CorpusError):self.validate()
                (self.root/path).write_bytes(old)

    def test_revoked_unknown_or_escaping_record_path_invalid(self):
        original=(self.root/REGISTRY).read_bytes()
        for k,value in [('status','revoked'),('record_path','../outside.json'),('record_sha256','0'*64)]:
            d=json.loads(original);next(p for p in d['policies'] if p['policy_id']==self.aspect)[k]=value;save(self.root,REGISTRY,d)
            with self.assertRaises(CorpusError):self.validate()
        (self.root/REGISTRY).write_bytes(original)

    def test_requirement_scope_binding_review_window_and_origin_are_checked(self):
        original=(self.root/(RECORD_PREFIX+self.aspect+'.json')).read_bytes()
        for op in [lambda r:r.update(review_due_at=r['checked_at']),lambda r:r.update(checked_at='2027-01-01T00:00:00+03:00'),
            lambda r:r.update(scope_version='wrong'),lambda r:r.update(statement='Unsupported new statement'),lambda r:r.update(origin='Ministry guideline'),lambda r:r.update(bindings=[]),
            lambda r:r['bindings'][0].update(requirement_sha256='0'*64)]:
            self.mutate_record(op)
            with self.assertRaises(CorpusError):self.validate()
            # Restore through re-hashing before the next independent mutation.
            self.mutate_record(lambda r:r.update(json.loads(original)))

    def test_tested_control_cannot_be_declared_without_real_proof_structure(self):
        self.mutate_record(lambda r:r.update(assurance='tested_existing_control'))
        with self.assertRaisesRegex(CorpusError,'policy_test_evidence_missing'):self.validate()

    def test_symlink_and_arbitrary_support_files_refused(self):
        target=self.root/SPEC;body=target.read_bytes();outside=self.root/'outside.txt';outside.write_bytes(body)
        target.unlink();target.symlink_to(outside)
        with self.assertRaises(CorpusError):self.validate()
        target.unlink();target.write_bytes(body)
        self.mutate_record(lambda r:r['support'][0].update(path='outside.txt'))
        with self.assertRaisesRegex(CorpusError,'policy_support_path'):self.validate()

    def install_tested_fixture(self):
        # Artificial successful-run structure, not an actual runtime proof.
        code='apps/compass/assessments.py';test='apps/tests/test_assessments.py';name='test_artificial_only'
        for path,text in [(code,'def artificial_control(): pass'),(test,'def '+name+'(): pass')]:
            p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        lp='evidence/S17J02B02/policy-control-tests.log';p=self.root/lp;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('ARTIFICIAL ONLY')
        self.run_path='evidence/S17J02B02/policy-control-tests.json'
        self.run=dict(status='PASS',exit_code=0,checked_at='2026-10-20T22:00:00+03:00',command='Artificial isolated proof fixture',tests=[test+'::'+name],log_path=lp,log_sha256=sha(p.read_bytes()))
        save(self.root,self.run_path,self.run)
        def update(r):
            r['assurance']='tested_existing_control';r['support'].append(dict(path=code,sha256=sha((self.root/code).read_bytes()),locator='def artificial_control('))
            r['verification']=dict(test_path=test,test_sha256=sha((self.root/test).read_bytes()),test_name=name,run_path=self.run_path,run_sha256=sha((self.root/self.run_path).read_bytes()))
        self.mutate_record(update)

    def test_tested_control_checks_run_status_selected_test_date_and_log_hash(self):
        self.install_tested_fixture();self.assertEqual(self.validate()['assurance'],'tested_existing_control')
        for change in [dict(exit_code=1),dict(status='FAIL'),dict(tests=[]),dict(checked_at='2026-10-22T00:00:00+03:00'),dict(checked_at='2026-10-18T00:00:00+03:00'),dict(log_sha256='0'*64)]:
            value=deepcopy(self.run);value.update(change);save(self.root,self.run_path,value)
            self.mutate_record(lambda r:r['verification'].update(run_sha256=sha((self.root/self.run_path).read_bytes())))
            with self.subTest(change=change),self.assertRaises(CorpusError):self.validate()
        save(self.root,self.run_path,self.run)
        self.mutate_record(lambda r:r['verification'].update(run_sha256=sha((self.root/self.run_path).read_bytes())))
        self.assertEqual(self.validate()['assurance'],'tested_existing_control')

if __name__=='__main__':unittest.main()
