/* Счётчик ответов и проверка пропусков. Тексты и порядок утверждений не меняются; ответы нигде не хранятся. */
(() => {
  const form = document.querySelector('[data-questionnaire]');
  if (!form) return;
  const sets = [...form.querySelectorAll('[data-question]')];
  const status = form.querySelector('[data-answer-progress]');
  const notice = form.querySelector('[data-skip-notice]');
  const noticeText = form.querySelector('[data-skip-text]');
  const firstSkip = form.querySelector('[data-skip-first]');
  const submit = form.querySelector('#q-submit');
  const sending = form.querySelector('[data-submit-status]');
  const label = submit.textContent;
  let dirty = false, warned = false;

  function skipped() {
    return sets.filter(set => {
      const picked = set.querySelector('input[type="radio"]:checked');
      return !picked || picked.value === '';
    });
  }
  function count() {
    const left = skipped().length, answered = sets.length - left;
    status.textContent = 'Отвечено: ' + answered + ' из ' + sets.length + '. Без ответа: ' + left + '.';
    if (warned) {
      // Ответ на пропущенный вопрос обновляет предупреждение, а при нуле пропусков убирает его.
      if (left === 0) { notice.hidden = true; warned = false; submit.textContent = label; }
      else noticeText.textContent = 'Без ответа: ' + left + '.';
    }
  }
  form.addEventListener('change', () => { dirty = true; count(); });
  firstSkip.addEventListener('click', event => {
    event.preventDefault();
    const target = skipped()[0];
    if (target) { target.scrollIntoView({block: 'center'}); target.querySelector('input[type="radio"]').focus(); }
  });
  form.addEventListener('submit', event => {
    const left = skipped().length;
    if (left && !warned) {
      // Первое нажатие с пропусками только предупреждает; второе отправляет как есть.
      event.preventDefault();
      warned = true;
      noticeText.textContent = 'Без ответа: ' + left + '.';
      notice.hidden = false;
      notice.focus();
      submit.textContent = 'Отправить с пропусками';
      return;
    }
    if (form.dataset.sending) { event.preventDefault(); return; }
    dirty = false;
    form.dataset.sending = 'yes';
    submit.setAttribute('aria-busy', 'true');
    submit.textContent = 'Отправляем…';
    sending.textContent = 'Отправляем анкету.';
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  count();
})();
