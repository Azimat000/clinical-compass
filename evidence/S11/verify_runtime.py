"""Real HTTP bidirectional exchange, uncertain TCP result and process restart."""
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
from urllib.request import build_opener, HTTPCookieProcessor, urlopen, Request
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.compass.db import connect
from apps.compass.access import seed_accounts


def main():
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'runtime.sqlite3'
        cmd=[sys.executable,'-m','apps.compass','--db',str(path)]
        subprocess.run(cmd+['seed-demo'],cwd=ROOT,check=True,capture_output=True)
        db=connect(path);credentials={x['login']:x['password'] for x in seed_accounts(db)};db.close()
        with socket.socket() as s: s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        doctor,patient=[build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar())) for _ in range(2)]
        process=None;pids=[]
        def stop():
            nonlocal process
            if process: process.kill();process.wait(timeout=10);process=None
        def start():
            nonlocal process
            process=subprocess.Popen(cmd+['serve','--port',str(port)],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            pids.append(process.pid)
            for _ in range(100):
                try:
                    with urlopen(origin+'/healthz',timeout=1) as r: assert json.load(r)['status']=='ok'
                    return
                except OSError: time.sleep(.1)
            raise RuntimeError('Startup timeout')
        def get(browser,route):
            with browser.open(origin+route,timeout=5) as r: return r.read().decode()
        def post(browser,route,form,token_route='/'):
            csrf=re.search(r'name="csrf" value="([^"]+)"',get(browser,token_route)).group(1)
            with browser.open(origin+route,urlencode({'csrf':csrf,**form}).encode(),timeout=5) as r:return r.read().decode()
        try:
            start()
            for browser,uid in ((doctor,'doctor-demo'),(patient,'patient-D01')):
                post(browser,'/login',{'login':uid,'password':credentials[uid]},'/login')
            token=re.search(r'readonly value="([^"]+)"',post(doctor,'/invitations',{'patient_id':'D01'})).group(1)
            post(patient,'/link',{'invitation':token})
            route='/patients/D01/communication'
            form={'request_key':secrets.token_hex(16),'body':'Synthetic TCP message'}
            csrf=re.search(r'name="csrf" value="([^"]+)"',get(patient,route)).group(1)
            payload=urlencode({'csrf':csrf,**form}).encode()
            req=Request(origin+route+'/send',data=payload)
            for handler in patient.handlers:
                if isinstance(handler,HTTPCookieProcessor):handler.cookiejar.add_cookie_header(req)
            sock=socket.create_connection(('127.0.0.1',port),timeout=5)
            sock.sendall((f'POST {route}/send HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nCookie: {req.get_header("Cookie")}\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n').encode()+payload)
            sock.close()
            for _ in range(100):
                db=connect(path);count=db.execute('SELECT count(*) FROM messages').fetchone()[0];db.close()
                if count:break
                time.sleep(.01)
            assert count==1
            stop();start()
            post(patient,route+'/send',form)
            assert 'Synthetic TCP message' in get(doctor,route)
            db=connect(path);assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==1
            mid=db.execute('SELECT id FROM messages').fetchone()[0];db.close()
            post(doctor,route+'/read',{'message_id':mid})
            reply={'request_key':secrets.token_hex(16),'body':'Synthetic doctor reply'}
            post(doctor,route+'/send',reply)
            assert 'Synthetic doctor reply' in get(patient,route)
            db=connect(path)
            before={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in ('messages','message_context','message_receipts')}
            db.close();stop();start()
            post(doctor,route+'/send',reply)
            db=connect(path)
            assert before=={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in before}
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            db.close()
            print(json.dumps({'server_processes':pids,'forced_restarts':2,'socket_closed_before_response':True,
              'retry_single_patient_message':True,'two_directions':True,'all_rows_survived':True,
              'messages':2,'explicit_receipts':2,'integrity':'ok'},indent=2))
        finally:stop()

if __name__=='__main__':main()
