/* Each drug can have several independent descriptions. Native form works without JS. */
(() => {
  for (const row of document.querySelectorAll('[data-feedback-response]')) {
    const choice = row.querySelector('input[type="checkbox"]');
    const detail = row.querySelector('[data-feedback-detail]');
    const text = detail.querySelector('textarea');
    function update() {
      detail.hidden = !choice.checked;
      text.required = choice.checked;
    }
    choice.addEventListener('change', update);
    update();
  }
})();
