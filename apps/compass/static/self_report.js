/* Один серверный бланк самоотчёта, пять шагов показа. Ничего не хранится в браузере и не отправляется до кнопки отправки. */
(() => {
  const form = document.querySelector('[data-report-form]');
  if (!form) return;
  const steps = [...form.querySelectorAll('[data-report-step]')];
  const controls = form.querySelector('[data-step-controls]');
  const back = controls.querySelector('[data-step-back]');
  const next = controls.querySelector('[data-step-next]');
  const status = form.querySelector('[data-step-status]');
  const unsaved = form.querySelector('[data-unsaved-status]');
  const review = form.querySelector('[data-review]');
  const list = form.querySelector('[data-review-list]');
  const last = steps.length;
  let current = 1, dirty = form.dataset.hasError === 'yes';

  function label(field) {
    const box = field.closest('label');
    if (!box) return field.name;
    const clone = box.cloneNode(true);
    clone.querySelectorAll('select,input,textarea').forEach(item => item.remove());
    return clone.textContent.trim();
  }
  function value(field) {
    if (field.tagName === 'SELECT') return field.options[field.selectedIndex].textContent.trim();
    return field.value.trim() || 'не заполнено';
  }
  function buildReview() {
    list.replaceChildren();
    steps.slice(0, -1).forEach(step => step.querySelectorAll('select, textarea, input[type="date"], input[type="number"]').forEach(field => {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label(field); dd.textContent = value(field);
      list.append(dt, dd);
    }));
    review.hidden = false;
  }
  function show(number, focus) {
    current = number;
    steps.forEach(step => { step.hidden = Number(step.dataset.reportStep) !== number; });
    status.hidden = false;
    status.textContent = 'Шаг ' + number + ' из ' + last;
    controls.hidden = false;
    back.disabled = number === 1;
    next.hidden = number === last;
    if (number === last) buildReview();
    if (focus) steps[number - 1].querySelector('h3').focus();
  }
  back.addEventListener('click', () => show(current - 1, true));
  next.addEventListener('click', () => show(current + 1, true));
  // При ошибке сервера все шаги остаются видимыми: ошибка не прячет своё поле.
  if (form.dataset.hasError === 'yes') unsaved.textContent = 'Запись не сохранена. Введённые ответы оставлены в форме; проверьте поля во всех разделах.';
  else {
    show(1, false);
    // Ссылка на шаг по якорю и встроенная проверка браузера открывают нужный шаг.
    form.addEventListener('invalid', event => {
      const step = event.target.closest('[data-report-step]');
      if (step && step.hidden) show(Number(step.dataset.reportStep), false);
    }, true);
  }
  function markDirty() { dirty = true; unsaved.textContent = 'Есть неотправленные ответы. Они не сохранены на сервере.'; }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
})();
