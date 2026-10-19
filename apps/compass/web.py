"""Local synthetic cabinets; every patient resource uses server-side access checks."""
import os
import secrets
from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from .db import connect, health, migrate, now, transaction
from .repository import patient_list
from . import access, records


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(DATABASE=str(database or os.environ.get('COMPASS_DB', 'var/compass.sqlite3')),
                      MAX_CONTENT_LENGTH=65536, TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'],
                      AUTH_COOKIE_SECURE=os.environ.get('COMPASS_COOKIE_SECURE') == '1')
    db = connect(app.config['DATABASE'])
    try:
        migrate(db)
    finally:
        db.close()

    def get_db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    def role(required):
        if g.user['role'] != required:
            abort(403)

    def patient_or_404(patient_id):
        patient = access.visible_patient(get_db(), g.user, patient_id)
        if patient is None:
            abort(404)
        return patient

    def cookie(response, name, token, seconds):
        response.set_cookie(name, token, max_age=seconds, httponly=True,
                            secure=app.config['AUTH_COOKIE_SECURE'], samesite='Strict', path='/')

    @app.before_request
    def authorize():
        if request.endpoint in ('static', 'healthz', 'login') or request.endpoint is None:
            return
        g.user = access.resolve_session(get_db(), request.cookies.get(access.COOKIE, ''))
        if not g.user:
            if request.path.startswith('/api/'):
                abort(401)
            return redirect(url_for('login'))
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token', '') or request.form.get('csrf', '')
            if not secrets.compare_digest(g.user['csrf_token'], supplied):
                abort(403)

    @app.context_processor
    def auth_context():
        return {'current_user': g.get('user'), 'csrf': g.user['csrf_token'] if g.get('user') else ''}

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.after_request
    def headers(response):
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        if app.config['AUTH_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/healthz')
    def healthz():
        return health(get_db())

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error, status = None, 200
        if request.method == 'POST':
            if not access.consume_challenge(get_db(), request.cookies.get(access.CHALLENGE_COOKIE, ''), request.form.get('csrf', '')):
                abort(403)
            uid, password = request.form.get('login', ''), request.form.get('password', '')
            if len(uid) > 100 or len(password) > 256:
                abort(400)
            token, failure = access.authenticate(get_db(), uid, password, request.remote_addr or '', request.cookies.get(access.COOKIE, ''))
            if token:
                response = redirect(url_for('dashboard'))
                cookie(response, access.COOKIE, token, access.SESSION_HOURS * 3600)
                response.delete_cookie(access.CHALLENGE_COOKIE, path='/')
                return response
            error = 'Слишком много попыток. Повторите через 15 минут.' if failure == 'limited' else 'Не удалось войти. Проверьте логин и пароль.'
            status = 429 if failure == 'limited' else 401
        challenge = access.login_challenge(get_db())
        response = app.make_response((render_template('login.html', challenge=challenge, error=error), status))
        cookie(response, access.CHALLENGE_COOKIE, challenge, 600)
        return response

    @app.post('/logout')
    def logout():
        access.revoke_session(get_db(), request.cookies[access.COOKIE], g.user['id'])
        response = redirect(url_for('login'))
        response.delete_cookie(access.COOKIE, path='/')
        return response

    @app.get('/')
    def dashboard():
        if g.user['role'] == 'patient':
            p = get_db().execute('SELECT id FROM patients WHERE user_id=?', (g.user['id'],)).fetchone()
            if p is None:
                abort(404)
            return redirect(url_for('demo_patient', patient_id=p['id']))
        query = request.args.get('q', '').strip()[:100]
        age_status = request.args.get('age_status', '')
        if age_status not in ('', 'known', 'unknown', 'conflicting'):
            abort(400)
        rows = patient_list(get_db(), query, age_status, doctor_id=g.user['id'])
        offers = get_db().execute('''SELECT token_hash,patient_id,expires_at FROM care_invitations
            WHERE doctor_id=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?''', (g.user['id'], now())).fetchall()
        return render_template('dashboard.html', patients=rows, query=query, age_status=age_status, offers=offers)

    @app.get('/demo/<patient_id>')
    def demo_patient(patient_id):
        return render_patient(patient_id)

    def render_patient(patient_id, form_values=None, form_error=None):
        patient = patient_or_404(patient_id)
        db = get_db()
        encounters = db.execute('SELECT * FROM encounters WHERE patient_id=? ORDER BY occurred_at DESC', (patient_id,)).fetchall()
        relationship = db.execute('''SELECT r.*,u.display_name FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?''', (patient_id, now())).fetchone()
        checks = db.execute('''SELECT c.* FROM relationship_checks c JOIN care_relationships r ON r.id=c.relationship_id
            WHERE r.patient_id=? AND r.ends_at IS NULL ORDER BY c.received_at DESC LIMIT 20''', (patient_id,)).fetchall()
        entries = records.history(db, patient_id)
        return render_template('patient.html', patient=patient, encounters=encounters, relationship=relationship, checks=checks,
                               entries=entries, record_warnings=records.warnings(patient, entries),
                               record_fields=records.FIELDS, statuses=records.STATUSES, wellbeing=records.WELLBEING,
                               request_key=(form_values.get('request_key', '') if form_values is not None else secrets.token_hex(16)),
                               today=records.today().isoformat(), form_values=form_values or {}, form_error=form_error)

    @app.post('/invitations')
    def create_invitation():
        role('doctor')
        token = access.invite(get_db(), g.user['id'], request.form.get('patient_id', '')[:100])
        if token is None:
            return render_template('result.html', title='Приглашение не создано', message='Проверьте код пациента. Для него должно быть доступно приглашение.'), 409
        return render_template('invitation.html', token=token)

    @app.post('/invitations/<token_hash>/revoke')
    def revoke_invitation(token_hash):
        role('doctor')
        with transaction(get_db()):
            count = get_db().execute('''UPDATE care_invitations SET revoked_at=? WHERE token_hash=? AND doctor_id=?
                AND consumed_at IS NULL AND revoked_at IS NULL''', (now(), token_hash, g.user['id'])).rowcount
            if not count:
                abort(404)
            access.audit(get_db(), g.user['id'], 'care.invitation_revoked', token_hash)
        return redirect(url_for('dashboard'))

    @app.post('/link')
    def accept_invitation():
        role('patient')
        if not access.accept_invite(get_db(), g.user['id'], request.form.get('invitation', '')):
            return render_template('result.html', title='Приглашение недоступно', message='Код не подходит этому кабинету, истёк или уже использован.'), 409
        return redirect(url_for('dashboard'))

    @app.post('/patients/<patient_id>/connection-check')
    def connection_check(patient_id):
        role('patient')
        patient_or_404(patient_id)
        db = get_db()
        with transaction(db):
            r = db.execute('''SELECT r.id FROM care_relationships r JOIN patients p ON p.id=r.patient_id
                JOIN users d ON d.id=r.doctor_id WHERE p.id=? AND p.user_id=?
                AND r.ends_at IS NULL AND r.starts_at<=? AND d.disabled=0''', (patient_id, g.user['id'], now())).fetchone()
            if r is None:
                abort(409)
            check_id = secrets.token_hex(16)
            db.execute('INSERT INTO relationship_checks VALUES(?,?,?,?)', (check_id, r['id'], g.user['id'], now()))
            access.audit(db, g.user['id'], 'care.connection_checked', check_id)
        return redirect(url_for('demo_patient', patient_id=patient_id))

    def submit_record(patient_id, kind):
        role('patient' if kind == 'self_report' else 'doctor')
        patient_or_404(patient_id)
        try:
            entry_id = records.save(get_db(), g.user, patient_id, kind, request.form)
        except records.RecordError as error:
            # Keep entered values on error without creating a partial record.
            if error.status == 400:
                return render_patient(patient_id, request.form, str(error)), 400
            return render_template('result.html', title='Запись не сохранена', message=str(error)), error.status
        return redirect(url_for('demo_patient', patient_id=patient_id) + '#entry-' + entry_id, code=303)

    @app.post('/patients/<patient_id>/self-reports')
    def self_report(patient_id):
        return submit_record(patient_id, 'self_report')

    @app.post('/patients/<patient_id>/visits')
    def visit(patient_id):
        return submit_record(patient_id, 'visit')

    @app.get('/api/patients/<patient_id>/history')
    def history_api(patient_id):
        patient = patient_or_404(patient_id)
        entries = records.history(get_db(), patient_id)
        # Opaque retry hashes are internal and do not belong in the read API.
        return jsonify({'entries': [{k: v for k, v in e.items() if k not in ('request_key', 'payload_json')} for e in entries],
                        'warnings': records.warnings(patient, entries)})

    @app.get('/api/patients/<patient_id>')
    def patient_api(patient_id):
        return jsonify(dict(patient_or_404(patient_id)))

    @app.get('/api/patients/<patient_id>/documents')
    def documents_api(patient_id):
        patient_or_404(patient_id)
        return jsonify([dict(r) for r in get_db().execute('SELECT id,format,origin,received_at FROM documents WHERE patient_id=?', (patient_id,))])

    @app.get('/api/documents/<document_id>')
    def document_api(document_id):
        row = get_db().execute('SELECT patient_id FROM documents WHERE id=?', (document_id,)).fetchone()
        if row is None:
            abort(404)
        patient_or_404(row['patient_id'])
        # Upload/export are outside S05; never interpret a stored path as a URL.
        return {'error': 'document_delivery_unavailable'}, 409

    @app.get('/api/patients/<patient_id>/reports')
    def reports_api(patient_id):
        patient_or_404(patient_id)
        return jsonify([dict(r) for r in get_db().execute('SELECT id,received_at,payload_json FROM self_reports WHERE patient_id=? ORDER BY received_at', (patient_id,))])

    @app.post('/api/patients/<patient_id>/actions')
    def actions_api(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        # Fail closed until S08/S09 implement reviewed proposals and confirmation.
        return {'error': 'clinical_actions_inactive'}, 409

    return app
