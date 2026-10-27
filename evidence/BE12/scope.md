# Scope BE12

Единственный автор изменений — основной агент. /root/be12_sources только читает.
Отдельного утверждённого плана нет: выполняется исходная карточка BE12-A01–A03.
Изменения: apps/compass/backend_care_plan.py, backend_analyses.py,
backend_jobs.py, backend_sources.py; docs/architecture/backend-api.json,
backend-care-plan.md; data/backend/care-plan-v1.json;
apps/tests/test_backend_care_plan.py; evidence/BE12/;
memory/STATE.json, sessions/BE12.md, DECISIONS.md, BLOCKERS.md, EXTERNAL.md,
BUDGET.json; plan/backend/requirements.json,README.md; plan/coverage.json,
plan/COVERAGE.md (если генератор требует); START_HERE.md, AGENTS.md.
Миграции/зависимости/интерфейс/рабочая база/учётные данные/ledger не изменяются.
Прежние4чужихфайла не меняются и не включаются. Baseline:baseline.json.
План: детерминированный источниковый проект через существующие analyses/jobs;
точная свежесть диагноза/рисков/источников; условные уточнения отдельно от
обсуждения помощи при выбранном врачом диагнозе; проверка перед публикацией;
только врачебныйAPI/синтетика; всеA01–A03 проверяются целевыми и общими тестами.
