"""Fresh authored cases: no seed_demo, inherited diagnosis, safety denial or wellbeing."""
from copy import deepcopy
import json
from pathlib import Path
import secrets
import tempfile

from apps.compass import backend_analyses as analyses, backend_diagnosis_codec as codec
from apps.compass import backend_diagnosis_service as service, assessments, first_visits, records
from apps.compass.db import connect, migrate, now
from apps.compass.web import create_app
from apps.tests import test_access


def named_responses(raw):
    """Convert deliberately authored mechanics assertions to a test double response."""
    catalog=service.criteria.release();result={};offset=0
    for kind,c in catalog['conditions'].items():
        selected=raw['facts'][offset:offset+len(c['facts'])];offset+=len(c['facts'])
        refs={abs(i) for row in selected for i in row} | {abs(i) for i in raw['durations'][kind]['refs']}
        ids={ref:'q'+str(i+1) for i,ref in enumerate(sorted(refs))}
        def assertion(row):
            state='unknown' if not row else 'conflicting' if any(i<0 for i in row) and any(i>0 for i in row) else 'denied' if row[0]<0 else 'present'
            return {'state':state,'refs':[ids[abs(i)] for i in row]}
        d=raw['durations'][kind]
        result[kind]={'quotes':[{'id':ids[i],'unit_id':raw['quotes'][i-1]['u'],'quote':raw['quotes'][i-1]['q']} for i in sorted(refs)],
            'facts':[{'id':fid,**assertion(row)} for fid,row in zip(c['facts'],selected)],
            'duration':{'state':'known' if d['value'] is not None else 'unknown' if not d['refs'] else 'conflicting',
                        'value':d['value'],'refs':[ids[abs(i)] for i in d['refs']]}}
    return result


class BranchModel:
    def __init__(self,responses):self.responses=deepcopy(responses);self.calls=[]
    def generate(self,data,schema,**kw):
        self.calls.append((deepcopy(data),deepcopy(schema),kw))
        return {'value':deepcopy(self.responses[data['branch']]),'metadata':{'test_double':True}}


class CleanDiagnosticCase:
    """Only a new temporary database; never accepts a database path from caller."""
    def __init__(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'authored.sqlite3'
        self.db=connect(self.path);migrate(self.db)
        self.user={'id':'doc-a','role':'doctor'};self.patient={'id':'pat-a','role':'patient'};stamp=now()
        for uid,role in [('doc-a','doctor'),('doc-b','doctor'),('pat-a','patient'),('pat-b','patient')]:
            self.db.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,role,uid,test_access.PASSWORD_HASH))
        self.db.execute('INSERT INTO patients(id,user_id,code,age_years,age_status,synthetic,created_at) VALUES(?,?,?,?,?,?,?)',
                        ('D01','pat-a','Авторский синтетический контроль',37,'known',1,records.today().isoformat()+'T00:00:00+03:00'))
        self.db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)',('qa-link','D01','doc-a',stamp))
        self.db.execute('UPDATE backend_job_settings SET enabled=1,generation_version=?',(service.EXECUTION_VERSION,))
        self.app=create_app(self.path);self.clients={uid:self.app.test_client() for uid in ('doc-a','doc-b','pat-a','pat-b')}
        for uid,client in self.clients.items():
            if test_access.login(client,uid).status_code!=302:raise AssertionError('fixture_login')

    def populate(self,case):
        day=records.today().isoformat()
        # Absent psychiatric/medical history stays unknown, including safety.
        visit={'request_key':secrets.token_hex(16),'base_revision':'0','state':'draft',
               'observed_on':day,'visit_kind':'first','not_collected':'yes','age_source':'patient'}
        if case.get('history'):
            visit.update(history_status='known',history_text=case['history'],history_basis='Авторский контроль',history_on=day)
        first_visits.save(self.db,self.user,'D01','new',visit)
        for note in [case['note'], *case.get('additional_notes',[])]:
            records.save(self.db,self.patient,'D01','self_report',{'request_key':secrets.token_hex(16),
                'observed_on':day,'summary':note,'wellbeing':'unknown'})
        form=assessments.definition()
        task=assessments.assign(self.db,self.user,'D01',{'assignment_key':secrets.token_hex(16),'form_version_id':form['id']})
        answers=case.get('questionnaire_answers',[None]*len(form['items']))
        assessments.submit(self.db,self.patient,task,{'form_version_id':form['id'],
            **{'answer_'+str(i+1):'' if n is None else str(n) for i,n in enumerate(answers)}})
        self.assert_clean(case)

    def assert_clean(self,case):
        for table in ('encounters','therapy_courses','care_actions'):
            assert self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table
        assert all(r['data_status']=='unknown' and r['value_json'] is None for r in self.db.execute('SELECT * FROM observations'))
        rows=self.db.execute('SELECT payload_json FROM clinical_entries ORDER BY id').fetchall()
        assert sorted(json.loads(r[0])['summary'] for r in rows)==sorted([case['note'],*case.get('additional_notes',[])])
        assert all(json.loads(r[0])['wellbeing']=='unknown' for r in rows)
        for (payload,) in self.db.execute('SELECT payload_json FROM first_visit_versions'):
            fields=json.loads(payload)['fields']
            assert fields['safety']['status']=='unknown'
            assert fields['history']['text']==case.get('history','')
        assert self.db.execute('SELECT count(*) FROM patients').fetchone()[0]==1

    def snapshot(self):return json.loads(analyses.capture(self.db,'D01','qa-link'))
    def close(self):self.db.close();self.tmp.cleanup()
