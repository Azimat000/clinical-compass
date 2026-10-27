"""Lease-bound private packet checkpoints, reused only within the same run."""
from contextlib import closing
import json
import sqlite3
import time
from pathlib import Path
from .db import connect, now, transaction
from .backend_model import ModelError


class Store:
    def __init__(self, path, work):
        self.path=Path(path);self.run=work['run'];self.token=work['token']
        self.last_checked=0;self.stopped=False

    def _authorized(self, db):
        row=db.execute('''SELECT j.state,j.token,j.lease_until,s.enabled,s.generation_version,
            r.ends_at,u.disabled,u.role FROM backend_jobs j
            JOIN analysis_runs a ON a.id=j.run_id JOIN care_relationships r ON r.id=a.relationship_id
            JOIN users u ON u.id=a.actor_id JOIN backend_job_settings s ON s.id=1 WHERE j.run_id=?''',
            (self.run['id'],)).fetchone()
        return bool(row and row['state']=='running' and row['token']==self.token and row['lease_until']>now()
                    and row['enabled'] and row['generation_version']=='fe03b-packets-v1'
                    and row['ends_at'] is None and not row['disabled'] and row['role']=='doctor')

    def is_set(self):
        if self.stopped:return True
        if time.monotonic()-self.last_checked<.2:return False
        self.last_checked=time.monotonic()
        try:
            with closing(sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True,timeout=1)) as db:
                db.row_factory=sqlite3.Row;self.stopped=not self._authorized(db)
        except (sqlite3.Error,OSError):self.stopped=True
        return self.stopped

    def assert_active(self):
        """Freshness fence at packet boundaries; never a network write lock."""
        self.last_checked=0
        if self.is_set():raise ModelError('cancelled')
        from . import backend_analyses as analyses
        try:
            with closing(sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                value=analyses.read(db,{'id':self.run['actor_id'],'role':'doctor'},self.run['patient_id'],self.run['id'])
                if value['status']=='stale':raise ModelError('cancelled')
        except (sqlite3.Error,analyses.AnalysisError):
            raise ModelError('cancelled') from None

    def load(self, operation, branch, index, payload, runtime):
        with closing(sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True)) as db:
            row=db.execute('''SELECT response_json FROM analysis_packet_results WHERE
                run_id=? AND operation=? AND branch=? AND packet_index=? AND payload_sha256=? AND runtime_sha256=?''',
                (self.run['id'],operation,branch,index,payload,runtime)).fetchone()
            return json.loads(row[0]) if row else None

    def save(self, operation, branch, index, payload, runtime, response):
        db=connect(self.path)
        try:
            with transaction(db):
                if not self._authorized(db):raise ModelError('cancelled')
                db.execute('INSERT OR IGNORE INTO analysis_packet_results VALUES(?,?,?,?,?,?,?,?)',
                    (self.run['id'],operation,branch,index,payload,runtime,
                     json.dumps(response,ensure_ascii=False,separators=(',',':')),now()))
        finally:db.close()
