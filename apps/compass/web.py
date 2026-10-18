"""Read-only application shell. Authentication is the next slice."""
import os
from flask import Flask, abort, g, render_template, request

from .db import connect, health, migrate
from .repository import patient_list


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(DATABASE=str(database or os.environ.get('COMPASS_DB', 'var/compass.sqlite3')),
                      MAX_CONTENT_LENGTH=65536, TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    db = connect(app.config['DATABASE'])
    try:
        migrate(db)
    finally:
        db.close()

    def get_db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/healthz')
    def healthz():
        return health(get_db())

    @app.get('/')
    def dashboard():
        query = request.args.get('q', '').strip()[:100]
        age_status = request.args.get('age_status', '')
        if age_status not in ('', 'known', 'unknown', 'conflicting'):
            abort(400)
        rows = patient_list(get_db(), query, age_status)
        return render_template('dashboard.html', patients=rows, query=query, age_status=age_status)

    @app.get('/demo/<patient_id>')
    def demo_patient(patient_id):
        db = get_db()
        patient = db.execute('SELECT * FROM patients WHERE id=?', (patient_id,)).fetchone()
        if patient is None:
            abort(404)
        encounters = db.execute('SELECT * FROM encounters WHERE patient_id=? ORDER BY occurred_at DESC', (patient_id,)).fetchall()
        return render_template('patient.html', patient=patient, encounters=encounters)

    return app
