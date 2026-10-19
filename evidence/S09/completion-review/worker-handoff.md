STATUS: COMPLETE
OWNED_PATHS:
- apps/compass/clinical_rules.py
- apps/compass/resources/clinical-rules-v1.json
- apps/compass/migrations/008_clinical_rules.sql
- apps/tests/test_clinical_rules.py
CHANGED_FILES:
Все4выделенных файла созданы; при начале отсутствовали.
WORK_SUMMARY:
Источниковое сопоставление для синтетики,контекст врача,возраст по всем источникам,две категории,неизменяемые оценки/критические события в общей транзакции. Source_author сохраняется,повтор не создаёт дубль. Доставка остаётсяS10.
TESTS_RUN:
- PYTHONPATH=apps/tests .venv/bin/python -m unittest discover -s apps/tests -p test_clinical_rules.py -v:15тестов,OK,0.409с.
- Промежуточный тест пытался synthetic=0;существующая схема это запрещает,тест исправлен на проверку запрета.
- git diff --check по4ownedпути:exit0(не проверяет неотслеживаемые новые файлы).
ACCEPTANCE_EVIDENCE:
- recommendation/test_referral:2категории/unknownсрочность/альтернатива/никакихproposals/care_actions.
- release и manifest:SHA/разделы/19и18лет;возрастunknown/conflict/диапазон/сверка/новое противоречие.
-4реакции:реальныеcritical_events/evaluations/outbox;недоступныйврач/нетсвязи/unassigned/неподавлениепрежнегоpositive.
- Отказ enqueue/INSERTevent откатывает весь самоотчёт,аудит откатывает контекст.
- Unknown/negative/conflict/stale/historical/нетRx не превращаются в отсутствие риска.
- Роль/активная связь/disabled/retry/appendonly проверены.
- Старый формат не переоценивается;обычный worker сохраняет критическую очередь pending/0.
SCOPE_COMPLIANCE: PASS
RISKS_OR_BLOCKERS:
Клинической валидации нет(явнообозначено);S10/S16не реализованы. Полная приёмка основным агентом остаётся обязательной. Коммитов не создавал.
