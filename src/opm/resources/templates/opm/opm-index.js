/* The collection index's filter and list/grid switch
   (default_index.html.tpl and .j2 include this file inline).

   Without JavaScript the index is a plain list: the bar stays hidden. The
   filter matches every word typed against an entry's text, ignoring case
   and accents; "/" jumps to it and Escape clears it. The chosen view is
   remembered per browser. */
(function () {
  var root = document.querySelector('[data-opm-index]');
  if (!root) return;
  var list = root.querySelector('.opm-doclist');
  var controls = root.querySelector('.opm-index__controls');
  if (!list || !controls) return;

  var items = Array.prototype.slice.call(list.querySelectorAll(':scope > .opm-doc'));
  var input = controls.querySelector('input[type="search"]');
  var count = controls.querySelector('.opm-index__count');
  var empty = root.querySelector('.opm-index__empty');
  var buttons = controls.querySelectorAll('[data-opm-view]');
  var KEY = 'opm-index-view';

  function fold(text) {
    return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }
  var texts = items.map(function (item) { return fold(item.textContent); });

  function filter() {
    var words = fold(input.value).split(/\s+/).filter(Boolean);
    var shown = 0;
    items.forEach(function (item, i) {
      var match = words.every(function (word) { return texts[i].indexOf(word) !== -1; });
      item.hidden = !match;
      if (match) shown++;
    });
    if (count) {
      count.textContent = words.length
        ? shown + ' / ' + items.length
        : items.length + ' ' + root.getAttribute(items.length === 1 ? 'data-one' : 'data-many');
    }
    if (empty) empty.hidden = shown > 0;
  }

  function markClipped() {
    items.forEach(function (item) {
      var body = item.querySelector('.opm-doc__body');
      if (body) body.classList.toggle('is-clipped', body.scrollHeight > body.clientHeight + 1);
    });
  }

  function setView(view, remember) {
    list.setAttribute('data-view', view);
    markClipped();
    Array.prototype.forEach.call(buttons, function (button) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-opm-view') === view));
    });
    if (remember) {
      try { localStorage.setItem(KEY, view); } catch (e) { /* not remembered */ }
    }
  }

  if (items.length >= Number(root.getAttribute('data-filter-min') || 2)) {
    controls.hidden = false;
  }

  if (input) {
    input.addEventListener('input', filter);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        input.value = '';
        filter();
      }
    });
    document.addEventListener('keydown', function (event) {
      if (event.key !== '/' || event.altKey || event.ctrlKey || event.metaKey) return;
      var active = document.activeElement;
      if (active && (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName))) return;
      event.preventDefault();
      input.focus();
    });
  }

  Array.prototype.forEach.call(buttons, function (button) {
    button.addEventListener('click', function () {
      setView(button.getAttribute('data-opm-view'), true);
    });
  });
  window.addEventListener('resize', markClipped);
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === 'grid' || saved === 'list') setView(saved, false);
  } catch (e) { /* the template's default view stays */ }
  markClipped();
})();
