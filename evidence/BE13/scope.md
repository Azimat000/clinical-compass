# BE13 scope, 27.10.2026

Baseline baseline.json, HEAD90e9821. Единственный автор файлов — основной агент.
Исследователь /root/be13_sources только чтение. Изменяющих подагентов нет.
Точные пути: apps/compass/backend_medication_safety.py,
apps/tests/test_backend_medication_safety.py,
data/backend/medication-safety-v1.json,
docs/architecture/backend-medication-safety.md, evidence/BE13/,
memory/sessions/BE13.md, memory/STATE.json, memory/DECISIONS.md,
memory/BLOCKERS.md, memory/EXTERNAL.md, memory/BUDGET.json,
plan/backend/requirements.json, plan/coverage.json и его штатная производная
plan/COVERAGE.md, START_HERE.md, AGENTS.md.

Новый внутренний серверный механизм для BE14, без нового HTTP/интерфейса,
без применения/генерации назначения и без миграций. Проверки только явной
структуры и авторских синтетических сведений. Неполное покрытие явно unknown;
pass отдельной проверки не выдаёт клинический допуск. Полные исходные
BE13-A01–A03 сохраняются, M04 Авиандр проверяется отдельно по первичному ГРЛС.
Рабочие база/сервис/доступы/ledger/четыре чужих файла не менять.
