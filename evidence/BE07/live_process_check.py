"""Actual production CLI worker, deterministic risk, no model/network substitution."""
from contextlib import closing
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

from apps.compass import backend_analyses as analyses, backend_risk_rules as rules, records
from apps.compass.db import connect, migrate, now
from apps.compass.repository import seed_demo
from apps.tests.test_access import setup_identities

ROOT = Path(__file__).resolve().parents[2]


def main():
    start = time.monotonic()
    outputs = []
    with tempfile.TemporaryDirectory(prefix='BE07-process-') as directory:
        path = Path(directory) / 'synthetic.sqlite3'
        with closing(connect(path)) as db:
            migrate(db); seed_demo(db); setup_identities(db)
            db.execute("UPDATE patients SET age_status='known',age_years=35,created_at=? WHERE id='D01'", (now(),))
            db.execute('INSERT INTO care_relationships VALUES(?,?,?,?,NULL)', ('be07-link','D01','doc-a',now()))
            db.execute('UPDATE backend_job_settings SET enabled=1')
            user = {'id':'doc-a','role':'doctor'}
            previous = None
            for condition, flags, expected in (
                ('F32', {'suicidal_plan':'present'}, ['DEP-SUICIDE-FACT']),
                ('F41.1', {'severity':'severe','psychopharmacotherapy':'present',
                          'initial_antidepressant_phase':'present','worsening_anxiety':'present'},
                          ['GAD-PSY-REVIEW','GAD-ADVERSE-REVIEW','GAD-INITIAL-ANXIETY']),
                ('F32', {}, [])):
                payload = {'condition':condition,'severity':'nonsevere','basis':'Авторский вымышленный пример.',
                           'supersedes_id':previous, **{k:'denied' for k in rules.FLAGS}, **flags}
                previous = rules.record_context(db,user,'D01',records.today().isoformat(),payload,secrets.token_hex(16))
                if condition == 'F41.1':
                    records.save(db,{'id':'pat-a','role':'patient'},'D01','self_report',{
                        'observed_on':records.today().isoformat(),'request_key':secrets.token_hex(16),
                        'adverse_events_status':'known','adverse_events_text':'Вымышленное НЯ'})
                child = subprocess.run([sys.executable,'-m','apps.compass','--db',str(path),
                                        'worker','--lane','risk','--once'],cwd=ROOT,
                                       text=True,capture_output=True,timeout=30)
                assert child.returncode == 0 and not child.stderr, (child.returncode,child.stderr)
                run = db.execute('SELECT id FROM analysis_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                value = analyses.read(db,user,'D01',run)
                assert value['status']=='ready', value
                assert value['model'] is None and value['release']['status']=='blocked'
                result=value['result']; ids=[p['id'] for p in result['output']['patterns']]
                assert ids==expected, ids
                assert result['output']['assessment']==('potential_risk' if expected else 'no_pattern_found')
                assert db.execute('SELECT attempts FROM backend_jobs WHERE run_id=?',(run,)).fetchone()[0]==1
                for fact in result['facts']:
                    for ref in fact['evidence_refs']:
                        resolved=analyses.inputs(db,user,'D01',run,reference=ref)
                        assert resolved['source']['ref']==ref
                outputs.append({'operation':'risk','condition':condition,'status':value['status'],
                                'assessment':result['output']['assessment'],'pattern_ids':ids,
                                'rules':result['output']['rule_evaluations'], 'attempts':1,
                                'model':None,'release':'blocked'})
            assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            assert db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]==3
            report={'pass':True,'production_cli_processes':3,'model_calls':0,'network_calls':0,
                    'source_fixture_substitution':False,'total_seconds':round(time.monotonic()-start,3),
                    'integrity':'ok','foreign_keys':0,'care_actions':0,'outputs':outputs}
            print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
