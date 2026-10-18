# Внешний контроль S05 — 18.10.2026, Москва

Read-only web-researcher /root/s05_research, fork_turns=none; завершён. Файлов не менял, сообщений людям/публикаций/покупок нет. Основной агент использовал проверенный отчёт без повторного поиска.

## Технические основания

- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): случайный непрозрачный SID; состояние на сервере; ротация при входе/повышении привилегий, отзыв, сроки, HttpOnly/SameSite/Secure при HTTPS.
- [Flask sessions](https://flask.palletsprojects.com/en/stable/quickstart/#sessions): встроенные cookie-сессии не выбраны; продукт использует собственную серверную таблицу и случайную cookie без роли/данных пациента.
- [Werkzeug security helpers](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash): установленные Flask 3.1.3/Werkzeug 3.1.9; scrypt:32768:8:1 явно закреплён, исходный пароль не сохраняется. [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) рекомендует более сильные параметры; подбор/замер перед внешним развёртыванием остаётся S14/S15. Стандарт библиотеки не назван полным соответствием OWASP.
- [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html): лимиты попыток, одинаковая ошибка неверного пароля/неизвестного/отключённого пользователя, фиктивная дорогая проверка для неизвестного ID. Реализация отдельно выдаёт 429 для сетевого/учётного лимита, который применяется и к неизвестным ID; это задокументированный технический режим прототипа.
- [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html): синхронизирующий случайный токен для небезопасных методов; SameSite дополнительно. Для входа — отдельный случайный серверный одноразовый challenge с cookie и полем формы. Origin/Referer не основной механизм; CSP form-action self, доверенные Host и отсутствие CORS.
- Привязка приглашения к пациенту/врачу/получателю, срок/отзыв/одноразовость/транзакция и единственная активная связь — применение этих принципов к проекту, а не цитата готового медицинского стандарта.

## Условия конкурса и доступ

[Официальная страница](https://clinicalcompass2026.ru/) и [DOCX](https://clinicalcompass2026.ru/wp-content/themes/clinical-compass/assets/documents/championship-regulations.docx?ver=1.2.8) проверены исследователем. DOCX HTTP 200, 63252 байта; Last-Modified Fri, 16 Oct 2026 09:27:21 GMT, ETag f714-65df1c57359a8; вычисленный SHA-256 7106584c95391fef5c22445781faa1e2b78aa6cda16df67e9a56f091e2265df3 совпал с сохранённым. Открытая страница: чемпионат 15–30.10.2026, предзащита 28.10, финал/демо 30.10. Новых публично подтверждённых условий для S05 не обнаружено; отсутствие закрытых дополнений не доказано.

Один узкий read-only Gmail-поиск за период после 17.10 вернул UNAUTHORIZED, не выполнен. Письма и закрытый чат не прочитаны. Нужна повторная авторизация через /mcp или настройки коннекторов. Новых подтверждений состава команды/вклада/согласий нет. B01/B03–B11 не сняты. Медицинские источники не активировались. Runtime-зависимости не добавлены, расходы и обязательства 0 ₽.
