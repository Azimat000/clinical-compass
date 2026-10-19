"""Real CLI, real pseudo terminal, no mocked sender; synthetic operator input."""
import json,os,pty,select,subprocess,sys,tempfile,time,secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'apps/tests')]
from apps.compass.db import connect,migrate,now
from apps.compass.repository import seed_demo
from apps.compass import records,clinical_rules,events
from test_access import setup_identities
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'reserve.sqlite3';db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
    db.execute("INSERT INTO care_relationships VALUES('rel','D01','doc-a',?,NULL)",(now(),))
    clinical_rules.save_context(db,{'id':'doc-a','role':'doctor'},'D01',{'request_key':'a'*32,'observed_on':records.today().isoformat(),'clinical_basis':'Synthetic existing source','aviandr_prescription':'active','prescription_basis':'Synthetic prescription'})
    records.save(db,{'id':'pat-a','role':'patient'},'D01','self_report',{'request_key':'b'*32,'observed_on':records.today().isoformat(),'safety_form_version':'aviandr-safety-v1','safety_taken':'present','safety_after_dose':'present','safety_current':'present','safety_trismus':'present'})
    while events.process_one(db):pass
    master,slave=pty.openpty()
    process=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(path),'reserve-console','--recipient','doc-a','--once'],cwd=ROOT,stdin=slave,stdout=slave,stderr=slave)
    os.close(slave);output=b''
    try:
        deadline=time.monotonic()+8
        while b'SIGNAL' not in output and time.monotonic()<deadline:
            if select.select([master],[],[],.2)[0]:output+=os.read(master,65536)
        assert 'КЛИНИЧЕСКИЙ КОМПАС' in output.decode()
        before=dict(db.execute('SELECT * FROM critical_delivery').fetchone())
        assert before['reserve_state']=='leased' and before['received_at'] is None
        os.write(master,b'SIGNAL\n')
        assert process.wait(timeout=5)==0
        row=dict(db.execute('SELECT * FROM critical_delivery').fetchone())
        assert row['reserve_state']=='operator_received'
        assert all(row[k] is None for k in ('received_at','seen_at','acknowledged_at','reacted_at'))
        entries=[dict(r) for r in db.execute('SELECT * FROM critical_delivery_log ORDER BY sequence')]
        print(json.dumps({'real_process':process.pid,'real_pseudo_terminal':True,'browser_not_launched':True,
          'signal_stdout':output.decode(),'operator_input':'SIGNAL (agent acting as synthetic local operator)',
          'result':row,'log':entries,'scope':'Actual console transport and separate operator receipt; no native window/sound/human physician receipt claimed.'},ensure_ascii=False,indent=2))
    finally:
        if process.poll() is None:process.kill();process.wait()
        os.close(master);db.close()
