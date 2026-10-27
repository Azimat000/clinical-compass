/* In-memory interaction study. No fetch, storage, clinical writes or fake API. */
(() => {
  const block = document.querySelector('.fe01-support');
  const select = document.querySelector('#fe01-state');
  if (!block || !select) return;
  const messages = {
    ready: 'Предложение подготовлено. Проверьте основания перед решением.',
    queued: 'Анализ в очереди. Можно продолжать работу с историей.',
    running: 'Анализ выполняется. Время завершения пока неизвестно.',
    partial: 'Не хватает сведений для полного вывода. Откройте список уточнений.',
    stale: 'Появились новые сведения. Прежний результат показан для сравнения; применить его нельзя.',
    conflict: 'В другой вкладке сохранена новая версия. Ваш текст остался здесь. Сравните версии перед повтором.',
    failed: 'Не удалось получить результат. История доступна. Повторите запрос после проверки соединения.',
    cancelled: 'Анализ отменён. Результат не получен; отсутствие результата не означает отсутствия риска.',
    offline: 'Нет связи с сервером. Свежесть сведений неизвестна; сохранение и подтверждение недоступны.',
    access_denied: 'Доступ изменился. Сведения пациента скрыты. Вернитесь к списку своих пациентов.',
    empty: 'Новых результатов нет. Это не означает, что риска или необходимости лечения нет.',
    saving: 'Сохраняется… Дождитесь ответа сервера. Не повторяйте отправку.',
    saved: 'Пример ответа сервера: запись сохранена, версия 2. В этом прототипе данные не записываются.'
  };
  const status = block.querySelector('.fe01-status');
  function change(state) {
    select.value = state;
    status.textContent = messages[state];
    status.dataset.state = state;
    status.setAttribute('role', ['failed','conflict','access_denied'].includes(state) ? 'alert' : 'status');
    block.setAttribute('aria-busy', String(['queued','running','saving'].includes(state)));
    block.querySelectorAll('[data-fe01-content]').forEach(el => { el.hidden = state === 'access_denied'; });
    block.querySelectorAll('[data-fe01-write]').forEach(el => { el.disabled = state !== 'ready'; });
    block.querySelectorAll('[data-fe01-result]').forEach(el => { el.hidden = ['queued','running','failed','cancelled','empty','partial'].includes(state); });
    block.querySelectorAll('[data-fe01-clarify]').forEach(el => { el.hidden = state !== 'partial'; });
    block.querySelectorAll('[data-fe01-retry]').forEach(el => { el.hidden = !['failed','cancelled','stale'].includes(state); });
    block.querySelectorAll('[data-fe01-compare]').forEach(el => { el.hidden = state !== 'conflict'; });
    if (state === 'access_denied') block.querySelectorAll('textarea').forEach(el => { el.value = ''; });
  }
  select.addEventListener('change', () => change(select.value));
  block.addEventListener('click', event => {
    const button = event.target.closest('[data-fe01-action]');
    if (!button) return;
    const action = button.dataset.fe01Action;
    if (action === 'save') {
      const field = block.querySelector('textarea');
      if (field && !field.value.trim()) {
        status.textContent = 'Введите текст врача. Пустая запись не сохраняется.';
        status.setAttribute('role', 'alert'); field.focus(); return;
      }
      change('saving');
      // Success is a separate explicit test case, never a timer or optimistic update.
    } else if (action === 'retry') change('queued');
    else if (action === 'compare') block.querySelector('[data-fe01-comparison]').hidden = false;
    else if (action === 'prepare') {
      const review = block.querySelector('[data-fe01-review]'); review.hidden = false;
      review.querySelector('textarea').focus();
    } else if (action === 'confirm') {
      const review = block.querySelector('[data-fe01-review]');
      if (!review.querySelector('input[type=checkbox]').checked || !review.querySelector('textarea').value.trim()) {
        status.textContent = 'Укажите обоснование и подтвердите просмотр сведений.';
        status.setAttribute('role', 'alert'); return;
      }
      change('saving');
    }
  });
  change('ready');
})();
