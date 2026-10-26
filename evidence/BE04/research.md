# DeepSeek: проверка исследователя, 26.10.2026

Изолированный read-only web-researcher проверил официальные страницы; основной
агент не повторял поиск. Ниже сохранён проверенный вывод, а не сырые HTTP-ответы.

- POST https://api.deepseek.com/chat/completions, Bearer API key.
- Текущие IDs: deepseek-flash, deepseek-v4-pro. Выбран deepseek-flash,
  thinking=disabled, temperature=0, stream=false, response_format=json_object.
- JSON mode гарантирует синтаксис, не соблюдение произвольной схемы; требуется
  инструкция JSON. Структуру независимо проверяет серверный validate_schema.
  JSON Schema в /responses — другой API, здесь не используется.
- Контекст моделей до 1M, выпуск до 384K; проект сознательно ограничивает запрос
  12000 байт включая schema/system, выпуск256 токенами; smoke 128.
- usage: prompt_tokens/completion_tokens/total_tokens и cache hit/miss.
- Keep-alive не гарантирует срок завершения; поставщик может ждать инференса
  до 10 минут. Проект:30 с обычно/60 с smoke, без автоматических повторов.
- Ошибки401 — ключ,402 — баланс,429 — лимит,400/422 — параметры,500/503 — сбой.
- Цены flash, USD/1M: вход hit 0.003/miss 0.15/output 0.60 вне пика;
  hit 0.006/miss 0.30/output 1.20 в пик. Консервативный внутренний резерв
  $1 input/$5 output за 1M покрывает обе ставки flash. Pro не разрешён адаптером.
- Пик 01–04 и 06–10 UTC в будни, кроме китайских праздников. Для отчёта сохраняются
  обе оценки, а не неподтверждённое фактическое списание. Конвертация RUB не делалась.
- Privacy от 10.02.2026: сервис не предназначен для чувствительных данных,
  включая здоровье; собирает входы, допускает улучшение/обучение, обработку/хранение
  в КНР. Точный API-retention и API-level no-training/zero-retention не подтверждены.
  Terms опубликованы22.04.2026, действуют 29.04.2026. Клинические реальные данные
  не допускаются. Синтетические тексты здесь авторские, без персональных данных.
- Имена моделей являются IDs поставщика, не неизменяемой ревизией весов. API
  не предоставил immutable revision в проверенном ответе. Сохраняются фактический
  ID, время, локальные версии инструкции/schema/конфигурация. Повторяемость весов
  и клиническое качество этим не доказаны.

Источники, просмотренные исследователем 26.10.2026:

- [Первый вызов](https://api-docs.deepseek.com/quick_start/)
- [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Responses/JSON Schema](https://api-docs.deepseek.com/api/create-response/)
- [Модели/цены](https://api-docs.deepseek.com/quick_start/pricing/)
- [Ограничения/keep-alive](https://api-docs.deepseek.com/quick_start/rate_limit/)
- [Ошибки](https://api-docs.deepseek.com/quick_start/error_codes/)
- [API Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)
- [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)

Предел: это отчёт исследователя с URL, без сохранённых тел страниц; условия могут
измениться. Перед новым длительным использованием тариф и правила проверяются заново.
