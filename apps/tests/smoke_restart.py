"""Real WSGI process restart and durable outbox smoke check on a fresh DB."""
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'fresh.sqlite3'
        command = [sys.executable, '-m', 'apps.compass', '--db', str(path)]
        subprocess.run(command + ['seed-demo'], cwd=ROOT, check=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        result = []
        for round_number in (1, 2):
            with open(Path(directory) / f'server-{round_number}.log', 'wb') as log:
                process = subprocess.Popen(command + ['serve', '--port', str(port)], cwd=ROOT, stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError('Server exited during startup')
                        try:
                            with urlopen(url + '/healthz', timeout=1) as response:
                                status = json.load(response)
                            break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise RuntimeError('Server did not become ready')
                    with urlopen(url, timeout=3) as response:
                        html = response.read().decode()
                    assert 'Демо 01' in html and 'Демо 06' in html
                    result.append({'restart_round': round_number, 'health': status, 'six_cards': True})
                finally:
                    process.terminate()
                    process.wait(timeout=10)
        subprocess.run(command + ['worker', '--once'], cwd=ROOT, check=True)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT count(*) FROM patients').fetchone()[0] == 6
            assert db.execute("SELECT count(*) FROM outbox_events WHERE status='processed'").fetchone()[0] == 6
            assert db.execute('SELECT count(*) FROM event_receipts').fetchone()[0] == 6
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        print(json.dumps({'process_restart': result, 'durable_events_after_restart': 6, 'integrity': 'ok'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
