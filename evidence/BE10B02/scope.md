# BE10B02 scope и baseline

Baseline.json записан до session start/изменений: HEAD/status/diff/cached,
хеши80таблиц активнойБД/доступов/4чужихфайлов, ledger28/50905microUSD.
Изменяет файлы только основной агент, implementation-workersнет. Исследователь
/root/be10b02_sources толькоread-only. Отдельного принятого плана реализации нет;
утверждённый объём — карточкаBE10B02 и неизменённые исходныеBE10-A01–A03.
Новых карточек/ID/ветвлений нет.

Файлы реализации: apps/compass/backend_diagnosis_service.py,
backend_analyses.py/backend_jobs.py/backend_sources.py/web.py в той же папке;
docs/architecture/backend-api.json/backend-diagnoses.md;
apps/tests/test_backend_diagnosis_integration.py.
Доказательства: evidence/BE10B02/, evidence/BE10/diagnosis-quality.json.
Память: START_HERE.md, memory/STATE.json, memory/sessions/BE10B02.md,
memory/DECISIONS.md/BLOCKERS.md/EXTERNAL.md/BUDGET.json,
plan/backend/requirements.json, plan/coverage.json и сгенерированныйplan/COVERAGE.md (не изменился).

Рабочиеvar/compass.sqlite3/доступы/8000/worker/старые4чужихфайла не меняются.
Единственная разрешённая локальная служебная мутацияvar — прежний учётный
ledger DeepSeek в пределахUSD0.10; шесть новых запросов, никакого сброса.
Миграций/зависимостей/клинических действий/интерфейсных правок нет.
