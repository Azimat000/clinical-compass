/* Keep the same form and retry key after an uncertain network outcome. No browser storage. */
for (const form of document.querySelectorAll('.retry-form')) {
  let busy = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    const status = form.querySelector('.retry-status');
    const fields = [...form.querySelectorAll('input,textarea,select,button')];
    const payload = new FormData(form);
    fields.forEach(field => { field.disabled = true; });
    status.textContent = 'Отправка…';
    try {
      const response = await fetch(form.action, {method:'POST', body:payload});
      if (response.redirected && new URL(response.url).pathname.endsWith('/communication')) {
        window.location.assign(response.url);
        return;
      }
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const detail = page.querySelector('main [role=alert]');
      status.textContent = detail ? detail.textContent : 'Не подтверждено. Проверьте поля и вход в кабинет; при истечении сессии войдите снова.';
    } catch (_) {
      status.textContent = 'Ответ не получен. Повторите отправку этой формы: повтор не создаст вторую запись. Содержимое сохранено в открытой форме до обновления страницы.';
    } finally {
      busy = false;
      fields.forEach(field => { field.disabled = false; });
    }
  });
}
