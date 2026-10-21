/* Счётчик ответов и предупреждение о несохранённых ответах. Тексты и порядок вопросов не меняются; ответы нигде не хранятся. */
(() => {
  const form = document.querySelector('.questionnaire');
  if (!form) return;
  const sets = [...form.querySelectorAll('fieldset')];
  const status = document.querySelector('[data-answer-progress]');
  let dirty = false;
  function count() {
    const answered = sets.filter(set => {
      const picked = set.querySelector('input[type="radio"]:checked');
      return picked && picked.value !== '';
    }).length;
    status.textContent = 'Отвечено: ' + answered + ' из ' + sets.length + '. Без ответа: ' + (sets.length - answered) + '. Ответы не отправлены, пока вы не нажмёте кнопку отправки.';
  }
  form.addEventListener('change', () => { dirty = true; count(); });
  form.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  count();
})();
