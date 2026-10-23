/* Только удобство формы. Назначения и отметки проверяет сервер. */
(function () {
  'use strict';
  var editor = document.querySelector('.med-editor');
  if (!editor) return;
  var mode = editor.querySelector('[name="med_change"]');
  var body = editor.querySelector('[data-med-editor-body]');
  var items = Array.from(editor.querySelectorAll('[data-med-item]'));
  var add = editor.querySelector('[data-med-add]');
  function sync() {
    body.hidden = mode.value !== 'replace';
    add.hidden = items.every(function (item) { return !item.hidden; });
  }
  function total(item) {
    var quarters = Array.from(item.querySelectorAll('select')).reduce(function (n, el) { return n + Number(el.value || 0); }, 0);
    item.querySelector('[data-med-total]').textContent = 'Всего за день: ' + (quarters / 4).toLocaleString('ru-RU') + ' табл.';
  }
  items.forEach(function (item, i) {
    var name = item.querySelector('input[type="text"]');
    item.hidden = i > 0 && !Array.from(item.querySelectorAll('input,select')).some(function (el) { return el.value; });
    item.querySelector('[data-med-remove]').hidden = false;
    item.querySelector('[data-med-remove]').addEventListener('click', function () {
      item.querySelectorAll('input,select').forEach(function (el) { el.value = ''; });
      item.querySelector('summary').textContent = 'Добавить препарат ' + (i + 1);
      item.hidden = true;
      item.open = false;
      total(item); sync();
      add.focus();
    });
    if (name) name.addEventListener('input', function () { item.querySelector('summary').textContent = name.value || 'Препарат ' + (i+1); });
    item.addEventListener('change', function () { total(item); });
    total(item);
  });
  add.addEventListener('click', function () {
    var item = items.find(function (x) { return x.hidden; });
    if (!item) return;
    item.hidden = false; item.open = true;
    item.querySelector('input').focus(); sync();
  });
  mode.addEventListener('change', sync); sync();
}());
