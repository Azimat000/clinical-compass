"""Read-only discovery for the physician client; records stay in analysis_runs."""
from . import backend_analyses as analyses


def read(db, user, patient_id, *, operation=None, page=1):
    """Read existing runs in one snapshot; polling never schedules work.

    The newest run stays first even if it failed or became stale. Returning an
    older successful result as current would conceal missing or changed data.
    """
    if operation not in (None, 'risk', 'diagnosis', 'plan') or type(page) is not int or not 1 <= page <= 1000000:
        raise analyses.AnalysisError('Недопустимый фильтр или страница.', 400, 'invalid_page')
    if not db.in_transaction:
        db.execute('BEGIN')
        try:
            value = read(db, user, patient_id, operation=operation, page=page)
            db.commit()
            return value
        except BaseException:
            db.rollback()
            raise
    relationship = analyses.authorize(db, user, patient_id)
    params = [patient_id, relationship]
    where = 'patient_id=? AND relationship_id=?'
    if operation is not None:
        where += ' AND operation=?'
        params.append(operation)
    count = db.execute('SELECT count(*) FROM analysis_runs WHERE ' + where, params).fetchone()[0]
    size = 10
    pages = max(1, (count + size - 1) // size)
    if page > pages:
        raise analyses.AnalysisError('Страница истории недоступна.', 400, 'invalid_page')
    rows = db.execute('SELECT id FROM analysis_runs WHERE ' + where +
                      ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                      [*params, size, (page - 1) * size]).fetchall()
    from . import backend_jobs
    config = backend_jobs.settings(db)
    return {'contract_version': '1.0', 'patient_id': patient_id, 'operation': operation,
            'page': page, 'page_size': size, 'page_count': pages, 'total': count,
            'backend': {'enabled': config is not None,
                        'generation_version': config['generation_version'] if config is not None else None},
            'items': [analyses.read(db, user, patient_id, row['id']) for row in rows]}
