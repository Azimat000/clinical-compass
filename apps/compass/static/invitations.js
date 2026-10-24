/* Native dialog keeps focus inside and makes the cabinet behind it inert.
   Links retain a server-rendered destination when JavaScript is unavailable. */
(function () {
  'use strict';
  var dialog = document.getElementById('invite-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') { return; }
  var opener = null;
  var backdropPress = false;
  function open(trigger) {
    if (dialog.open) { return; }
    opener = trigger || document.activeElement;
    dialog.showModal();
    dialog.querySelector('[name="patient_id"]').focus({ preventScroll: true });
  }
  document.querySelectorAll('[data-invite-open]').forEach(function (trigger) {
    trigger.addEventListener('click', function (event) {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) { return; }
      event.preventDefault();
      open(trigger);
    });
  });
  dialog.querySelector('[data-invite-close]').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') { return; }
    var controls = Array.from(dialog.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex]'))
      .filter(function (node) { return !node.disabled && node.tabIndex >= 0 && node.getClientRects().length; });
    if (!controls.length) { return; }
    // Safari can omit buttons from native Tab navigation, depending on system
    // settings. Use the same complete cycle in every supported browser.
    var index = controls.indexOf(document.activeElement);
    var next = (index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
    event.preventDefault();
    controls[next].focus();
  });
  function outside(event) {
    var box = dialog.getBoundingClientRect();
    return event.target === dialog && (event.clientX < box.left || event.clientX > box.right ||
      event.clientY < box.top || event.clientY > box.bottom);
  }
  dialog.addEventListener('pointerdown', function (event) { backdropPress = outside(event); });
  dialog.addEventListener('click', function (event) {
    if (backdropPress && outside(event)) { dialog.close(); }
    backdropPress = false;
  });
  dialog.addEventListener('close', function () {
    if (opener && opener.isConnected) { opener.focus({ preventScroll: true }); }
  });
  // Previously shared invitation anchors still open the new window.
  function openBookmark() { if (location.hash === '#invitations') { open(); } }
  window.addEventListener('hashchange', openBookmark);
  openBookmark();
}());
