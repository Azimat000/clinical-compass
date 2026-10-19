"""Real HTTP import/review/retry across forced process restart; temporary synthetic DB."""
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPCookieProcessor, urlopen
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'apps/tests'))
from apps.compass.db import connect,migrate
from apps.compass.repository import seed_demo
from apps.compass import access, extraction
from test_access import setup_identities,PASSWORD


def main():
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'runtime.sqlite3'
        db=connect(path);migrate(db);seed_demo(db);setup_identities(db)
        access.accept_invite(db,'pat-a',access.invite(db,'doc-a','D01'));db.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        browser=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        process=None;pids=[]
        def stop():
            nonlocal process
            if process:process.kill();process.wait(timeout=10);process=None
        def start():
            nonlocal process
            process=subprocess.Popen([sys.executable,'-m','apps.compass','--db',str(path),'serve','--port',str(port)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pids.append(process.pid)
            for _ in range(100):
                try:
                    with urlopen(origin+'/healthz',timeout=1) as response:assert json.load(response)['status']=='ok'
                    return
                except OSError:time.sleep(.1)
            raise RuntimeError('Startup timeout')
        def get(route):
            with browser.open(origin+route,timeout=5) as response:return response.read().decode()
        def post(route,data,token_route='/patients/D01/imports'):
            token=re.search(r'name="csrf" value="([^"]+)"',get(token_route)).group(1)
            with browser.open(origin+route,urlencode({'csrf':token,**data}).encode(),timeout=5) as response:return response.read().decode()
        try:
            start()
            post('/login',{'login':'doc-a','password':PASSWORD},'/login')
            route='/patients/D01/imports'
            form={'source_text':'35 лет. F41.1. Авиандр 10 мг. Беременность: неизвестно.', 'request_key':secrets.token_hex(16)}
            page=post(route,form);assert 'Кандидаты, требуют сверки' in page
            stop();start()
            post(route,form)
            db=connect(path);items=extraction.history(db,'D01');assert len(items)==1
            item=items[0];c=item['result']['candidates'][0]
            review={'request_key':secrets.token_hex(16),'candidate_id':c['id'],'field':c['field'],'assertion':'unknown',
                    'value':'нужно уточнить','quote':c['quote'],'disposition':'correct','reason':'Synthetic review, no clinical action'}
            db.close()
            path_review=f"{route}/{item['id']}/review"
            post(path_review,review)
            db=connect(path)
            before={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in ('text_imports','extraction_reviews')}
            db.close();stop();start()
            page=post(path_review,review);assert 'нужно уточнить' in page
            db=connect(path)
            assert before=={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
            assert db.execute('SELECT count(*) FROM care_actions').fetchone()[0]==0
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            db.close()
            print(json.dumps({'processes':pids,'forced_restarts':2,'imports':1,'reviews':1,
                              'retries_no_duplicate':True,'all_rows_survived':True,'clinical_actions':0,'integrity':'ok'},indent=2))
        finally:stop()

if __name__=='__main__':main()
