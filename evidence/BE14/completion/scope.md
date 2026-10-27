# BE14 completion scope

Прямое поручение пользователя: доработать независимую лекарственную проверку и
довести BE14 до полной приёмки. Все BE14-A01–A04 сохраняются. Основной агент —
единственный автор файлов; исследователь be14_complete_sources только чтение.

План: проверенный узкий каталог режимов/компонентов/ограничений; независимая
проверка синтетического кандидата с отдельными клиническими границами; отдельная
версионная сверка врача в БД/API; сохранение её в снимке plan; настоящая генерация
через существующий DeepSeek/ledger; пересчёт при публикации в существующих
analyses/jobs; положительная/опасная реальная оценка и регрессия; память/приёмка.

Writable: apps/compass/backend_medication_safety.py,
apps/compass/backend_medication_regimens.py, apps/compass/backend_therapy.py,
apps/compass/backend_therapy_context.py, apps/compass/backend_analyses.py,
apps/compass/backend_care_plan.py, apps/compass/backend_jobs.py,
apps/compass/backend_sources.py, apps/compass/web.py,
apps/compass/migrations/021_backend_therapy_context.sql,
apps/tests/test_backend_therapy.py, apps/tests/test_backend_therapy_integration.py,
apps/tests/test_backend_medication_regimens.py,
data/backend/medication-regimens-v2.json, docs/architecture/backend-api.json,
docs/architecture/backend-therapy.md, docs/architecture/backend-medication-safety.md,
evidence/BE14/, memory/sessions/BE14.md, memory/STATE.json, memory/DECISIONS.md,
memory/BLOCKERS.md, memory/EXTERNAL.md, memory/BUDGET.json, START_HERE.md,
AGENTS.md, plan/backend/README.md, plan/backend/requirements.json,
plan/slices/BE14.md, plan/coverage.json, plan/COVERAGE.md.

Все остальные пути только чтение. Рабочая БД/доступы/чужие четыре файла запрещены
к изменению; 021 применяется только в копиях. Ledger может получить только
фактические разрешённые синтетические модельные вызовы в прежнем cap1USD и
percall20000microUSD; старые строки не удалять/не переписывать. Рабочие8000/worker
не переключать. HTML/CSS/JS, BE15, UI08/организационная работа вне объёма.
