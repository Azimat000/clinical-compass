/* Формы кабинета врача: без этого файла всё работает, он только убирает лишнее.
   1) повторное нажатие кнопки при ожидании ответа сервера;
   2) для вида решения показываются только нужные группы полей;
   3) переход по ссылке на запись в истории раскрывает её;
   4) на узком экране строка разделов пациента прокручивается к текущему пункту. */
(function () {
  'use strict';

  function busy(form, button) {
    form.dataset.sent = '1';
    form.setAttribute('aria-busy', 'true');
    if (button) {
      button.dataset.label = button.textContent;
      button.textContent = button.textContent.replace(/[.…]*$/, '') + '…';
      button.setAttribute('aria-busy', 'true');
      button.setAttribute('aria-disabled', 'true');
    }
  }

  function release(form) {
    delete form.dataset.sent;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('button[aria-busy]').forEach(function (button) {
      if (button.dataset.label) { button.textContent = button.dataset.label; }
      button.removeAttribute('aria-busy');
      button.removeAttribute('aria-disabled');
    });
  }

  document.querySelectorAll('form[data-busy]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (form.dataset.sent) { event.preventDefault(); return; }
      busy(form, event.submitter);
      // Если ответа нет полминуты (обрыв сети), форму можно отправить снова: сервер узнает повтор по ключу.
      window.setTimeout(function () { release(form); }, 30000);
    });
  });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) { document.querySelectorAll('form[data-busy]').forEach(release); }
  });

  document.querySelectorAll('[data-decision-form]').forEach(function (form) {
    var kind = form.querySelector('select[name="kind"]');
    var groups = form.querySelectorAll('[data-for-kinds]');
    if (!kind) { return; }
    function sync() {
      groups.forEach(function (group) {
        group.hidden = group.dataset.forKinds.split(' ').indexOf(kind.value) === -1;
      });
    }
    kind.addEventListener('change', sync);
    sync();
  });

  var current = document.querySelector('.patient-nav [aria-current="page"]');
  if (current && current.scrollIntoView) { current.scrollIntoView({ block: 'nearest', inline: 'center' }); }

  function openTarget() {
    if (!location.hash) { return; }
    var target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { return; }
    if (!target) { return; }
    for (var node = target; node; node = node.parentElement) {
      if (node.tagName === 'DETAILS') { node.open = true; }
    }
    target.scrollIntoView();
  }
  window.addEventListener('hashchange', openTarget);
  openTarget();
}());
