"""Instrument the unmodified full suite; preserve failing access state without relaxing checks."""
import json
import sys
import unittest
sys.path.insert(0,'.')
sys.path.insert(0,'apps/tests')
from apps.compass import access, decisions
from apps.compass.db import now
trace=[]
original=access.visible_patient

def visible(db,user,pid):
    result=original(db,user,pid)
    if result is None:
        trace.append({'where':'visible','user':dict(user),'patient':pid,'now':now(),
                      'relationships':[dict(r) for r in db.execute('SELECT * FROM care_relationships')],
                      'patients':[dict(r) for r in db.execute('SELECT id,user_id FROM patients')]})
    return result
access.visible_patient=visible
original_doctor=decisions.doctor_relationship

def doctor(db,user,pid):
    try:return original_doctor(db,user,pid)
    except decisions.DecisionError as error:
        trace.append({'where':'doctor','status':error.status,'error':str(error),'now':now(),
                      'relationships':[dict(r) for r in db.execute('SELECT * FROM care_relationships')]})
        raise

decisions.doctor_relationship=doctor
class Result(unittest.TextTestResult):
    def startTest(self,test):
        trace.clear();super().startTest(test)
    def addFailure(self,test,err):
        print('ACCESS_DIAGNOSTIC',test.id(),json.dumps(trace[-10:],ensure_ascii=False),flush=True)
        super().addFailure(test,err)
suite=unittest.defaultTestLoader.discover('apps/tests')
result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
sys.exit(not result.wasSuccessful())
