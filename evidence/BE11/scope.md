# BE11 — границы текущей сессии

Единственный автор изменяющих файлов — основной агент. Изменяющих подагентов нет.
Read-only исследователь /root/be11_sources: только внешняя проверка КР.
Baseline: baseline.json; чужие четыре файла, рабочая база, доступы и ledger сохраняются.

План: отдельный журнал решений врача с миграцией020; API GET/POST с точной
версией снимка и решения, повторы/конфликт/связь/неизменяемая история; версия диагноза
в зависимостях существующего плана; проверка на временных синтетических базах.
Ни одного изменения лечения и ни одного платного вызова модели.

Разрешённые пути основного агента:
- apps/compass/backend_diagnosis_review.py
- apps/compass/migrations/020_backend_diagnosis_review.sql
- apps/compass/decisions.py
- apps/compass/web.py
- apps/tests/test_backend_diagnosis_review.py
- docs/architecture/backend-diagnosis-review.md
- evidence/BE11/
- memory/sessions/BE11.md
- memory/STATE.json
- memory/DECISIONS.md
- memory/BLOCKERS.md
- memory/EXTERNAL.md
- memory/BUDGET.json
- plan/backend/README.md
- plan/backend/requirements.json
- plan/coverage.json
- plan/COVERAGE.md (generated)
- START_HERE.md
- AGENTS.md

Никаких изменений HTML/CSS/JS, исходных медицинских правил/источников, модели,
зависимостей/прежних миграций/рабочей базы и чужих файлов. BE12 здесь не начинать.
