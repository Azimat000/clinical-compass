"""Structured synthetic medication checks. Never a prescription or clinical release.

Trusted internal caller supplies reviewed coded facts with provenance. Narrative
and model extraction are not accepted as doses, ingredient codes or negative facts.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'data/backend/medication-safety-v1.json'
VERSION = 'medication-safety-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def release():
    catalog = json.loads(CATALOG.read_text())
    if (catalog['version'] != VERSION or catalog['mode'] != 'synthetic_only'
            or catalog['clinical_review'] is not None):
        raise ValueError('medication_catalog_not_admitted')
    evidence = ROOT / catalog['evidence']
    if hashlib.sha256(evidence.read_bytes()).hexdigest() != catalog['evidence_sha256']:
        raise ValueError('medication_evidence_changed')
    return catalog


def number(value):
    # No strings, booleans, NaN, infinity, exponent text or unit conversion.
    if type(value) not in (int, float):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def evaluate(candidate, patient, *, at=None):
    """Return per-gate pass/block/unknown; every unknown denies a supported option.

    Internal synthetic-only function, not an authorization boundary or public API.
    Caller must resolve refs and authorize patient access before passing facts.
    """
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError('timezone_required')
    catalog = release()
    if not isinstance(candidate, dict) or not isinstance(patient, dict):
        raise ValueError('structured_input_required')
    if not isinstance(candidate.get('product_id'), str):
        raise ValueError('product_id_required')
    candidate, patient = deepcopy(candidate), deepcopy(patient)
    checks = []
    product = catalog['products'].get(candidate.get('product_id'))
    source = catalog['sources'].get(product['source_id']) if product else None

    def add(code, state, reason, *, section='scope', refs=()):
        checks.append({'code': code, 'state': state, 'reason': reason,
                       'input_refs': list(refs), 'source': None if source is None else {
                           'id': product['source_id'], 'registration': source['registration'],
                           'url': source['pdf_url'], 'pdf_sha256': source['pdf_sha256'],
                           'section': section, 'pages': source['locators'].get(section, [])}})

    def fact(key):
        value = patient.get(key)
        if (not isinstance(value, dict) or not isinstance(value.get('refs'), list)
                or not value['refs'] or not all(isinstance(r, str) and r for r in value['refs'])):
            return None, []
        return value.get('value'), value['refs']

    if patient.get('mode') != 'synthetic_only' or patient.get('synthetic') is not True:
        add('mode', 'block', 'Разрешены только явно синтетические сведения.')
    if not product:
        add('product', 'unknown', 'Точный препарат отсутствует в поддерживаемом каталоге.')
    else:
        add('product', 'pass', 'Точная регистрация препарата найдена.')
        checked = datetime.fromisoformat(source['checked_at'])
        due = datetime.fromisoformat(source['review_due_at'])
        within_deadline = checked <= at < due <= checked + timedelta(days=1)
        add('source_freshness', 'pass' if within_deadline else 'unknown',
            'Проверка срока источникового подтверждения; просроченное не продлевается автоматически.')
        fresh = source['status'] == 'current' and within_deadline
        add('source', 'pass' if fresh else 'unknown',
            'Действующий документ проверен.' if fresh else 'Актуальность документа не подтверждена.')
        for field in ('form', 'unit', 'strength_mg'):
            actual = candidate.get(field)
            if field == 'strength_mg':
                valid = number(actual) is not None and actual in product['strengths_mg']
            else:
                valid = actual == product[field]
            add(field, 'pass' if valid else 'block', 'Проверка точной формы/единицы/силы.', section='form')
        indication = candidate.get('indication')
        add('indication', 'pass' if indication in product['indications'] else 'unknown',
            'Проверка поддерживаемого зарегистрированного показания.', section='indications')
        age, refs = fact('age')
        age_ok = type(age) is int and 0 <= age <= 120
        add('age', 'unknown' if not age_ok else 'pass' if age >= product['age_min'] else 'unknown' if age == product.get('age_ambiguous') else 'block',
            'Проверка возраста для поддерживаемой взрослой ветки.', section='age', refs=refs)
        allergies, refs = fact('allergies')
        allergy_ok = isinstance(allergies, list) and all(isinstance(x, str) and x for x in allergies)
        allergen_codes = {product['ingredient'], product['source_id'], *product['excipients']}
        add('allergies', 'unknown' if not allergy_ok else 'block' if allergen_codes.intersection(allergies) else 'pass',
            'Проверка известной аллергии на вещество или точный препарат; компоненты не полностью покрыты.', section='contraindications', refs=refs)
        add('excipient_coverage', 'unknown', 'Компоненты препарата не перечислены полностью; их переносимость не подтверждена.', section='contraindications')
        known_allergens, refs = fact('allergies_complete')
        add('allergies_complete', 'pass' if known_allergens is True else 'unknown',
            'Пустой список без явной сверки не подтверждает отсутствие аллергий.', section='contraindications', refs=refs)
        for key in product['required_facts']:
            value, refs = fact(key)
            state = 'unknown'
            if type(value) is bool:
                state = ('block' if key in product['contraindicated_facts'] or key in product.get('excluded_concurrent_facts', []) else 'unknown') if value else 'pass'
            add(key, state, ('Противопоказание: ' if key in product['contraindicated_facts'] else 'Особое условие: ') + key,
                section='contraindications' if key in product['contraindicated_facts'] else 'cautions', refs=refs)
        dose = number(candidate.get('daily_dose_mg'))
        low, high = map(Decimal, map(str, product['daily_mg']))
        hepatic, _ = fact('hepatic_impairment')
        if 'elderly_max_mg' in product and age_ok and age > 65:
            high = min(high, Decimal(str(product['elderly_max_mg'])))
            low = Decimal(str(product.get('adjusted_min_mg', low)))
        if hepatic is True and 'hepatic_max_mg' in product:
            high = min(high, Decimal(str(product['hepatic_max_mg'])))
            low = Decimal(str(product.get('adjusted_min_mg', low)))
        valid_dose = dose is not None and low <= dose <= high
        add('dose', 'pass' if valid_dose else 'block',
            'Поддерживаемая суточная доза; этап начала/изменения проверяется отдельно.', section='dose')
        add('frequency', 'pass' if candidate.get('times_per_day') == product['times_per_day']
            and type(candidate.get('times_per_day')) is int else 'block',
            'Проверка кратности приёма.', section='dose')
        strength, frequency = number(candidate.get('strength_mg')), number(candidate.get('times_per_day'))
        count = dose / strength / frequency if dose and strength and frequency and strength > 0 and frequency > 0 else None
        divisible = count is not None and count > 0 and (count == count.to_integral_value()
            or candidate.get('strength_mg') in product['split_strengths_mg'] and count * 2 == (count * 2).to_integral_value())
        add('tablet_divisibility', 'pass' if divisible else 'unknown',
            'Доза должна соответствовать целым таблеткам или подтверждённой равной делимости.', section='form')
        # BE13 deliberately does not infer initiation, titration or cross-tapers.
        add('regimen_phase', 'pass' if candidate.get('phase') == 'maintenance' else 'unknown',
            'Поддерживается проверка поддерживающей дозы; старт/изменение/переход требуют отдельного основания.', section='dose')
        medicines, refs = fact('medications')
        complete, complete_refs = fact('medications_complete')
        add('medications_complete', 'pass' if complete is True else 'unknown',
            'Требуется сверка назначенного, фактического и недавно отменённого.', section='interactions', refs=complete_refs)
        if not isinstance(medicines, list):
            add('medications', 'unknown', 'Лекарственный состав неизвестен.', section='interactions', refs=refs)
        else:
            for index, med in enumerate(medicines):
                if not isinstance(med, dict) or not isinstance(med.get('refs'), list) or not med.get('refs'):
                    add('medication_' + str(index), 'unknown', 'Нет точного вещества/происхождения.', section='interactions')
                    continue
                ingredient = med.get('ingredient')
                if (ingredient is not None and not isinstance(ingredient, str)
                        or med.get('product_id') is not None and not isinstance(med['product_id'], str)
                        or not all(isinstance(r, str) and r for r in med['refs'])):
                    add('medication_' + str(index), 'unknown', 'Некорректный код или происхождение.', section='interactions')
                    continue
                other = catalog['products'].get(med.get('product_id'))
                if other:
                    if ingredient is not None and ingredient != other['ingredient']:
                        add('medication_' + str(index), 'unknown', 'Противоречивые коды вещества и препарата.', section='interactions', refs=med['refs'])
                        continue
                    ingredient = other['ingredient']
                activity = med.get('state')
                if activity not in ('current', 'recently_stopped'):
                    add('medication_' + str(index), 'unknown', 'Неизвестна актуальность препарата.', section='interactions', refs=med['refs'])
                    continue
                rule = product['interactions'].get(ingredient)
                if ingredient == product['ingredient']:
                    state, reason = ('block', 'Дублирование одного вещества под разными названиями.') if activity == 'current' else ('unknown', 'Недавняя отмена того же вещества: нужна сверка перехода.')
                elif activity == 'recently_stopped':
                    state, reason = 'unknown', 'Недавняя отмена: нужен точный проверенный интервал перехода.'
                elif rule:
                    state, reason = rule['state'], rule['reason']
                else:
                    state, reason = 'unknown', 'Взаимодействие отсутствует в поддерживаемой части каталога.'
                add('medication_' + str(index), state, reason, section='interactions', refs=med['refs'])
        add('coverage', 'unknown', 'Каталог покрывает только перечисленные ограничения и взаимодействия; полного допуска нет.', section='scope')
    state = 'block' if any(c['state'] == 'block' for c in checks) else 'unknown' if any(c['state'] == 'unknown' for c in checks) else 'pass'
    return {'version': VERSION, 'mode': 'synthetic_only', 'clinical_release': False,
            'catalog_sha256': digest(catalog), 'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'input_sha256': digest({'candidate': candidate, 'patient': patient}), 'checked_at': at.isoformat(),
            'expires_at': min(at + timedelta(days=1), datetime.fromisoformat(source['review_due_at']) if source else at + timedelta(days=1)).isoformat(),
            'state': state, 'eligible': False, 'applied': False, 'checks': checks,
            'coverage': {'restrictions': 'partial', 'interactions': 'partial', 'dose': 'adult_maintenance_only'}}


def verify(candidate, patient, report, *, at=None):
    expected = evaluate(candidate, patient, at=datetime.fromisoformat(report['checked_at']))
    if report != expected:
        raise ValueError('medication_safety_report_mismatch')
    now = at or datetime.now(timezone.utc)
    if not datetime.fromisoformat(report['checked_at']) <= now < datetime.fromisoformat(report['expires_at']):
        raise ValueError('medication_report_expired_or_future')
    return True


def evaluate_regimen(candidate, patient, *, at=None):
    """BE14 extension; technical synthetic eligibility is separate from release."""
    from . import backend_medication_regimens
    return backend_medication_regimens.evaluate(candidate, patient, at=at)


def verify_regimen(candidate, patient, report, *, at=None):
    from . import backend_medication_regimens
    return backend_medication_regimens.verify(candidate, patient, report, at=at)
