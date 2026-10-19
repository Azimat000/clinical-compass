"""Small local synthetic query measurements, not a load benchmark."""
import json
from pathlib import Path
import statistics
import tempfile
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,'apps/tests')
from test_access import setup_identities
from apps.compass import access,records,extraction
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo,patient_list

with tempfile.TemporaryDirectory() as temp:
    db=connect(Path(temp)/'search.sqlite3');migrate(db);seed_demo(db);setup_identities(db)
    access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'))
    records.save(db,{'id':'pat-a','role':'patient'},'D01','self_report',{'request_key':'a'*32,'observed_on':records.today().isoformat(),'summary':'Уникальныйсамоотчёт'})
    extraction.save_import(db,{'id':'doc-a','role':'doctor'},'D01','Уникальныйимпорт 35 лет.','b'*32)
    queries=[{'query':'D01'},{'query':'Уникальныйсамоотчёт'},{'query':'Уникальныйимпорт'},
             {'age_status':'known','record_kind':'self_report'},{'attention':'pending'},
             {'route_category':'desirable'},{'query':'%_" OR 1=1'}]
    results=[]
    for filters in queries:
        times=[];sql=[]
        db.set_trace_callback(sql.append)
        rows=patient_list(db,doctor_id='doc-a',**filters)
        db.set_trace_callback(None)
        statement=next(s for s in sql if s.startswith('SELECT p.*'))
        plan=[list(r) for r in db.execute('EXPLAIN QUERY PLAN '+statement)]
        for _ in range(30):
            begin=time.perf_counter();patient_list(db,doctor_id='doc-a',**filters);times.append((time.perf_counter()-begin)*1000)
        results.append({'filters':filters,'ids':[r['id'] for r in rows],'median_ms':round(statistics.median(times),4),'max_ms':round(max(times),4),'explain_query_plan':plan})
    result={'scope':'6 synthetic patients, 1 active pair, 1 self-report, 1 import; warm single-connection queries, 30 repeats; not S15 load test',
            'sqlite':db.execute('select sqlite_version()').fetchone()[0],'results':results,'integrity':db.execute('pragma integrity_check').fetchone()[0],
            'foreign_keys':list(db.execute('pragma foreign_key_check'))}
    Path('evidence/S13/search.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    db.close()
print('PASS: 7 measured selections, query plans captured')
