"""Patient descriptions about physician-approved drugs; no causality or dose advice."""
import re
from . import medications, records

VERSION = 'medication-feedback-v1'
LABELS = {'effect': 'Есть эффект', 'no_effect': 'Нет эффекта', 'adverse': 'Нежелательные явления'}
LIMITS = {'medication_feedback_version': 64, 'medication_feedback_plan': 64,
          **{f'feedback_{i}_{code}{suffix}': limit
             for i in range(medications.MAX_MEDICATIONS) for code in LABELS
             for suffix, limit in (('', 3), ('_text', 2000))}}


def view(db, patient_id, values=None):
    plans = medications.approved(db, patient_id)
    plan = plans[-1] if plans else None
    # Restore the exact approved prescription a private draft refers to, even if
    # the doctor replaced it meanwhile. Submission will require a fresh form.
    selected = (values or {}).get('medication_feedback_plan')
    if selected:
        plan = next((p for p in plans if p['id'] == selected), None)
    return {'plan_id': plan['id'] if plan else '',
            'medications': plan['medications'] if plan else [], 'labels': LABELS,
            'stale': bool(selected and (not plans or selected != plans[-1]['id']))}


def parse(form):
    if 'medication_feedback_version' not in form:
        if any(k.startswith('feedback_') or k == 'medication_feedback_plan' for k in form):
            raise records.RecordError('Обновите форму дневника перед отправкой.')
        return None  # Preserve the existing API and historical forms.
    if records.text_field(form, 'medication_feedback_version', 64) != VERSION:
        raise records.RecordError('Версия дневника изменилась. Откройте новую форму.', 409)
    for key in form:
        if key.startswith('feedback_') and key not in LIMITS:
            raise records.RecordError('Неизвестное поле препарата. Обновите форму.')
    result = []
    for i in range(medications.MAX_MEDICATIONS):
        responses = {}
        for code, label in LABELS.items():
            prefix = f'feedback_{i}_{code}'
            selected = records.text_field(form, prefix, 3)
            detail = records.text_field(form, prefix + '_text', 2000)
            if selected not in ('', 'yes'):
                raise records.RecordError('Проверьте выбранную отметку препарата.')
            if selected:
                if not detail:
                    raise records.RecordError(f'Препарат {i + 1}: опишите «{label}».')
                responses[code] = detail
            # Unchecking a response withdraws it, including its unsubmitted text.
        if responses:
            result.append({'med_index': i, 'responses': responses})
    plan = records.text_field(form, 'medication_feedback_plan', 64)
    if plan and not re.fullmatch('[0-9a-f]{32}', plan):
        raise records.RecordError('Назначение не найдено. Обновите форму.', 409)
    return {'plan_id': plan, 'items': result}


def resolve(db, patient_id, parsed):
    """Resolve labels from immutable approved data, never from a browser's text."""
    plans = medications.approved(db, patient_id)
    plan = next((p for p in plans if p['id'] == parsed['plan_id']), None)
    if parsed['plan_id'] and plan is None:
        raise records.RecordError('Подтверждённое назначение не найдено. Обновите форму.', 409)
    result = []
    for item in parsed['items']:
        i = item['med_index']
        if not plan or i >= len(plan['medications']):
            raise records.RecordError('Препарат не входит в назначение врача. Обновите форму.', 409)
        result.append({**item, 'proposal_id': plan['id'], 'name': plan['medications'][i]['name']})
    return result


def adverse_text(items):
    return '\n'.join(item['name'] + ': ' + item['responses']['adverse']
                     for item in items if 'adverse' in item['responses'])
