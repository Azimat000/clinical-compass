# FE03C: подготовка примеров, без проверок

Рабочий сайт и его база не переключены. Копия: `var/FE03C-cases.sqlite3`,
полная SQLite backup существующей базы, миграции только в копии. Очередь выключена.
Все старые истории скопированы без фильтрации; сверка сохранности не запускалась.
Новые события явно вымышленные, добавлены через records.save, не заменяют назначения.
Идентификаторы добавлений: `evidence/FE03C/preparation-before.json`.

Начальная подготовка:
` .venv/bin/python tools/prepare_frontend_cases.py --phase before `

Отдельный шаг изменения:
` .venv/bin/python tools/prepare_frontend_cases.py --phase after `

Шаг after пока НЕ выполнен: D05 — уточнение без заполнения старых пропусков,
D08 — отдельное уточнение времени эпизода, D10 — новое сведение после черновика.
Повтор уже завершённой фазы возвращает already_prepared и ничего не переписывает.
Сброса/удаления/пересоздания существующей копии нет. Неизвестная копия или другой
хеш manifest отклоняются. Незавершённая подготовка без provenance требует отдельного
разбора и не перезаписывается автоматически. Не подключать эту копию к8000.

| Сценарий | Пациент | Фактическая подготовка |
|---|---|---|
| D01 | P201 | existing_history_or_pending_event_unverified |
| D02 | P202 | input_added_unverified |
| D03 | P203 | existing_history_or_pending_event_unverified |
| D04 | P204 | existing_history_or_pending_event_unverified |
| D05 | P205 | existing_history_or_pending_event_unverified |
| D06 | P206 | existing_history_or_pending_event_unverified |
| D07 | P207 | input_added_unverified |
| D08 | P208 | input_added_unverified |
| D09 | P209 | existing_history_or_pending_event_unverified |
| D10 | P210 | existing_history_or_pending_event_unverified |
| D11 | P201/P206 | existing_history_or_pending_event_unverified |
| D12 | P210 | existing_history_or_pending_event_unverified |

Для всех сценариев ожидаемое состояние записано в frontend-cases-v1.json;
это ожидание, а не фактический результат. Источники дневник/анамнез/приём имеют
новые входные записи; четвёртый источник (анкета D06) ещё требует отдельного
штатного назначения и ответа. D01 не имеет доказанного положительного модельного
пути; D11/D12 не исполнялись. Диагноз врача не придуман и не подтверждён автоматически.
Результаты системы не сгенерированы и не подставлены в HTML. Модель/worker не запускались.
FE03C/родитель FE03 не приняты; quality gate FE03B false сохранён.

Следующие три блока — FE05/FE06/FE07–08, в существующем оформлении и навигации.
Подключать состояния ожидания/отказа/неполноты можно без имитации успешного ответа;
публиковать непроверенный packet runtime как готовый нельзя.
