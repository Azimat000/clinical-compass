STATUS: COMPLETE
OWNED_PATHS:
- apps/tests/test_notifications.py
- evidence/S10A/verify_delivery.py
CHANGED_FILES:
- apps/tests/test_notifications.py (новый)
- evidence/S10A/verify_delivery.py (новый)
WORK_SUMMARY:
Восемь групп тестов и автономный HTTP-сценарий с тремя процессами Waitress/двумя перезапусками. Worker завершён до окончательной проверки основным агентом, коммита не делал.
TESTS_RUN:
- PYTHONPATH=apps/tests .venv/bin/python -m unittest discover -s apps/tests -p test_notifications.py -v:8тестов,OK.
- .venv/bin/python evidence/S10A/verify_delivery.py:exit0,worker-замер373.565мс,integrityok/FK0. Это не основной приёмочный замер; основной агент повторил сценарий, delivery.json.
- Ранняя ошибка rowid служебной FTS-таблицы исправлена в принадлежащем worker тесте.
ACCEPTANCE_EVIDENCE:
- Атомарность: инъекция после enqueue откатывает отчёт/событие/уведомление, audit и observations прежние.
- Повторы: одинаковый/конкурентный запрос и повтор обработчика дают одну запись/событие/уведомление.
- Сбой/восстановление: partial handler rollback,5ошибок retry×4/dead и transient retry/processed,без текста исключения.
- Доступ: роли,CSRF,чужая/завершённая/будущая/новая связь,disabled врач; HEAD не отмечает доставку.
- Метки: порядок/идемпотентность/сохранность; unknown/XSS/отсутствие клинических действий/каталог неизменен.
- Миграция: прежние таблицы/строки сохранены после007.
- HTTP: сохранность ожидающего события/отметок после настоящего перезапуска.
SCOPE_COMPLIANCE: PASS
RISKS_OR_BLOCKERS:
Блокеров нет. Worker измерял HTTP HTML, браузер проверяет основной агент; нет клинической апробации/внешней доставки/24/7.
