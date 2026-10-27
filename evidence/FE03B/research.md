# FE03B — первичная источниковая сверка 27.10.2026

Read-only web-researcher `/root/fe03b_sources`, isolated context. Основной агент
использует отчёт, повторного внешнего поиска нет. Наблюдение около16:15МСК.
Все пять первичных PDF HTTP200, SHA256 совпали с evidence/BE15/research.md.

| Источник | Байты | SHA256 |
|---|---:|---|
| КР301_3 |2148711|2e8b83978be0e5fa3772e1dc37b44954bc5991fb4f74433ffd1375700ab7b5bd|
| КР457_3 |1763250|c2db38ebb558ba98a8514bb3027f3e71d0cf293c512183f882ac9a94da21271a|
| Элицея |270866|25300691d20562bf7f55c7d6e5ef6e7b624210442ae3d929b5c446d21caad67e|
| Алевал |19135708|b49bbf87b9d7381eb62b40423fb24a23733d71c1f9f8fee6c91deb6dfb98a33e|
| Авиандр |327709|873f2962acbb84a3b5ac7cf92da1b5363fa204d29a7246b3f9818d0cce2a83dc|

JSON КР: version3/adulttrue/childfalse/NPC_approvedtrue/«Применяется».
301_3 — F32/F33, публикация2024-08-26T12:06:01.3;
457_3 — F41.1, публикация2024-09-19T00:00:00.
Точные первичные URL:
- https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrec2&id=301_3
- https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrecPdf&id=301_3
- https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrec2&id=457_3
- https://apicr.minzdrav.gov.ru/api.ashx?op=GetClinrecPdf&id=457_3
- https://grls.rosminzdrav.ru/InstrImg/2024/11/12/1510612/6aca30c6-f96a-4c23-a390-d0b7279bd03d.pdf
- https://grls.rosminzdrav.ru/InstrImg/2021/4/22/1468377/%D0%9B%D0%A1%D0%A0-003615_10%5B2021%5D_0.pdf
- https://grls.rosminzdrav.ru/InstrImg/2026/07/29/1532717/94ba54dc-ce1c-40ed-96f4-5c3a31f13805.pdf

Авиандр: первая загрузка SSL error, три последующих HTTP200/одинаковый SHA.
Это листок-вкладыш пациента, не ОХЛП. Доступность/хеши не доказывают юридический
current регистрации/отсутствие отзыва, индивидуальную применимость, полноту
ограничений, права на fulltext или независимую клиническую проверку.
BE03 до 27.10.2026 19:17 МСК НЕ продлён; clinical_release blocked,
BE17–BE19 пропущены. Закрытые организационные каналы не возобновлялись.

Официальные DeepSeekдокументыисследовательсверил16:15МСК:
https://api-docs.deepseek.com/quick_start/pricing/
https://api-docs.deepseek.com/api/create-chat-completion/
https://api-docs.deepseek.com/quick_start/rate_limit/
Модельdeepseek-flash/V4.1-Flash-1017,контекст1048576/maxoutput393216токенов;
HACсохраняетболееузкие16000байт/1536output. Максимальныетарифыcachemiss
USD0.30/Minput/1.20/Moutput,cachehit0.006/M;offpeak0.15/0.60/hit0.003.
Кодовыеценовыепотолки1/5USD/Mостаютсяконсервативными;неявнаяревизиявесов
неизвестна. ПользовательпряморазрешилувеличениеAPIбюджета,зафиксирован
общийcapUSD3/percallUSD0.02,безпокупок/пополнений. СрокBE03НЕпродлён.
