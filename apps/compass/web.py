"""Local synthetic cabinets; every patient resource uses server-side access checks."""
import os
import re
import json
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from werkzeug.exceptions import HTTPException
from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from .db import connect, health, migrate, now, transaction
from .repository import patient_list
from . import access, records, assessments, decisions, routing, notifications, clinical_rules, critical_delivery, communication, extraction
from . import first_visits, follow_up, report_drafts, overview, medications, medication_feedback, plan_tasks, backend_analyses

# Screens rebuilt from scratch (UI02+). Every other view keeps answering 503/interface_removed.
READY_VIEWS = frozenset({'login.html', 'result.html', 'invitation.html',
                         'patient.html', 'assessment_form.html', 'assessment_receipt.html',
                         'dashboard.html', 'invitation_manage.html', 'doctor_patient.html',
                         'decisions.html', 'first_visit.html', 'imports.html',
                         'communication.html', 'plan.html'})
# Patient cabinet screens: a doctor never receives them; the doctor's card is doctor_patient.html.
PATIENT_VIEWS = frozenset({'patient.html', 'assessment_form.html', 'assessment_receipt.html', 'plan.html'})
# Doctor-only screens: a patient asking for the same address still gets the technical answer, not the doctor's page.
# communication.html is for both roles.
DOCTOR_VIEWS = frozenset({'decisions.html', 'first_visit.html', 'imports.html', 'critical.html', 'invitation_manage.html'})
MOSCOW = ZoneInfo('Europe/Moscow')
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')


def create_app(database=None):
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.jinja_env.globals.update(med_quantity=medications.quantity, med_choices=medications.choices, new_key=lambda: secrets.token_hex(16))
    app.json.ensure_ascii = False
    app.config.update(DATABASE=str(database or os.environ.get('COMPASS_DB', 'var/compass.sqlite3')),
                      MAX_CONTENT_LENGTH=65536, TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'],
                      AUTH_COOKIE_SECURE=os.environ.get('COMPASS_COOKIE_SECURE') == '1',
                      UI_GALLERY=os.environ.get('COMPASS_UI_GALLERY') == '1')
    db = connect(app.config['DATABASE'])
    try:
        migrate(db)
        assessments.install_form(db)
    finally:
        db.close()

    @app.template_global()
    def sheet_date():
        """Server date for the sheet header, as on a printed results form."""
        day = records.today()
        weekday = ('Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье')[day.weekday()]
        return weekday, day.strftime('%d.%m.%Y'), day.isoformat()

    @app.template_global()
    def clock_msk():
        """Time of the page as on a printed form: the moment the server composed the data."""
        return datetime.now(MOSCOW).strftime('%H:%M')

    @app.template_filter()
    def short_date(value):
        """2026-10-20 -> 20.10; anything else is shown as it came."""
        try:
            return datetime.strptime(value, '%Y-%m-%d').strftime('%d.%m')
        except (TypeError, ValueError):
            return value

    @app.template_filter()
    def full_date(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').strftime('%d.%m.%Y')
        except (TypeError, ValueError):
            return value

    @app.template_filter()
    def ru_day(value):
        """2026-10-22 -> 22 октября."""
        try:
            day = datetime.strptime(value, '%Y-%m-%d')
        except (TypeError, ValueError):
            return value
        return '%d %s' % (day.day, MONTHS[day.month - 1])

    @app.template_filter()
    def times(value):
        return overview.times_word(int(value))

    @app.template_filter()
    def years(value):
        try:
            return '%d %s' % (int(value), overview.years_word(int(value)))
        except (TypeError, ValueError):
            return 'не указан'

    @app.template_filter()
    def note_parts(value):
        return overview.note_parts(value)

    @app.template_filter()
    def note(value):
        """Warning text for people: ISO date -> 22.10, internal record ids dropped."""
        return overview.tidy(value or '')

    @app.template_filter()
    def msk(value):
        """Stored UTC stamp -> 22.10.2026 14:05 МСК."""
        try:
            return datetime.fromisoformat(value).astimezone(MOSCOW).strftime('%d.%m.%Y\u00a0%H:%M\u00a0МСК')
        except (TypeError, ValueError):
            return value

    def pending_invitations():
        user = g.get('user')
        if not user or user['role'] != 'doctor':
            return []
        return get_db().execute('''SELECT token_hash,patient_id,expires_at FROM care_invitations
            WHERE doctor_id=? AND consumed_at IS NULL AND revoked_at IS NULL AND expires_at>?
            ORDER BY expires_at DESC''', (user['id'], now())).fetchall()

    @app.context_processor
    def session_context():
        user = g.get('user')
        return {'current_user': user, 'csrf': user['csrf_token'] if user else '',
                'pending_invitations': pending_invitations}

    @app.template_filter()
    def person_name(code):
        """Display name of a patient from the list code."""
        return overview.person(code or '')[0]

    def get_db():
        if 'db' not in g:
            g.db = connect(app.config['DATABASE'])
        return g.db

    def role(required):
        if g.user['role'] != required:
            abort(403)

    def wants_html():
        """Browsers get pages; clients that ask for JSON keep the technical answers."""
        if request.path.startswith('/api/'):
            return False
        accepted = request.accept_mimetypes
        if not accepted:  # no Accept header means any type is acceptable
            return True
        return accepted.best_match(['text/html', 'application/json', 'text/plain']) == 'text/html'

    def interface_response(view, **context):
        """Render rebuilt screens; never serialize template context of missing ones.

        Keep login/invitation/assessment receipts usable without a browser UI.
        Existing mutation handlers, validation and access checks remain in place.
        """
        role_now = g.user['role'] if g.get('user') else None
        ready = (view in READY_VIEWS and (view not in PATIENT_VIEWS or role_now == 'patient')
                 and (view not in DOCTOR_VIEWS or role_now == 'doctor'))
        if ready and wants_html():
            return render_template(view, **context)
        if view == 'login.html':
            return jsonify(csrf=context['challenge'], error=context['error'])
        if view == 'invitation.html':
            return jsonify(invitation=context['token'])
        if view == 'assessment_receipt.html':
            return jsonify(status='submitted', request_id=context['task']['id'],
                           received_at=context['received_at'])
        if view == 'result.html':
            return app.response_class(error_page(context['title'], context['message']),
                                      mimetype='text/plain')
        g.interface_removed = True
        payload = {'status': 'interface_removed',
                   'message': 'Интерфейс удалён. Новый интерфейс пока не создан.'}
        failure = (context.get('error') or context.get('form_error')
                   or context.get('assessment_error'))
        if failure:
            payload['error'] = str(failure)
        if g.get('user'):
            payload['csrf'] = g.user['csrf_token']
        return jsonify(payload)

    def error_page(title, message):
        return title + '\n' + message + '\n'

    def failure_body(title, message):
        """Error pages for browsers; plain text for API and JSON clients or if rendering fails."""
        if wants_html():
            try:
                return render_template('result.html', title=title, message=message), 'text/html; charset=utf-8'
            except Exception:  # never let the error page hide the original failure
                app.logger.error('result_page_failure')
        return error_page(title, message), 'text/plain; charset=utf-8'

    @app.errorhandler(Exception)
    def request_failure(error):
        if isinstance(error, HTTPException):
            code = error.code
            title, message = {
                400: ('Неверный запрос', 'Проверьте введённые значения и откройте форму заново.'),
                401: ('Требуется вход', 'Сеанс завершён или недействителен. Войдите снова.'),
                403: ('Действие недоступно', 'Не хватает прав или код защиты формы устарел. Откройте форму заново.'),
                404: ('Запись недоступна', 'Запись не найдена или недоступна этому кабинету.'),
                405: ('Действие недоступно', 'Используйте соответствующую форму в кабинете.'),
            }.get(code, ('Запрос не выполнен', 'Откройте кабинет и проверьте состояние операции.'))
            if request.path.startswith('/api/v1/'):
                return jsonify(error='http_' + str(code), message=message), code
            response = error.get_response()
            body, content_type = failure_body(title, message)
            response.set_data(body)
            response.content_type = content_type
            return response
        # Never log exception text, URLs, headers, form bodies or traceback: they
        # can contain clinical text, credentials, SQL parameters or private paths.
        incident = secrets.token_hex(8)
        app.logger.error('request_failure incident=%s type=%s endpoint=%s',
                         incident, type(error).__name__, request.endpoint or 'unmatched')
        unavailable = isinstance(error, (sqlite3.Error, OSError))
        message = ('Не удалось завершить запрос; результат операции неизвестен. Отсутствие сигнала не означает отсутствие риска. '
                   'После восстановления откройте кабинет и проверьте сохранённые записи перед повтором. '
                   'Не ожидайте помощи через демо. Код ошибки: ' + incident)
        if request.path.startswith('/api/v1/'):
            response = jsonify(error='service_unavailable' if unavailable else 'internal_error', message=message)
            response.status_code = 503 if unavailable else 500
            if unavailable:
                response.headers['Retry-After'] = '5'
            return response
        body, content_type = failure_body('Сервис временно недоступен', message)
        response = app.make_response((body, 503 if unavailable else 500, {'Content-Type': content_type}))
        if unavailable:
            response.headers['Retry-After'] = '5'
        return response

    @app.errorhandler(413)
    def request_too_large(error):
        if request.path.startswith('/api/v1/'):
            return jsonify(error='request_too_large', message='Запрос больше 65 536 байт.'), 413
        return interface_response('result.html',title='Ввод слишком большой',
                               message='Запрос больше 65 536 байт. Для импорта нужен текст или .txt UTF-8 до 24 000 байт; уменьшите файл или текст.'),413

    @app.errorhandler(clinical_rules.RuleError)
    def rule_failure(error):
        return interface_response('result.html', title='Источниковая проверка не выполнена',
                               message=str(error)), error.status

    def author_names(items):
        """Display names for every doctor mentioned in a list of decisions."""
        ids = {i.get(key) for i in items for key in ('actor_id', 'doctor_id') if i.get(key)}
        if not ids:
            return {}
        marks = ','.join('?' * len(ids))
        return {r['id']: r['display_name'] for r in get_db().execute(
            'SELECT id,display_name FROM users WHERE id IN (%s)' % marks, tuple(ids))}

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
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if (any(len(request.form.getlist(key)) != 1 for key in request.form)
                    or any(len(request.files.getlist(key)) != 1 for key in request.files)
                    or set(request.form).intersection(request.files)):
                abort(400)
        if request.endpoint in ('static', 'healthz', 'login', 'ui_gallery') or request.endpoint is None:
            return
        g.user = access.resolve_session(get_db(), request.cookies.get(access.COOKIE, ''))
        if not g.user:
            if request.path.startswith('/api/'):
                abort(401)
            return redirect(url_for('login'))
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token', '') or request.form.get('csrf', '')
            if not access.matches_token(g.user['csrf_token'], supplied):
                abort(403)

    @app.errorhandler(backend_analyses.AnalysisError)
    def analysis_failure(error):
        return jsonify(error=error.code, message=str(error)), error.status

    @app.post('/api/v1/patients/<patient_id>/analyses')
    def create_analysis(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        if request.mimetype != 'application/json':
            raise backend_analyses.AnalysisError('Нужен Content-Type application/json.', 415, 'unsupported_media_type')
        body = backend_analyses.parse_request(request.get_data())
        value = backend_analyses.create(get_db(), g.user, patient_id, body)
        response = jsonify(value)
        response.status_code = 202
        response.headers['Location'] = url_for('get_analysis', patient_id=patient_id, run_id=value['run_id'])
        return response

    @app.get('/api/v1/patients/<patient_id>/analyses')
    def analysis_history(patient_id):
        role('doctor')
        if (set(request.args) - {'operation', 'page'}
                or any(len(request.args.getlist(key)) != 1 for key in request.args)):
            raise backend_analyses.AnalysisError('Недопустимые параметры страницы.', 400, 'invalid_page')
        page = request.args.get('page', '1')
        if not re.fullmatch(r'[1-9][0-9]{0,6}', page):
            raise backend_analyses.AnalysisError('Нужен номер страницы.', 400, 'invalid_page')
        from . import backend_analysis_history
        return jsonify(backend_analysis_history.read(get_db(), g.user, patient_id,
            operation=request.args.get('operation'), page=int(page)))

    @app.get('/api/v1/patients/<patient_id>/analyses/<run_id>')
    def get_analysis(patient_id, run_id):
        role('doctor')
        return jsonify(backend_analyses.read(get_db(), g.user, patient_id, run_id))

    @app.get('/api/v1/patients/<patient_id>/analyses/<run_id>/inputs')
    def analysis_inputs(patient_id, run_id):
        role('doctor')
        if set(request.args) - {'page'} or len(request.args.getlist('page')) > 1:
            raise backend_analyses.AnalysisError('Недопустимые параметры страницы.', 400, 'invalid_page')
        page = request.args.get('page', '1')
        if not re.fullmatch(r'[1-9][0-9]{0,8}', page):
            raise backend_analyses.AnalysisError('Нужен номер страницы.', 400, 'invalid_page')
        value = backend_analyses.inputs(get_db(), g.user, patient_id, run_id, page=int(page))
        return jsonify(value)

    @app.post('/api/v1/patients/<patient_id>/analyses/<run_id>/cancel')
    def cancel_analysis(patient_id, run_id):
        role('doctor')
        patient_or_404(patient_id)
        if request.args or request.mimetype != 'application/json':
            raise backend_analyses.AnalysisError('Нужен JSON без параметров адреса.')
        body = backend_analyses.parse_request(request.get_data(), schema=None)
        if body != {}:
            raise backend_analyses.AnalysisError('Для отмены требуется пустой объект.')
        from . import backend_jobs
        return jsonify(backend_jobs.cancel(get_db(), g.user, patient_id, run_id))

    @app.get('/api/v1/patients/<patient_id>/analyses/<run_id>/diagnosis-context')
    def analysis_diagnosis_context(patient_id, run_id):
        role('doctor')
        patient_or_404(patient_id)
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        from . import backend_diagnosis_service
        return jsonify(backend_diagnosis_service.details(get_db(), g.user, patient_id, run_id))

    @app.get('/api/v1/patients/<patient_id>/analyses/<run_id>/risk-context')
    def analysis_risk_context(patient_id, run_id):
        role('doctor')
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        from . import backend_risk_context
        return jsonify(backend_risk_context.details(get_db(), g.user, patient_id, run_id))

    @app.get('/api/v1/patients/<patient_id>/analyses/<run_id>/inputs/<reference>')
    def analysis_input_source(patient_id, run_id, reference):
        role('doctor')
        return jsonify(backend_analyses.inputs(get_db(), g.user, patient_id, run_id, reference=reference))

    @app.post('/api/v1/patients/<patient_id>/analyses/<run_id>/plan-reviews')
    def create_plan_review(patient_id, run_id):
        role('doctor')
        patient_or_404(patient_id)
        from . import backend_plan_review as review
        if request.args or request.mimetype != 'application/json':
            raise backend_analyses.AnalysisError('Нужен JSON без параметров адреса.')
        try:
            return jsonify(review.create(get_db(), g.user, patient_id, run_id,
                backend_analyses.parse_request(request.get_data(), schema=None)))
        except decisions.DecisionError as exc:
            raise backend_analyses.AnalysisError(str(exc), exc.status, 'plan_review_refused') from None

    @app.route('/api/v1/patients/<patient_id>/plan-reviews/<proposal_id>', methods=['GET', 'POST'])
    def plan_review(patient_id, proposal_id):
        role('doctor')
        patient_or_404(patient_id)
        from . import backend_plan_review as review
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        if request.method in ('GET', 'HEAD'):
            return jsonify(review.receipt(get_db(), g.user, patient_id, proposal_id))
        if request.mimetype != 'application/json':
            raise backend_analyses.AnalysisError('Нужен JSON.', 415, 'unsupported_media_type')
        return jsonify(review.confirm(get_db(), g.user, patient_id, proposal_id,
            backend_analyses.parse_request(request.get_data(), schema=None)))

    @app.route('/api/v1/patients/<patient_id>/therapy-context', methods=['GET', 'POST'])
    def therapy_context(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        from . import backend_therapy_context as context
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        if request.method == 'POST':
            if request.mimetype != 'application/json':
                raise backend_analyses.AnalysisError('Нужен JSON.', 415, 'unsupported_media_type')
            return jsonify(context.record(get_db(), g.user, patient_id,
                backend_analyses.parse_request(request.get_data(), schema=None)))
        return jsonify(context.view(get_db(), g.user, patient_id))

    @app.route('/api/v1/patients/<patient_id>/diagnosis-review', methods=['GET', 'POST'])
    def diagnosis_review(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        from . import backend_diagnosis_review as review
        if request.method == 'POST':
            if request.args or request.mimetype != 'application/json':
                raise backend_analyses.AnalysisError('Нужен JSON без параметров адреса.')
            body = backend_analyses.parse_request(request.get_data(), schema=None)
            return jsonify(review.record(get_db(), g.user, patient_id, body))
        if set(request.args) - {'page'} or len(request.args.getlist('page')) > 1:
            raise backend_analyses.AnalysisError('Недопустимые параметры страницы.')
        page = request.args.get('page', '1')
        if not re.fullmatch(r'[1-9][0-9]{0,8}', page):
            raise backend_analyses.AnalysisError('Нужен номер страницы.')
        return jsonify(review.view(get_db(), g.user, patient_id, int(page)))

    @app.get('/api/v1/patients/<patient_id>/therapy-editor')
    def therapy_editor(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        backend_analyses.authorize(get_db(), g.user, patient_id)
        from . import backend_therapy_context as context, backend_medication_regimens as regimens
        catalog = regimens.release()
        questions = {}
        for product in catalog['products'].values():
            for flag, spec in product['required_facts'].items():
                questions.setdefault(flag, spec['question'])
        from .backend_ui_therapy import FLAG_LABELS
        return jsonify(context=context.view(get_db(), g.user, patient_id),
            facts=[{'id': key, 'label': FLAG_LABELS.get(key, questions.get(key, key))} for key in context.FLAGS],
            products=[{'id': key, 'name': product['name'], 'ingredient': product['ingredient'],
                       'form': product['form']} for key, product in catalog['products'].items()])

    @app.get('/api/v1/patients/<patient_id>/plan-review-state')
    def plan_review_state(patient_id):
        role('doctor')
        patient_or_404(patient_id)
        backend_analyses.authorize(get_db(), g.user, patient_id)
        from . import backend_plan_review as review
        review.available(get_db())
        latest = review.head(get_db(), patient_id)
        return jsonify(expected_version=latest['version'] if latest else 0,
                       parent_id=latest['proposal_id'] if latest else None)

    @app.get('/api/v1/physician/decision-support')
    @app.get('/api/v1/patients/<patient_id>/decision-support')
    def decision_support_availability(patient_id=None):
        role('doctor')
        if patient_id is not None:
            patient_or_404(patient_id)
            backend_analyses.authorize(get_db(), g.user, patient_id)
        names = {row[0] for row in get_db().execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'analysis_runs', 'backend_alerts', 'backend_diagnosis_reviews',
                    'backend_plan_reviews'}
        available = required.issubset(names)
        from . import backend_jobs
        automatic = []
        if available and patient_id is not None and 'backend_ui_update_cursors' in names:
            from . import backend_ui_updates
            relationship = backend_analyses.authorize(get_db(), g.user, patient_id)
            automatic = backend_ui_updates.view(get_db(), patient_id, relationship)
        from . import backend_diagnosis_preview
        return jsonify(available=available, automatic=automatic,
                       diagnosis_preview=backend_diagnosis_preview.release()['enabled'],
                       enabled=available and backend_jobs.settings(get_db()) is not None)

    @app.get('/api/v1/physician/alerts')
    def backend_alert_inbox():
        role('doctor')
        from . import backend_alerts
        if set(request.args) - {'page'} or len(request.args.getlist('page')) > 1:
            raise backend_analyses.AnalysisError('Недопустимые параметры страницы.', 400, 'invalid_page')
        page = request.args.get('page', '1')
        if not re.fullmatch(r'[1-9][0-9]{0,5}', page):
            raise backend_analyses.AnalysisError('Неверная страница.', 400, 'invalid_page')
        return jsonify(backend_alerts.inbox(get_db(), g.user, int(page)))

    @app.get('/api/v1/physician/alerts/<alert_id>')
    def backend_alert_detail(alert_id):
        role('doctor')
        from . import backend_alerts
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        return jsonify(backend_alerts.read(get_db(), g.user, alert_id))

    @app.post('/api/v1/physician/alerts/<alert_id>/actions')
    def backend_alert_action(alert_id):
        role('doctor')
        from . import backend_alerts
        if request.args:
            raise backend_analyses.AnalysisError('Параметры не поддерживаются.')
        if request.mimetype != 'application/json':
            raise backend_analyses.AnalysisError('Нужен Content-Type application/json.', 415, 'unsupported_media_type')
        body = backend_analyses.parse_request(request.get_data(), schema=None)
        return jsonify(backend_alerts.act(get_db(), g.user, alert_id, body))

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.after_request
    def headers(response):
        if (g.get('interface_removed') and request.method in ('GET', 'HEAD')
                and 200 <= response.status_code < 300):
            response.status_code = 503
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        # Fonts, styles and icons hold no personal data: revalidate instead of refetching.
        response.headers['Cache-Control'] = 'no-cache' if request.endpoint == 'static' else 'no-store'
        if app.config['AUTH_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/healthz')
    def healthz():
        return health(get_db())

    if app.config['UI_GALLERY']:
        from .ui_fixtures import CASES

        @app.get('/ui/components', defaults={'page': 'catalog'})
        @app.get('/ui/components/<page>')
        def ui_gallery(page):
            """Component catalogue and page previews for design checks; no service data, off unless COMPASS_UI_GALLERY=1."""
            case = request.args.get('data', 'demo')
            if case not in CASES or page not in ('catalog', 'login', 'login-error', 'login-locked', 'result'):
                abort(404)
            d = CASES[case]
            toggle = {'page': page, 'case': case}
            if page == 'catalog':
                return render_template('components_gallery.html', d=d, toggle=toggle)
            if page == 'result':
                return render_template('result.html', title=d['result_title'], message=d['result_message'], toggle=toggle)
            failure = {'login': None, 'login-error': 'invalid', 'login-locked': 'limited'}[page]
            return render_template('login.html', challenge='preview-only', error=failure, failure=failure,
                                   login_value=d['login_value'] if failure else '', toggle=toggle)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error, status, failure, uid = None, 200, None, ''
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
        response = app.make_response((interface_response('login.html', challenge=challenge, error=error,
                                                         failure=failure, login_value=uid), status))
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
        if attention not in ('', 'pending'):
            abort(400)
        # Retire bookmarked signal filters; never silently hide patients through an obsolete URL.
        if attention:
            filters = {key: request.args[key] for key in ('q', 'age_status', 'record_kind', 'route_category', 'show')
                       if key in request.args}
            return redirect(url_for('dashboard', **filters))
        show = request.args.get('show', '')
        if show not in ('', 'flagged'):
            abort(400)
        try:
            rows = patient_list(get_db(), query, age_status, doctor_id=g.user['id'],
                                record_kind=record_kind, route_category=route_category)
        except ValueError:
            abort(400)
        sheet = overview.rows(get_db(), g.user, rows)
        flagged = sum(1 for r in sheet if r['attention'])
        if show == 'flagged':
            sheet = [r for r in sheet if r['attention']]
        return interface_response('dashboard.html', rows=sheet, flagged=flagged, total=len(rows), show=show,
                               query=query, age_status=age_status,
                               record_kind=record_kind, route_category=route_category, attention=attention)

    @app.get('/demo/<patient_id>')
    def demo_patient(patient_id):
        return render_patient(patient_id)

    @app.get('/demo/<patient_id>/diary')
    def patient_diary(patient_id):
        role('patient')
        return render_patient(patient_id, section='diary')

    @app.get('/demo/<patient_id>/visits')
    def patient_visits(patient_id):
        role('patient')
        return render_patient(patient_id, section='visits')

    @app.get('/patients/<patient_id>/records/<entry_id>')
    def record_location(patient_id, entry_id):
        patient_or_404(patient_id)
        entry = get_db().execute('SELECT kind FROM clinical_entries WHERE id=? AND patient_id=?',
                                 (entry_id, patient_id)).fetchone()
        if entry is None:
            abort(404)
        if entry['kind'] == 'visit':
            destination = 'demo_patient' if g.user['role'] == 'doctor' else 'patient_visits'
        else:
            destination = 'demo_patient' if g.user['role'] == 'doctor' else 'patient_diary'
        return redirect(url_for(destination, patient_id=patient_id) + '#entry-' + entry_id)

    @app.get('/demo/<patient_id>/report')
    def patient_report(patient_id):
        role('patient')
        return render_patient(patient_id, section='report')

    @app.get('/demo/<patient_id>/forms')
    def patient_forms(patient_id):
        role('patient')
        return render_patient(patient_id, section='forms')

    @app.get('/patients/<patient_id>/follow-up')
    def follow_up_page(patient_id):
        role('doctor')
        # Compatibility address: one implementation and one visible patient card.
        return render_patient(patient_id)

    @app.route('/patients/<patient_id>/first-visits', methods=['GET'])
    @app.route('/patients/<patient_id>/first-visits/<visit_id>', methods=['GET', 'POST'])
    def first_visit_page(patient_id, visit_id='new'):
        role('doctor')
        patient = patient_or_404(patient_id)
        db = get_db()
        error, status = None, 200
        if request.method == 'POST':
            try:
                saved = first_visits.save(db, g.user, patient_id, visit_id, request.form)
                if request.form.get('state') == 'completed':
                    return redirect(url_for('demo_patient', patient_id=patient_id) + '#visit-' + saved, code=303)
                return redirect(url_for('first_visit_page', patient_id=patient_id, visit_id=saved), code=303)
            except first_visits.Error as failure:
                if failure.status in (403, 404):
                    abort(failure.status)
                error, status = str(failure), failure.status
        items = first_visits.history(db, g.user, patient_id)
        selected = [item for item in items if item['visit_id'] == visit_id]
        if visit_id != 'new' and not selected:
            abort(404)
        current = selected[0] if selected else None
        if request.method in ('GET', 'HEAD') and current and current['state'] == 'completed':
            return redirect(url_for('demo_patient', patient_id=patient_id) + '#visit-' + visit_id)
        values = dict(request.form) if error else first_visits.form_values(current) if current else first_visits.initial_values(db, g.user, patient_id)
        values = first_visits.editor_values(values)
        return interface_response('first_visit.html', patient=patient,
            patient_name=overview.person(patient['code'])[0],
            current=current, visit_id=visit_id, values=values, error=error,
            request_key=values.get('request_key') or secrets.token_hex(16), today=records.today().isoformat(),
            fields=first_visits.FIELDS, static_fields=first_visits.STATIC_FIELDS,
            statuses=records.STATUSES, sources=first_visits.SOURCES), status

    def communication_view(patient, patient_id, error=None, error_op=None, values=None, status=200):
        """The conversation screen for both roles; a refused write comes back here with what was typed."""
        db = get_db()
        try:
            data = communication.view(db, g.user, patient_id)
        except communication.Error as failure:
            return interface_response('result.html', title='Раздел недоступен', message=str(failure)), failure.status
        doctor = db.execute('''SELECT u.display_name FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?''', (patient_id, now())).fetchone()
        return interface_response('communication.html', patient=patient, data=data, error=error, error_op=error_op,
                               values=values or {}, kinds=decisions.KINDS, patient_name=overview.person(patient['code'])[0],
                               doctor_name=doctor['display_name'] if doctor else '',
                               message_key=secrets.token_hex(16)), status

    @app.get('/patients/<patient_id>/communication')
    def communication_page(patient_id):
        return communication_view(patient_or_404(patient_id), patient_id)

    def moscow_time(local):
        """datetime-local value from the browser -> ISO time with the Moscow offset the server rule asks for."""
        try:
            return datetime.fromisoformat(local).replace(tzinfo=MOSCOW).isoformat()
        except ValueError:
            return local

    @app.post('/patients/<patient_id>/communication/<operation>')
    def communication_write(patient_id, operation):
        patient = patient_or_404(patient_id)
        anchor = ''
        try:
            if operation == 'send':
                communication.send(get_db(),g.user,patient_id,request.form)
            elif operation == 'schedule':
                role('doctor')
                form = request.form
                if form.get('due_local') and not form.get('due_at'):
                    form = form.copy()
                    form['due_at'] = moscow_time(form['due_local'])
                communication.schedule(get_db(),g.user,patient_id,form)
            elif operation == 'report':
                communication.report(get_db(),g.user,patient_id,request.form.get('task_id',''),request.form)
            elif operation in ('received','read'):
                communication.receipt(get_db(),g.user,patient_id,request.form.get('message_id',''),operation)
                anchor = '#message-' + request.form.get('message_id','')
            else:
                abort(404)
        except communication.Error as error:
            # Legacy task writes remain available, but their forms were removed in S53.
            if operation in ('schedule', 'report'):
                title = 'Пункт не запланирован' if operation == 'schedule' else 'Отметка не сохранена'
                return interface_response('result.html', title=title, message=str(error)), error.status
            if error.status in (403, 404):
                return interface_response('result.html', title='Не сохранено', message=str(error)), error.status
            return communication_view(patient, patient_id, error=str(error), error_op=operation, values=request.form, status=error.status)
        return redirect(url_for('communication_page',patient_id=patient_id)+anchor,code=303)

    @app.get('/notifications')
    def notification_inbox():
        role('doctor')
        # Retired UI: an old bookmark must not record delivery or reading.
        if wants_html():
            return redirect(url_for('dashboard'))
        return interface_response('notifications.html')

    @app.post('/notifications/<notification_id>/<action>')
    def notification_mark(notification_id, action):
        role('doctor')
        try:
            notifications.mark(get_db(), g.user, notification_id, action)
        except notifications.NotificationError as error:
            return interface_response('result.html', title='Отметка не сохранена', message=str(error)), error.status
        # Historical server operation only; no doctor screen exposes receipt actions.
        return redirect(url_for('dashboard'), code=303)

    @app.get('/critical')
    def critical_inbox():
        role('doctor')
        if wants_html():
            return redirect(url_for('dashboard'))
        return interface_response('critical.html')

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
            return interface_response('result.html', title='Отметка не сохранена', message=str(error)), error.status
        # Legacy server receipts are retained for existing technical callers; no doctor screen exposes them.
        if action == 'received' and not request.form.get('back'):
            return '', 204
        return redirect(url_for('dashboard'),code=303)

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
                saved = extraction.save_import(get_db(),g.user,patient_id,text,request.form.get('request_key',''))
                return redirect(url_for('imports_page',patient_id=patient_id)+'#import-'+saved,code=303)
            except (extraction.ExtractionError, decisions.DecisionError) as exc:
                error, status = str(exc), exc.status
        return imports_view(patient, patient_id, error, status, values)

    def imports_view(patient, patient_id, error=None, status=200, values=None, review_error=None, document_error=None):
        """The documents screen; a refused review comes back here with the typed values."""
        items = extraction.history(get_db(),patient_id)
        for item in items:
            for candidate in item['result']['candidates']:
                candidate['review_value'] = extraction.canonical(candidate['value'])
            for review in item['reviews']:
                review['payload'] = json.loads(review['payload_json'])
        visits = first_visits.history(get_db(), g.user, patient_id)
        latest = {}
        for visit in visits:
            latest.setdefault(visit['visit_id'], visit)
        document_drafts = [v for v in latest.values() if v['state'] == 'draft']
        editable_ids = {v['id'] for v in document_drafts}
        document_history = [v for v in visits if v['id'] not in editable_ids and
                            (v['payload'].get('documented_facts') or v['payload'].get('document_basis'))]
        return interface_response('imports.html',patient=patient,items=items,error=error,values=values or {},
                               document_drafts=document_drafts, document_history=document_history, document_error=document_error,
                               review_error=review_error,
                               review_key=review_error['key'] if review_error else request.args.get('review','')[:80],
                               patient_name=overview.person(patient['code'])[0],
                               authors=author_names([r for item in items for r in item['reviews']] + visits),
                               fields=extraction.FIELDS,assertions=extraction.ASSERTIONS,assertion_labels=extraction.ASSERTION_LABELS,
                               warning=extraction.WARNING,new_key=lambda:secrets.token_hex(16)),status

    @app.post('/patients/<patient_id>/first-visits/<visit_id>/documents')
    def save_visit_documents(patient_id, visit_id):
        role('doctor')
        patient = patient_or_404(patient_id)
        try:
            saved = first_visits.save_documents(get_db(), g.user, patient_id, visit_id, request.form)
        except first_visits.Error as failure:
            if failure.status in (403, 404):
                abort(failure.status)
            return imports_view(patient, patient_id, status=failure.status,
                                document_error={'visit_id': visit_id, 'message': str(failure), 'form': dict(request.form)})
        return redirect(url_for('imports_page', patient_id=patient_id) + '#visit-document-' + saved, code=303)

    @app.post('/patients/<patient_id>/imports/<import_id>/review')
    def review_import(patient_id,import_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            extraction.review(get_db(),g.user,patient_id,import_id,request.form)
        except (extraction.ExtractionError, decisions.DecisionError) as exc:
            if exc.status in (403, 404):
                return interface_response('result.html',title='Сверка не сохранена',message=str(exc)),exc.status
            return imports_view(patient_or_404(patient_id),patient_id,status=exc.status,
                                review_error={'key':import_id+':'+request.form.get('candidate_id',''),'message':str(exc),'form':request.form})
        return redirect(url_for('imports_page',patient_id=patient_id)+'#import-'+import_id,code=303)

    def patient_today(patient_id, relationship, pending, draft):
        """The one request at the top of the patient's home screen. Read-only; nothing is written."""
        hour = datetime.now(MOSCOW).hour
        view = {'greeting': 'Доброе утро' if 5 <= hour < 12 else 'Добрый день' if 12 <= hour < 18 else 'Добрый вечер' if hour >= 18 else 'Доброй ночи',
                'note': None}
        if relationship is None:
            view.update(kind='link', label='Привязать врача',
                        why='Пока врач не связан с кабинетом, отправлять сведения некому. Код приглашения даёт врач.')
        elif pending:
            view.update(kind='assessment', label='Заполнить анкету ' + pending[0]['code'].replace('DASS-42', 'DASS\u201142'), task=pending[0],
                        href=url_for('assessment_form', request_id=pending[0]['id']),
                        why='Врач предложил анкету.',
                        note=('Есть ещё анкеты от врача: %d. Они в разделе «Анкеты».' % (len(pending) - 1)) if len(pending) > 1 else None)
        elif draft and draft['active']:
            view.update(kind='draft', label='Продолжить черновик', href=url_for('patient_report', patient_id=patient_id),
                        why='Вы начали отметку самочувствия. Черновик виден только вам и врачу не отправлен.')
        else:
            view.update(kind='report', label='Отметить самочувствие', href=url_for('patient_report', patient_id=patient_id),
                        why='Отметить самочувствие можно в любой день.',
                        note='Черновик сохраняется, можно вернуться позже.')
        return view

    def render_patient(patient_id, form_values=None, form_error=None, assessment_error=None, assessment_values=None,
                       section='today'):
        patient = patient_or_404(patient_id)
        if g.user['role'] == 'doctor' and request.method == 'GET' and 'med_day' in request.args:
            # Old medication-day bookmarks now lead to the one plan screen.
            return redirect(url_for('decisions_page', patient_id=patient_id, med_day=request.args.get('med_day')) + '#medications')
        db = get_db()
        personal_draft = report_drafts.view(db, g.user, patient_id) if g.user['role'] == 'patient' else None
        draft_restored = bool(personal_draft and personal_draft['active'] and form_values is None)
        if draft_restored:
            form_values = personal_draft['values']
        encounters = records.legacy_encounters(db, patient_id) if g.user['role'] == 'doctor' else []
        relationship = db.execute('''SELECT r.*,u.display_name FROM care_relationships r JOIN users u ON u.id=r.doctor_id
            WHERE r.patient_id=? AND r.ends_at IS NULL AND r.starts_at<=?''', (patient_id, now())).fetchone()
        checks = db.execute('''SELECT c.* FROM relationship_checks c JOIN care_relationships r ON r.id=c.relationship_id
            WHERE r.patient_id=? AND r.ends_at IS NULL ORDER BY c.received_at DESC LIMIT 20''', (patient_id,)).fetchall()
        all_entries = records.history(db, patient_id)
        entries = [e for e in all_entries if e['kind'] == 'self_report']
        doctor_entries = [e for e in all_entries if e['kind'] == 'visit']
        measured = assessments.history(db, g.user, patient_id)
        pending = assessments.pending(db, g.user, patient_id)
        is_patient = g.user['role'] == 'patient'
        data, period_error, period_status = None, None, 200
        all_history = not any(k in request.args for k in ('start', 'end'))
        if not is_patient:
            try:
                if any(len(request.args.getlist(k)) != 1 for k in ('start', 'end') if k in request.args):
                    raise decisions.DecisionError('Укажите один период: по одной начальной и конечной дате.')
                data = follow_up.view(db, g.user, patient_id, request.args, all_history=all_history, include_plan=False)
            except decisions.DecisionError as failure:
                if failure.status in (403, 404):
                    abort(failure.status)
                period_error, period_status = str(failure), failure.status
            entries = data['entries'] if data else []
            doctor_entries = data['doctor_entries'] if data else []
            encounters = data['encounters'] if data else []
            measured = data['measured'] if data else []
        response = interface_response('patient.html' if is_patient else 'doctor_patient.html', section=section,
                               data=data, period_error=period_error, period_values=request.args, all_history=all_history,
                               period_days=(date.fromisoformat(data['end']) - date.fromisoformat(data['start'])).days + 1 if data else 0,
                               recent_start=(records.today() - timedelta(days=29)).isoformat(),
                               kinds=decisions.KINDS, labels=communication.LABELS,
                               visit_fields=first_visits.FIELDS, visit_sources=first_visits.SOURCES,
                               route_categories=routing.CATEGORIES, route_urgencies=routing.URGENCIES,
                               overview=None if is_patient else overview.summary(db, g.user, patient), own_marks=[e for e in entries if e['kind'] == 'self_report'],
                               plan=patient_plan(patient_id) if is_patient else [],
                               med_calendar=medication_calendar(patient_id) if is_patient else None,
                               medication_feedback=medication_feedback.view(db, patient_id, form_values if section == 'report' else None) if is_patient else None,
                               today_view=patient_today(patient_id, relationship, pending, personal_draft) if is_patient else None,
                               personal_draft=personal_draft, draft_restored=draft_restored,
                               draft_revision=(form_values.get('draft_revision', personal_draft['revision']) if form_values is not None else personal_draft['revision']) if personal_draft else None,
                               patient=patient, encounters=encounters, relationship=relationship, checks=checks,
                               doctor_entries=doctor_entries,
                               entries=entries, record_warnings=data['warnings'] if data else records.warnings(patient, all_entries) if is_patient else [],
                               wellbeing_trend=records.wellbeing_trend(entries),
                               measured=measured, assessment_trends=assessments.trends(measured) if g.user['role']=='doctor' else [],
                               pending_assessments=pending, assessment_form=assessments.definition(),
                               assessment_catalogue=assessments.catalogue(db, g.user, patient_id) if not is_patient else [],
                               form_names={f['id']: f['code'] for f in assessments.definitions()},
                               assignment_key=(assessment_values.get('assignment_key','') if assessment_values is not None else secrets.token_hex(16)),
                               assessment_values=assessment_values or {}, assessment_error=assessment_error,
                               record_fields=records.FIELDS, statuses=records.STATUSES, wellbeing=records.WELLBEING,
                               request_key=(form_values.get('request_key', '') if form_values is not None else secrets.token_hex(16)),
                               today=records.today().isoformat(), form_values=form_values or {}, form_error=form_error)
        return (response, period_status) if period_status != 200 else response

    @app.post('/patients/<patient_id>/medication-marks')
    def medication_report(patient_id):
        role('patient')
        patient_or_404(patient_id)
        endpoint = request.form.get('return_to')
        if endpoint not in ('demo_patient', 'decisions_page'):
            endpoint = 'demo_patient'
        try:
            medications.report(get_db(), g.user, patient_id, request.form)
        except decisions.DecisionError as failure:
            return interface_response('result.html', title='Отметка не сохранена', message=str(failure)), failure.status
        return redirect(url_for(endpoint, patient_id=patient_id, med_day=request.form['dose_on'])+'#medications', code=303)

    def medication_calendar(patient_id):
        try:
            return medications.calendar(get_db(), patient_id, request.args.get('med_day'))
        except decisions.DecisionError as failure:
            abort(400, description=str(failure))

    def patient_plan(patient_id):
        items = decisions.history(get_db(), g.user, patient_id)
        confirmed = sorted((i for i in items if i['decision'] == 'approved'),
                           key=lambda i: (i['confirmed_at'], i['version']), reverse=True)
        names = author_names(confirmed)
        return [{'id': i['id'], 'kind': i['kind'], 'content': i['payload'].get('content', ''), 'confirmed_at': i['confirmed_at'],
                 'doctor': names.get(i['doctor_id']) or 'врач (имя не указано)'} for i in confirmed]

    @app.get('/invitations/new')
    def invitation_page():
        role('doctor')
        return interface_response('invitation_manage.html', offers=pending_invitations())

    @app.post('/invitations')
    def create_invitation():
        role('doctor')
        token = access.invite(get_db(), g.user['id'], request.form.get('patient_id', '')[:100])
        if token is None:
            return interface_response('result.html', title='Приглашение не создано', message='Проверьте код пациента. Для него должно быть доступно приглашение.'), 409
        return interface_response('invitation.html', token=token)

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
            return interface_response('result.html', title='Приглашение недоступно', message='Код не подходит этому кабинету, истёк или уже использован.'), 409
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
        json_reply = kind == 'self_report' and request.accept_mimetypes.best == 'application/json'
        try:
            entry_id = records.save(get_db(), g.user, patient_id, kind, request.form)
        except records.RecordError as error:
            if json_reply:
                return jsonify(error=str(error)), error.status
            # Keep entered values on error without creating a partial record.
            if kind == 'self_report' and (error.status == 400 or (error.status == 409 and 'medication_feedback_version' in request.form)):
                return render_patient(patient_id, request.form, str(error), section='report'), error.status
            return interface_response('result.html', title='Запись не сохранена', message=str(error)), error.status
        destination = 'demo_patient' if kind == 'visit' else 'patient_diary'
        location = url_for(destination, patient_id=patient_id) + '#entry-' + entry_id
        if json_reply:
            return jsonify(location=location)
        return redirect(location, code=303)

    @app.post('/patients/<patient_id>/self-reports')
    def self_report(patient_id):
        return submit_record(patient_id, 'self_report')

    @app.route('/patients/<patient_id>/self-report-draft', methods=['GET', 'POST'])
    def self_report_draft(patient_id):
        role('patient')
        patient_or_404(patient_id)
        if request.method in ('GET', 'HEAD'):
            return jsonify(report_drafts.view(get_db(), g.user, patient_id))
        try:
            if request.form.get('draft_action', 'save') not in ('save', 'delete'):
                raise report_drafts.Error('Неизвестное действие с черновиком.')
            result = report_drafts.save(get_db(), g.user, patient_id, request.form,
                                        delete=request.form.get('draft_action') == 'delete')
        except report_drafts.Error as error:
            if request.accept_mimetypes.best == 'application/json':
                return jsonify(error=str(error)), error.status
            return render_patient(patient_id, request.form, str(error), section='report'), error.status
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(result)
        return redirect(url_for('patient_report', patient_id=patient_id), code=303)

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
                return interface_response('assessment_receipt.html', task=task, received_at=completed['recorded_at'],
                                          patient=patient_or_404(task['patient_id']))
            if task['expires_at']<=now() or task['age_on']!=records.today().isoformat():
                raise assessments.AssessmentError('Срок предложения истёк. Врач может предложить новую анкету.',409)
            form = assessments.available_form(db, task['form_version_id'])
        except assessments.AssessmentError as error:
            if request.method == 'POST' and error.status == 400:
                return interface_response('assessment_form.html', task=task, instrument=assessments.definition(task['form_version_id']), values=request.form,
                                          error=str(error), patient=patient_or_404(task['patient_id'])),400
            return interface_response('result.html', title='Анкета недоступна', message=str(error)),error.status
        return interface_response('assessment_form.html', task=task, instrument=form, values={}, error=None,
                                  patient=patient_or_404(task['patient_id']))

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
        return decisions_view(patient, patient_id, error, status)

    def plan_response(patient, items, task_error=None, task_values=None):
        """Patient-safe decisions and linked recommendation marks; no private clinical rationale."""
        return interface_response('plan.html', patient=patient, plan=patient_plan(patient['id']), kinds=decisions.KINDS,
                                  plan_task_data=plan_tasks.view(get_db(), g.user, patient['id']),
                                  task_error=task_error, task_values=task_values or {}, task_labels=communication.LABELS,
                                  med_calendar=medication_calendar(patient['id']))

    @app.post('/patients/<patient_id>/plan-tasks')
    def schedule_plan_task(patient_id):
        role('doctor')
        patient = patient_or_404(patient_id)
        try:
            task_id = plan_tasks.schedule(get_db(), g.user, patient_id, request.form.to_dict())
        except decisions.DecisionError as failure:
            if failure.status in (403, 404):
                abort(failure.status, description=str(failure))
            return decisions_view(patient, patient_id, status=failure.status,
                                  task_error=str(failure), task_values=request.form)
        return redirect(url_for('decisions_page', patient_id=patient_id)+'#task-'+task_id, code=303)

    @app.post('/patients/<patient_id>/plan-tasks/<task_id>/report')
    def report_plan_task(patient_id, task_id):
        role('patient')
        patient = patient_or_404(patient_id)
        try:
            communication.report(get_db(), g.user, patient_id, task_id, request.form, patient_only=True)
        except decisions.DecisionError as failure:
            if failure.status in (403, 404):
                abort(failure.status, description=str(failure))
            return plan_response(patient, [], task_error=str(failure),
                                 task_values={**request.form, 'task_id':task_id}), failure.status
        return redirect(url_for('decisions_page', patient_id=patient_id)+'#task-'+task_id, code=303)

    def decisions_view(patient, patient_id, error=None, status=200, confirm_error=None, task_error=None, task_values=None):
        """The decisions screen; a refused confirmation comes back here with the typed rationale instead of a bare error page."""
        items = decisions.history(get_db(), g.user, patient_id)
        values = request.form if request.method == 'POST' and confirm_error is None else {}
        stale = set()
        if g.user['role'] == 'doctor':
            stale = decisions.stale_ids(get_db(), g.user, patient_id, items)
        if request.method == 'GET' and request.args.get('revise'):
            role('doctor')
            earlier = next((i for i in items if i['id'] == request.args['revise']), None)
            if earlier is None:
                abort(404)
            values = decisions.revision_values(earlier)
        if request.method == 'GET' and request.args.get('from_context'):
            role('doctor')
            advice = clinical_rules.recommendation(get_db(), g.user, patient_id)
            if advice['context_id'] != request.args['from_context'] or advice['category'] == 'unknown':
                return interface_response('result.html', title='Рекомендация изменилась', message='Обновите карточку и проверьте исходные сведения.'), 409
            alternative = 'Допустимая альтернатива по КР — врач-психотерапевт.' if advice.get('alternative') == 'psychotherapist' else ''
            values = {'kind': 'referral', 'content': advice['reason'] + ' ' + alternative,
                      'basis': advice['source_url'] + ' · ' + advice['source_section'],
                      'uncertainties': 'Срочность определяет врач. Это проект; он не изменяет план до отдельного подтверждения.',
                      'route_rule_context_id': advice['context_id'],
                      'route_category': advice['category'], 'route_urgency': 'unknown',
                      'route_population_status': 'known', 'route_age_years': str(advice['age_years']),
                      'route_population': 'Справка для взрослых; применимость и решение определяет врач.',
                      'route_severity': advice['basis'], 'route_severity_status': 'unknown',
                      'route_evidence': advice['source_url'] + ' · ' + advice['source_section'] + ' · ' + advice['reason'],
                      'route_unavailable': 'Не ожидать помощи через демо: использовать доступный обычный канал связи с врачом или обратиться в медицинскую организацию.'}
        if g.user['role'] == 'patient':
            return plan_response(patient, items), status
        med_plans = medications.approved(get_db(), patient_id)
        med_base = values.get('med_base', medications.base_id(get_db(), patient_id))
        if not values:
            values = medications.form_values(med_plans[-1]['medications']) if med_plans else {}
        if request.method == 'GET' and request.args.get('med_edit') == '1':
            values = {**values, 'med_change': 'replace'}
        return interface_response('decisions.html', patient=patient, decisions=items, kinds=decisions.KINDS,
                               plan_task_data=plan_tasks.view(get_db(), g.user, patient_id),
                               task_error=task_error, task_values=task_values or {},
                               plan_data=follow_up.view(get_db(), g.user, patient_id, {}, all_history=True), labels=communication.LABELS,
                               reference=decisions.reference() if g.user['role']=='doctor' else None,
                               route_reference=routing.reference() if g.user['role']=='doctor' else None,
                               route_categories=routing.CATEGORIES, route_urgencies=routing.URGENCIES, route_statuses=routing.STATUSES,
                               med_base=med_base, med_calendar=medication_calendar(patient_id),
                               error=error, values=values, stale=stale, confirm_error=confirm_error,
                               compose_open=bool(error or values.get('parent_id') or values.get('route_rule_context_id') or request.args.get('compose') == '1' or request.args.get('med_edit') == '1'),
                               patient_name=overview.person(patient['code'])[0], authors=author_names(items),
                               today=records.today().isoformat(),
                               request_key=request.form.get('request_key', secrets.token_hex(16))), status

    @app.post('/patients/<patient_id>/decisions/<proposal_id>/confirm')
    def confirm_decision(patient_id, proposal_id):
        role('doctor')
        patient_or_404(patient_id)
        try:
            decisions.confirm(get_db(), g.user, patient_id, proposal_id, request.form)
        except decisions.DecisionError as error:
            if error.status in (403, 404):
                return interface_response('result.html', title='Решение не подтверждено', message=str(error)), error.status
            return decisions_view(patient_or_404(patient_id), patient_id, status=error.status,
                                  confirm_error={'id': proposal_id, 'message': str(error), 'rationale': request.form.get('rationale', '')})
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
