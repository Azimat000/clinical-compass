# BE16 — внешняя сверка 27.10.2026

Read-only исследователь `/root/be16_sources`, fork_turns=none. Основной агент
использовал отчёт; внешний поиск не повторял. Организационная ветка отложена.

[OWASP API1:2023](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/)
требует проверки текущего доступа к каждому объекту. UUID не заменяет проверку
пациента, связи, роли и конкретного анализа/черновика/сигнала.

[OWASP Prompt Injection](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
описывает многоуровневую защиту: минимальные полномочия, отделение данных,
проверку структуры/оснований и человека перед действиями высокой важности.
Ни системный prompt, ни фильтр слов не гарантируют отсутствие ложного кандидата.
[OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
рекомендует события безопасности без медицинских текстов, ключей, токенов,
паролей и лишних личных идентификаторов.

Официальные документы [Flask об ошибках](https://flask.palletsprojects.com/en/stable/errorhandling/),
[настройках](https://flask.palletsprojects.com/en/stable/config/) и
[безопасности](https://flask.palletsprojects.com/en/stable/web-security/)
поддерживают безопасные ответы, отключённый debug, ограничения тела/host и
защитные заголовки. Это рекомендации для технической проверки, не заключение
о соблюдении медицинского или российского законодательства.

Узкая сверка первичных URL: оба JSON и PDF Минздрава HTTP200; metadata301_3:
version3/status0/создан26.08.2024, 457_3:version3/status0/создан18.09.2024;
оба «Взрослые». PDF2148711/1763250байт. Три ГРЛСPDFHTTP200:
Элицея270866/Алевал19135708/Авиандр327709байт. Размеры совпали с BE15;
новых вычисленных хешей исследователь не сообщил, совпадение байтов не заявляем.

Первичные ссылки сохранены в [предыдущей сверке](../BE15/research.md):
[КР301_3 metadata](https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrec2&id=301_3),
[КР301_3 PDF](https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrecPdf&id=301_3),
[КР457_3 metadata](https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrec2&id=457_3),
[КР457_3 PDF](https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrecPdf&id=457_3).
Доступность не доказывает актуальную применимость/отсутствие отмены/права.
Авиандр — листок-вкладыш пациента, не ОХЛП. BE03 срок 27.10.2026 19:17МСК
не продлён; clinical_releaseblocked; независимая экспертиза/полные права/
регистрационный юридический допуск не установлены. Закрытые каналы не проверены.
