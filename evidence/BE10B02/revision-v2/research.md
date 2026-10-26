# Официальная документация API — 26.10.2026

Read-only исследователь /root/be10b02_api_limits, fork_turns=none, итоговый отчёт
получен. Основной агент не повторял поиск, ключи и платный endpoint исследователь
не использовал. Первичные источники:

- https://api-docs.deepseek.com/guides/json_mode/
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/quick_start/pricing/

DeepSeekflash поддерживает JSON Output; имя модели и thinking disabled применимы.
JSON mode гарантирует синтаксис JSON, а не соответствие нашей схеме. Документация
требует явного слова JSON и примера структуры; длина ответа должна быть достаточной.
Пустой ответ и finish_reason=length — отказы. Верхний API предел max_tokens393216;
старые1024 были локальным ограничителем HAC. В новой версии1536, денежный предел
одного запроса20000microUSD сохранён. Оба условия проверяются до резерва/HTTP.

Исследователь подтвердил текущие peakтарифыFlash: cachemissUSD0.30/Minput,
outputUSD1.20/M; offpeakUSD0.15/M иUSD0.60/M. Для решения о бюджете используются
прежние более высокие защитные ставкиHACUSD1/Minput иUSD5/Moutput с резервом по
байтамUTF8+512, а не эти тарифы. Это защитный потолок, не точный счёт. Invoice и
RUBconversion неизвестны. Цены не заменяют реальныеusage/ledgerизмерения.

Клинические критерии/источники/реестрправ не менялись, срокBE03до27.10.2026
19:17МСК не продлён. Только самостоятельные фактические вопросы и авторские
синтетические записи. PDF/таблицы/цитатыКР/текстшкал/реальныеистории не передаются.
Границыfulltextunknown,syntheticonly,clinical_releaseblocked и BE18/19 сохранены.
