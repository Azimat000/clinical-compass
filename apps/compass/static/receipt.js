/* Экран критических событий: страница сама отправляет отметку «получено на экране врача», когда она открыта и видна.
   Без этого файла работает кнопка «Подтвердить получение». Отметка считается сделанной только после ответа сервера 204. */
(function () {
  'use strict';

  var list = document.getElementById('critical-list');
  var status = document.querySelector('[data-receipt-status]');
  if (!list || !window.fetch) { return; }
  var pending = list.querySelectorAll('[data-receipt-url]');
  if (!pending.length) { return; }
  var started = false;

  function send() {
    if (started || document.visibilityState !== 'visible') { return; }
    started = true;
    var jobs = Array.prototype.map.call(pending, function (article) {
      return fetch(article.dataset.receiptUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRF-Token': list.dataset.csrf }
      }).then(function (response) { return response.status === 204; }, function () { return false; });
    });

    Promise.all(jobs).then(function (results) {
      if (results.every(Boolean)) {
        // Время получения показывает сервер: берём страницу заново, а не рисуем своё.
        window.location.reload();
      } else if (status) {
        status.hidden = false;
      }
    });
  }

  // Вкладка, открытая в фоне, получения не отмечает: экрана никто не видел.
  document.addEventListener('visibilitychange', send);
  send();
}());
