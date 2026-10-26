"""Real process/SQLite test. Only a new synthetic database; no network/model stub.

A generation process claims and stalls, then is killed. Production risk worker
runs independently; production generation worker recovers after the real 90s
lease expires. Default production executor reports operation_unavailable.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from apps.compass import backend_analyses as analyses, backend_jobs as jobs
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from apps.tests.test_access import setup_identities

ROOT = Path(__file__).resolve().parents[2]


def main():
    started = time.monotonic()
    children=[]
    with tempfile.TemporaryDirectory(prefix='BE06-live-') as directory:
        dbpath=Path(directory)/'synthetic.sqlite3'
        with closing(connect(dbpath)) as db:
            migrate(db); seed_demo(db); setup_identities(db)
            db.execute("UPDATE patients SET age_status='known',age_years=35,birth_date=NULL,created_at=? WHERE id='D01'", (now(),))
            db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('live-link','D01','doc-a',now()))
            db.execute('UPDATE backend_job_settings SET enabled=1')
            user={'id':'doc-a','role':'doctor'}
            generation=analyses.create(db,user,'D01',{'contract_version':'1.0','operation':'diagnosis','request_key':'1'*32})
            risk=analyses.create(db,user,'D01',{'contract_version':'1.0','operation':'risk','request_key':'2'*32})
            child_code = '''import sys,time,json
from apps.compass.db import connect
from apps.compass.backend_jobs import claim
with_db=connect(sys.argv[1])
work=claim(with_db,'generation')
print(json.dumps({'run_id':work['run']['id'],'token':work['token']}),flush=True)
while True: time.sleep(.1)
'''
            try:
                stalled=subprocess.Popen([sys.executable,'-c',child_code,str(dbpath)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append(stalled)
                claimed=json.loads(stalled.stdout.readline())
                assert claimed['run_id']==generation['run_id']
                lease=db.execute('SELECT lease_until FROM backend_jobs WHERE run_id=?',(generation['run_id'],)).fetchone()[0]
                worker=lambda lane: subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(dbpath),'worker','--lane',lane],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                risk_worker=worker('risk');children.append(risk_worker)
                def wait_status(run_id,expected,seconds):
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        value=analyses._latest(db,run_id)
                        if value['status']==expected:return value
                        time.sleep(.1)
                    raise AssertionError('status deadline: '+run_id)
                failed_risk=wait_status(risk['run_id'],'failed',20)
                risk_seconds=round(time.monotonic()-started,3)
                assert stalled.poll() is None
                assert analyses._latest(db,generation['run_id'])['status']=='running'
                risk_worker.terminate();risk_worker.communicate(timeout=10)
                stalled.kill();stalled.communicate(timeout=10)
                # Real time passes; no altered clock, backdated lease or SQL reset.
                restarted=worker('generation');children.append(restarted)
                failed_generation=wait_status(generation['run_id'],'failed',110)
                restarted.terminate();out,err=restarted.communicate(timeout=10)
                assert not err,err
                attempts=[dict(r) for r in db.execute('SELECT run_id,attempt,started_at,finished_at,outcome,error_code FROM backend_job_attempts ORDER BY run_id,attempt')]
                terminal_counts={r['run_id']:r['n'] for r in db.execute("SELECT run_id,count(*) n FROM analysis_result_versions WHERE status='failed' GROUP BY run_id")}
                assert terminal_counts=={risk['run_id']:1,generation['run_id']:1}
                assert all(v['result'] is None and v['errors'][0]['code']=='operation_unavailable' for v in (failed_risk,failed_generation))
                assert any(a['outcome']=='expired' for a in attempts)
                assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not db.execute('PRAGMA foreign_key_check').fetchall()
                report={'pass':True,'synthetic_only':True,'network_calls':0,'executor':'production unavailable, no clinical generator installed',
                        'real_processes':3,'simultaneous_processes':2,'lease_seconds':jobs.LEASE_SECONDS,'real_lease_wait':True,
                        'generation_claim_lease_until':lease,'risk_failed_while_generation_alive_seconds':risk_seconds,
                        'total_seconds':round(time.monotonic()-started,3),'risk':failed_risk,'generation':failed_generation,
                        'attempts':attempts,'terminal_counts':terminal_counts,'integrity':'ok','foreign_key_violations':0}
                (ROOT/'evidence/BE06/live-processes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({k:report[k] for k in ('pass','risk_failed_while_generation_alive_seconds','total_seconds','real_lease_wait')}))
            finally:
                for process in children:
                    if process.poll() is None:process.kill()
                    process.communicate(timeout=10)


if __name__=='__main__':main()
