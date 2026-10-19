"""Local synthetic cabinets; every patient resource uses server-side access checks."""
import os
import re
import json
import secrets
from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from .db import connect, health, migrate, now, transaction
from .repository import patient_list
from . import access, records, assessments, decisions, ages, routing, notifications, clinical_rules, critical_delivery, communication, extraction


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(DATABASE=str(database or os.environ.get('COMPASS_DB', 'var/compass.sqlite3')),
                      MAX_CONTENT_LENGTH=65536, TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'],
                      AUTH_COOKIE_SECURE=os.environ.get('COMPASS_COOKIE_SECURE') == '1')
    db = connect(app.config['DATABASE'])
    try:
        migrate(db)
        assessments.install_form(db)
    finally:
        db.close()

    def get_db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    def role(required):
        if g.user['role'] != required:
            abort(403)

    @app.errorhandler(413)
    def request_too_large(error):
        return render_template('result.html',title='Ввод слишком большой',
                               message='Запрос больше 65 536 байт. Для импорта нужен текст или .txt UTF-8 до 24 000 байт; уменьшите файл или текст.'),413

    @app.errorhandler(clinical_rules.RuleError)
    def rule_failure(error):
        return render_template('result.html', title='Источниковая проверка не выполнена',
                               message=str(error)), error.status

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
        return {'current_user': g.get('user'), 'csrf': g.user['csrf_token'] if g.get('user') else '',
                'route_categories': routing.CATEGORIES, 'route_urgencies': routing.URGENCIES}

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
        record_kind = request.args.get('record_kind', '')
        route_category = request.args.get('route_category', '')
        attention = request.args.get('attention', '')
        try:
            rows = patient_list(get_db(), query, age_status, doctor_id=g.user['id'],
                                record_kind=record_kind, route_category=route_category, attention=attention)
        except ValueError:
            abort(400)
        offers = get_db().execute('''SELECT token_hash,patient_id,expires_at FROM care_invitations
            WHERE doctor_id=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?''', (g.user['id'], now())).fetchall()
        route_summaries = {p['id']: routing.summaries(get_db(), g.user, p['id']) for p in rows}
        return render_template('dashboard.html', route_summaries=route_summaries, patients=rows, query=query, age_status=age_status, offers=offers,
                               record_kind=record_kind, route_category=route_category, attention=attention)

    @app.get('/demo/<patient_id>')
    def demo_patient(patient_id):
        return render_patient(patient_id)

    @app.get('/patients/<patient_id>/communication')
    def communication_page(patient_id):
        patient = patient_or_404(patient_id)
        try:
            data = communication.view(get_db(), g.user, patient_id)
        except communication.Error as error:
            return render_template('result.html', title='Раздел недоступен', message=str(error)), error.status
        return render_template('communication.html', patient=patient, data=data,
                               message_key=secrets.token_hex(16), task_key=secrets.token_hex(16),
                               report_keys={t['id']:secrets.token_hex(16) for t in data['tasks']})

    @app.post('/patients/<patient_id>/communication/<operation>')
    def communication_write(patient_id, operation):
        patient_or_404(patient_id)
        try:
            if operation == 'send':
                communication.send(get_db(),g.user,patient_id,request.form)
            elif operation == 'schedule':
                role('doctor')
                communication.schedule(get_db(),g.user,patient_id,request.form)
            elif operation == 'report':
                communication.report(get_db(),g.user,patient_id,request.form.get('task_id',''),request.form)
            elif operation in ('received','read'):
                communication.receipt(get_db(),g.user,patient_id,request.form.get('message_id',''),operation)
            else:
                abort(404)
        except communication.Error as error:
            return render_template('result.html', title='Не сохранено', message=str(error)), error.status
        return redirect(url_for('communication_page',patient_id=patient_id),code=303)

    @app.get('/notifications')
    def notification_inbox():
        role('doctor')
        try:
            items = notifications.inbox(get_db(), g.user, prepare=request.method != 'HEAD')
        except notifications.NotificationError as error:
            abort(error.status)
        return render_template('notifications.html', items=items)

    @app.post('/notifications/<notification_id>/<action>')
    def notification_mark(notification_id, action):
        role('doctor')
        try:
            notifications.mark(get_db(), g.user, notification_id, action)
        except notifications.NotificationError as error:
            return render_template('result.html', title='Отметка не сохранена', message=str(error)), error.status
        return redirect(url_for('notification_inbox'), code=303)

    @app.get('/critical')
    def critical_inbox():
        role('doctor')
        items = critical_delivery.inbox(get_db(), g.user)
        logs = {r['id']: get_db().execute('SELECT * FROM critical_delivery_log WHERE event_id=? ORDER BY sequence',
                                        (r['id'],)).fetchall() for r in items}
        return render_template('critical.html', items=items, logs=logs)

    @app.get('/api/critical')
    def critical_status():
        role('doctor')
        return jsonify([{'id':r['id'], 'received':r['received_at'] is not None}
                        for r in critical_delivery.inbox(get_db(),g.user) if r['acknowledged_at'] is None])

    @app.post('/critical/<event_id>/<action>')
    def critical_mark(event_id, action):
        role('doctor')
        try:
            critical_delivery.mark(get_db(), g.user, event_id, action, request.form.get('reaction',''))
        except notifications.NotificationError as error:
            return render_template('result.html', title='Отметка не сохранена', message=str(error)), error.status
        if action == 'received':
            return '', 204
        return redirect(url_for('critical_inbox'),code=303)

    @app.route('/patients/<patient_id>/imports', methods=['GET', 'POST'])
    def imports_page(patient_id):
        role('doctor')
        patient = patient_or_404(patient_id)
        error, status = None, 200
        values = request.form if request.method == 'POST' else {}
        if request.method == 'POST':
            try:
                file = request.files.get('file')
                if file and file.filename and request.form.get('source_text','').strip():
                    raise extraction.ExtractionError('Выберите один источник: текст или файл.')
                text = extraction.upload_text(file) if file and file.filename else request.form.get('source_text','')
                if re.search(r'\d{101}',text):
                    raise extraction.ExtractionError('Числовой фрагмент длиннее 100 цифр не поддерживается; проверьте источник.')
                extraction.save_import(get_db(),g.user,patient_id,text,request.form.get('request_key',''))
                return redirect(url_for('imports_page',patient_id=patient_id),code=303)
            except (extraction.ExtractionError, decisions.DecisionError) as exc:
                error, status = str(exc), exc.status
        items = extraction.history(get_db(),patient_id)
        for item in items:
            for candidate in item['result']['candidates']:
                candidate['review_value'] = extraction.canonical(candidate['value'])
            for review in item['reviews']:
                review['payload'] = json.loads(review['payload_json'])
        return render_template('imports.html',patient=patient,items=items,error=error,values=values,
                               fields=extraction.FIELDS,assertions=extraction.ASSERTIONS,assertion_labels=extraction.ASSERTION_LABELS,
                               warning=extraction.WARNING,new_key=lambda:secrets.token_hex(16)),status

    @app.post('/patients/<patient_id>/imports/<import_id>/review')
    def review_import(patient_id,import_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            extraction.review(get_db(),g.user,patient_id,import_id,request.form)
        except (extraction.ExtractionError, decisions.DecisionError) as exc:
            return render_template('result.html',title='Сверка не сохранена',message=str(exc)),exc.status
        return redirect(url_for('imports_page',patient_id=patient_id),code=303)

    def render_patient(patient_id, form_values=None, form_error=None, assessment_error=None, assessment_values=None, age_error=None, age_values=None):
        patient = patient_or_404(patient_id)
        db = get_db()
        encounters = db.execute('SELECT * FROM encounters WHERE patient_id=? ORDER BY occurred_at DESC', (patient_id,)).fetchall()
        relationship = db.execute('''SELECT r.*,u.display_name FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?''', (patient_id, now())).fetchone()
        checks = db.execute('''SELECT c.* FROM relationship_checks c JOIN care_relationships r ON r.id=c.relationship_id
            WHERE r.patient_id=? AND r.ends_at IS NULL ORDER BY c.received_at DESC LIMIT 20''', (patient_id,)).fetchall()
        entries = records.history(db, patient_id)
        measured = assessments.history(db, g.user, patient_id)
        return render_template('patient.html', patient=patient, encounters=encounters, relationship=relationship, checks=checks,
                               clinical_panel=clinical_rules.panel(db, g.user, patient_id) if g.user['role']=='doctor' else None,
                               clinical_context_key=secrets.token_hex(16),
                               route_items=routing.summaries(db, g.user, patient_id),
                               entries=entries, record_warnings=records.warnings(patient, entries),
                               age_view=ages.view(db, patient), age_error=age_error, age_values=age_values or {},
                               age_request_key=secrets.token_hex(16),
                               wellbeing_trend=records.wellbeing_trend(entries),
                               measured=measured, assessment_trends=assessments.trends(measured) if g.user['role']=='doctor' else [],
                               pending_assessments=assessments.pending(db, g.user, patient_id), assessment_form=assessments.definition(),
                               assignment_key=(assessment_values.get('assignment_key','') if assessment_values is not None else secrets.token_hex(16)),
                               assessment_values=assessment_values or {}, assessment_error=assessment_error,
                               record_fields=records.FIELDS, statuses=records.STATUSES, wellbeing=records.WELLBEING,
                               request_key=(form_values.get('request_key', '') if form_values is not None else secrets.token_hex(16)),
                               today=records.today().isoformat(), form_values=form_values or {}, form_error=form_error)

    @app.post('/patients/<patient_id>/clinical-context')
    def clinical_context(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            clinical_rules.save_context(get_db(), g.user, patient_id, request.form)
        except clinical_rules.RuleError as error:
            return render_template('result.html', title='Сведения не сохранены', message=str(error)), error.status
        return redirect(url_for('demo_patient', patient_id=patient_id) + '#clinical-rules', code=303)

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

    @app.post('/patients/<patient_id>/age-reviews')
    def review_age(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            ages.reconcile(get_db(), g.user, patient_id, request.form)
        except ages.AgeError as error:
            return render_patient(patient_id, age_error=str(error), age_values=request.form), error.status
        return redirect(url_for('demo_patient', patient_id=patient_id)+'#age-review', code=303)

    @app.post('/patients/<patient_id>/assessment-requests')
    def request_assessment(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            assessments.assign(get_db(), g.user, patient_id, request.form)
        except assessments.AssessmentError as error:
            return render_patient(patient_id, assessment_error=str(error), assessment_values=request.form), error.status
        return redirect(url_for('demo_patient', patient_id=patient_id)+'#assessments', code=303)

    @app.route('/assessments/<request_id>', methods=['GET','POST'])
    def assessment_form(request_id):
        db = get_db()
        try:
            task = assessments.visible_request(db, g.user, request_id, read_completed=request.method=='GET')
            if request.method == 'POST':
                assessments.submit(db, g.user, request_id, request.form)
                return redirect(url_for('assessment_form', request_id=request_id), code=303)
            completed = db.execute('SELECT assessment_id,recorded_at FROM assessment_results WHERE request_id=?', (request_id,)).fetchone()
            if completed:
                if g.user['role']=='doctor':
                    return redirect(url_for('demo_patient', patient_id=task['patient_id'])+'#assessment-'+completed['assessment_id'])
                return render_template('assessment_receipt.html', task=task, received_at=completed['recorded_at'])
            if task['expires_at']<=now() or task['age_on']!=records.today().isoformat():
                raise assessments.AssessmentError('Срок предложения истёк. Врач может предложить новую анкету.',409)
            form = assessments.available_form(db, task['form_version_id'])
        except assessments.AssessmentError as error:
            if request.method == 'POST' and error.status == 400:
                return render_template('assessment_form.html', task=task, instrument=assessments.definition(), values=request.form, error=str(error)),400
            return render_template('result.html', title='Анкета недоступна', message=str(error)),error.status
        return render_template('assessment_form.html', task=task, instrument=form, values={}, error=None)

    @app.get('/api/patients/<patient_id>/assessments')
    def assessments_api(patient_id):
        patient_or_404(patient_id)
        return jsonify({'assessments': assessments.history(get_db(),g.user,patient_id)})

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

    @app.route('/patients/<patient_id>/decisions', methods=['GET', 'POST'])
    def decisions_page(patient_id):
        patient = patient_or_404(patient_id)
        error, status = None, 200
        if request.method == 'POST':
            role('doctor')
            try:
                proposal_id = decisions.draft(get_db(), g.user, patient_id, request.form)
                return redirect(url_for('decisions_page', patient_id=patient_id)+'#decision-'+proposal_id, code=303)
            except decisions.DecisionError as failure:
                error, status = str(failure), failure.status
        items = decisions.history(get_db(), g.user, patient_id)
        values = request.form if request.method == 'POST' else {}
        if request.method == 'GET' and request.args.get('from_context'):
            role('doctor')
            advice = clinical_rules.recommendation(get_db(), g.user, patient_id)
            if advice['context_id'] != request.args['from_context'] or advice['category'] == 'unknown':
                return render_template('result.html', title='Рекомендация изменилась', message='Обновите карточку и проверьте исходные сведения.'), 409
            alternative = 'Допустимая альтернатива по КР — врач-психотерапевт.' if advice.get('alternative') == 'psychotherapist' else ''
            values = {'kind': 'referral', 'content': advice['reason'] + ' ' + alternative,
                      'basis': advice['source_url'] + ' · ' + advice['source_section'],
                      'uncertainties': 'Срочность определяет врач. Это проект; он не изменяет план до отдельного подтверждения.',
                      'route_rule_context_id': advice['context_id'],
                      'route_category': advice['category'], 'route_urgency': 'unknown',
                      'route_population_status': 'known', 'route_age_years': str(advice['age_years']),
                      'route_population': 'Взрослая применимость проверена по имеющимся возрастным источникам; требуется сверка врача.',
                      'route_severity': advice['basis'], 'route_severity_status': 'unknown',
                      'route_evidence': advice['source_url'] + ' · ' + advice['source_section'] + ' · ' + advice['reason'],
                      'route_unavailable': 'Не ожидать помощи через демо: использовать доступный обычный канал связи с врачом или обратиться в медицинскую организацию.'}
        return render_template('decisions.html', patient=patient, decisions=items, kinds=decisions.KINDS,
                               reference=decisions.reference() if g.user['role']=='doctor' else None,
                               route_reference=routing.reference() if g.user['role']=='doctor' else None,
                               route_categories=routing.CATEGORIES, route_urgencies=routing.URGENCIES, route_statuses=routing.STATUSES,
                               error=error, values=values,
                               request_key=request.form.get('request_key', secrets.token_hex(16))), status

    @app.post('/patients/<patient_id>/decisions/<proposal_id>/confirm')
    def confirm_decision(patient_id, proposal_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            decisions.confirm(get_db(), g.user, patient_id, proposal_id, request.form)
        except decisions.DecisionError as error:
            return render_template('result.html', title='Решение не подтверждено', message=str(error)), error.status
        return redirect(url_for('decisions_page', patient_id=patient_id)+'#decision-'+proposal_id, code=303)

    @app.get('/api/patients/<patient_id>/decisions')
    def decisions_api(patient_id):
        patient_or_404(patient_id)
        return jsonify({'decisions': decisions.history(get_db(), g.user, patient_id)})

    @app.post('/api/patients/<patient_id>/actions')
    def actions_api(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        # Generic action writes remain closed; use the versioned manual review workflow.
        return {'error': 'clinical_actions_inactive'}, 409

    return app
