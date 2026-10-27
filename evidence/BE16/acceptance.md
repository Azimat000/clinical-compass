# BE16 — техническая приёмка

27.10.2026. Технический PASS в ограниченной синтетической области. Не юридическое
заключение/клиническая приёмка/разрешение реальных данных. Общая регрессия по
прямому поручению отложена, полного make check PASS нет.

| Критерий/работа | Прямое доказательство | Результат |
|---|---|---|
| BE16-A01: матрица всех новых операций и промежуточных данных | security-review.md: полная таблица v1/create/read/input/context/review/alert/cancel/queue/cache/export; 9новыхtests и выбранные contracts/jobs/alerts/sources/reviews/integration; реальные HTTP23 и независимая проверка81рабочейтаблицы | PASS технически |
| BE16-A02: недоверенный текст/секреты/клиническое состояние | test_untrusted_text_and_provider_output_cannot_publish_or_apply, test_http_mass_assignment…, test_minimal_model_payload…, test_safe_exceptions_logs…, test_provider_error_body…; rules/цитаты/версии/источники/independent medication checker, отсутствиеtools, отдельныйврач; 19реальныхсценариев/24подмены | PASS в проверенном объёме |
| BE16-A03: фактические проверки, закрытие находок, честные границы | reproduce_baseline.py/json воспроизводит2нарушения; security тесты/HTTP23 подтверждают исправление HEAD/старойсвязи; report разделяет техническое/юридическое/клиническое и содержит оставшиеся ограничения | PASS |
| Работа1: API/очереди/кэши/журналы/экспорты | security-review.md, integration.log, remaining-boundaries.log; прямое чтение routes/analyses/jobs/alerts/context/reviews/model/events; нет нового прямого export/табличного API | PASS |
| Работа2: подмена инструкции/ID/версии/цитаты/роли/retry | security, contracts, sources, risk/diagnosis/plan/review tests; никакого самостоятельногоназначениямоделью, roles/relationship/lease проверяютсяна сервере | PASS |
| Работа3: устранение проблем/минимум данных/нет tools | web.GET/HEAD; therapy_context.view/prepare; risk errors allowlist; therapy payload без diagnosisreviewID; 7новыхнастоящихвызововDeepSeek/defaultworker | PASS |

## Проверки основного агента

- `PYTHONPATH=apps/tests:. .venv/bin/python -m unittest apps.tests.test_backend_security apps.tests.test_backend_contracts apps.tests.test_backend_jobs apps.tests.test_backend_alerts apps.tests.test_backend_model apps.tests.test_backend_risk_context apps.tests.test_backend_sources apps.tests.test_backend_plan_review apps.tests.test_backend_therapy_integration apps.tests.test_report_drafts`:
  **141testsPASS/72.954s**, integration.log. Включает9новыхsecuritytests.
- Дополнительная целевая команда по diagnosis_review/diagnosis_integration/
  risk_integration/extraction: **50testsPASS/22.043s**, remaining-boundaries.log.
  Всего191целевойтест; общаярегрессиянеподменена.
- `evidence/BE16/reproduce_baseline.py`: exit0, старыйHEAD безCSRFсоздавал1действие;
  старыйcontext выдавал canary новой связи; только временная база/кодbaselineвпамяти.
- `evidence/BE16/live_protocol.py`:6настоящихвызовов,19случаевPASS; exit1 на
  старой неверной проверке мутации только первого кандидата. Лог сохранён.
  `verify_therapy.py`:exit0, независимая перепроверка всех19сохранённыхреальных
  результатов и24подмен всехкандидатов, без повторных платных запросов.
- `evidence/BE16/http_protocol.py`:exit0,**23настоящихHTTP/отдельныйdefaultCLIworker/
  перезапуск/HEADбеззаписи/роли/CSRF/сменасвязи/подтверждение/календарь/пункты**,
  ещё1настоящийDeepSeek. Диагноз — явная структурированная механическая фикстура.
- `evidence/BE16/verify_preservation.py`:exit0,**81таблица/доступы/4чужихфайла**
  неизменны, рабочий8000health200/схема015; изменённыеtrackedпути в scope.
- validate_plan/status/diffcheck — финальные логи, после commit/tagповторены.
  Общая регрессия намеренно не запускалась, это не полный make check.

Начальный securityпрогон:2FAIL/1ERROR. ОдинFAILвыявилреальныйHEADдефект;
другие — неверное ожидание404вместо безопасного409 и несуществующая таблица
в проверке. Исправлены поведение и ошибочные ожидания; targeted-second9PASS,
затем integration141PASS. Клинические критерии не снижались.

## Матрица поручения

| Требования | Фактический результат BE16 |
|---|---|
| B01 | Чужие input/source/run/пациент скрыты, точные версии/снимки защищены; новый context только текущей связи |
| B02/B03/B04 | Рисковый путь независим; очередь/канал/episode/роль/retry/ошибки проверены; семантическая клиническая точность не переоценивалась |
| B05/B06 | Гипотезы/решение по диагнозу только врачу текущей связи, подмена версии/цитат/состояния отклоняется |
| B07/B08/B09 | План/сверка/лекарственный вариант/редакция/отдельноеутверждение/календарь; HEAD больше не утверждает; до врача нет применения |
| B10 | Только backendAPI; HTML/CSS/JS и интерфейс не менялись |
| B11 | Источники/отзыв/изменение/истечение проверяются сервером; внешняя доступность исследована без продления срока/прав/юридического допуска |
| B12 | 7новыхнастоящихDeepSeekс ограниченным запросом/без инструментов; только синтетика |
| B13 | МатрицаAPI/промежуточныхданных/экспортов, исправлены2воспроизведённыхнарушения; дополнительные защиты ошибок/минимизации. Внеобъёмные/клинические/юридические риски остаются |
| B14 | Целевые lease/cancel/stale/retry/rollback/сохранность/перезапуск/бюджет; нагрузочныйBE17ещёвпереди |
| B15 | РеальныеHTTP/defaultworkerвкопии; полнаясквознаяBE18неподменена |
| B16 | Независимой клинической экспертизы и допуска нет, BE19/clinical_releaseblocked |

M01/M02/M03/M09/M10/T13: технические границы ролей/текста/конфиденциальности/
человеческого решения/защиты данных проверены выше; обе матрицы дополнены
ссылками без повышения полного конкурсного/медицинского выполнения.

Ledger153/739853→160/748067microUSD:7новыхвызовов/8214microUSDceiling;
6094токена/оценкаUSD0.001020888–0.002041776, остаток251933из1000000,
percall20000. Фактическийсчёт/RUBнеизвестны; покупок/пополнений/новыхобязательствнет.
Модельdeepseek-flash/compass-model-v1/temperature0/thinkingdisabled;
therapy-draft-v1/medication-regimens-v2; точныехешиruntime/источников —
verification.json/therapy/live-summary.json. Новыхмиграций/зависимостейнет.
СрокBE03до27.10.2026 19:17МСКнепродлён. СледующийотдельныйсрезBE17.
