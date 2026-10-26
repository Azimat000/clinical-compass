# Продолжение того же BE10B02

Базовый коммит b319df584c53314f79c93eda7faf345fb1df26cf. Baseline до правок:
status/diff/staged,80таблиц/доступы/4чужихфайла,все34строкиledger83138microUSD.
Изменяет файлы только основной агент. Исследователь read-only, изменяющихагентов
нет. Отдельного плана нет: прямое поручение исправить формат/тестовые истории и
рассчитать лимит. Повышение доUSD1.00 отдельно разрешено прямым ответом; percall
USD0.02 и общий≤5000₽ сохранены. Никакого сброса прежнегоучёта/пополнений/покупок.

Пути кода: apps/compass/backend_diagnosis_codec.py, backend_diagnosis_service.py,
backend_model.py; apps/tests/diagnosis_fixtures.py,test_backend_diagnosis_codec.py,
test_backend_diagnosis_integration.py,test_backend_model.py;
docs/architecture/backend-api.json,backend-diagnoses.md;
evidence/BE10B02/revision-v2/,evidence/BE10/diagnosis-quality.json;
START_HERE.md,memory/STATE.json,memory/sessions/BE10B02.md,DECISIONS.md,BLOCKERS.md,
EXTERNAL.md,BUDGET.json в memory/;plan/backend/requirements.json,plan/coverage.json,
plan/COVERAGE.md при фактической генерации.

Рабочуюvar/compass.sqlite3/8000/worker/10историй/доступы/4чужихфайла не менять.
Локальная оплачиваемаямутация — только прежнийledger в пределах согласованного
USD1.00, только авторские синтетические временныеБД. Новыхсрезов/ID/миграцийнет.

Дополнительно, до правок зафиксированы SHA/diff: apps/tests/test_backend_contracts.py
и apps/tests/test_clinic_medication_revision.py (additional-test-baseline.json).
Изменения только опорных тестовых дат, добавлена проверка неизвестности17–18лет
при предыдущем дне. Код ages/risk_rules/original_guard не изменялся.
Также актуальная итоговая приёмка: evidence/BE10B02/acceptance.md.
