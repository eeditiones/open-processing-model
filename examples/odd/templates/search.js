/* SPDX-FileCopyrightText: 2026 e-editiones
   SPDX-License-Identifier: CC0-1.0 */

(function () {
  var form = document.querySelector('.doc-search');
  if (!form) return;
  var input = form.querySelector('input');
  var list = form.querySelector('.doc-search__hits');
  var url = form.getAttribute('data-idents');
  var items = [];
  var selected = -1;

  function hrefFor(item) {
    return item.href || ('ref-' + item.ident + '.html');
  }

  function render(hits) {
    list.innerHTML = '';
    selected = -1;
    if (!hits.length) {
      list.hidden = true;
      return;
    }
    hits.slice(0, 20).forEach(function (item, i) {
      var li = document.createElement('li');
      var a = document.createElement('a');
      a.href = hrefFor(item);
      a.innerHTML = '<code>' + item.ident + '</code><span class="doc-search__kind">' + item.kind + '</span>';
      li.appendChild(a);
      list.appendChild(li);
    });
    list.hidden = false;
  }

  function query(q) {
    q = (q || '').trim().toLowerCase();
    if (!q) return [];
    return items.filter(function (item) {
      return item.ident.toLowerCase().indexOf(q) !== -1;
    });
  }

  fetch(url)
    .then(function (r) { return r.json(); })
    .then(function (data) { items = data; })
    .catch(function () { items = []; });

  input.addEventListener('input', function () {
    render(query(input.value));
  });
  input.addEventListener('keydown', function (ev) {
    var links = list.querySelectorAll('a');
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      selected = Math.min(selected + 1, links.length - 1);
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      selected = Math.max(selected - 1, 0);
    } else if (ev.key === 'Enter' && selected >= 0 && links[selected]) {
      ev.preventDefault();
      window.location = links[selected].href;
      return;
    } else if (ev.key === 'Escape') {
      list.hidden = true;
      return;
    } else {
      return;
    }
    Array.prototype.forEach.call(list.children, function (li, i) {
      li.setAttribute('aria-selected', i === selected ? 'true' : 'false');
    });
  });
  document.addEventListener('click', function (ev) {
    if (!form.contains(ev.target)) list.hidden = true;
  });
})();

(function () {
  var aside = document.querySelector('[data-page-toc]');
  var main = document.querySelector('.doc-main');
  if (!aside || !main) return;
  var ul = aside.querySelector('ul');
  if (!ul) return;
  var seen = {};
  function entry(id, label, sub) {
    if (!id || !label || seen[id]) return;
    seen[id] = true;
    var li = document.createElement('li');
    if (sub) li.className = 'is-sub';
    var a = document.createElement('a');
    a.href = '#' + id;
    a.textContent = label;
    li.appendChild(a);
    ul.appendChild(li);
  }
  // A reference section lists what it holds: the attributes the spec defines
  // itself (the inherited ones live in the tree above the list, which has no
  // anchors of its own) and the class / content relations under it.
  function subEntries(section) {
    section.querySelectorAll('dl.att-def > dt[id], dl.spec-facts > dt[id]')
      .forEach(function (dt) {
        var dd = dt.nextElementSibling;
        if (dd && dd.tagName === 'DD' && !(dd.textContent || '').trim()) return;
        var name = dt.querySelector('.att-def__name');
        entry(dt.id, ((name || dt).textContent || '').trim(), true);
      });
  }
  // What the rail links to. A chapter's headings sit in a div that carries the
  // anchor, which is what the fragment links in the prose point at; a heading
  // with neither its own id nor a section of its own — the groups on the home
  // page — gets one made from its text, or the page's own container would
  // stand in for every one of them and the rail would show only the first.
  function anchor(heading) {
    if (heading.id) return heading.id;
    var wrap = heading.closest('[id]');
    if (wrap && wrap !== main && !seen[wrap.id]) return wrap.id;
    var base = (heading.textContent || '').trim().toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'section';
    var id = base;
    for (var n = 2; document.getElementById(id); n++) id = base + '-' + n;
    heading.id = id;
    return id;
  }
  main.querySelectorAll('h2, h3').forEach(function (heading) {
    var id = anchor(heading);
    entry(id, (heading.textContent || '').trim(), heading.tagName === 'H3');
    var section = heading.tagName === 'H2' ? heading.closest('.spec-section') : null;
    if (section) subEntries(section);
  });
  if (!ul.children.length) {
    // Keep the rail when it still carries the chapter's previous/next pair.
    var nav = aside.querySelector('.chapter-nav');
    ul.hidden = true;
    var label = aside.querySelector('.doc-aside__label');
    if (label) label.hidden = true;
    if (!nav) aside.hidden = true;
  }
})();
