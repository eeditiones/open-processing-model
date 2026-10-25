/* SPDX-FileCopyrightText: 2021-2026 eXistSolutions GmbH, e-editiones
   SPDX-License-Identifier: CC-BY-SA-4.0 */

/* The two readings of a letter and the facsimile beside the diplomatic one.
   Ported from the Escher app's escher.js; runs once, at the end of the page,
   before the pb-components bundle (a module script) upgrades the elements, so
   nodes can be moved freely.

   - The view switch sets body.escher--edited or body.escher--diplomatic and
     remembers the choice; letter.css does the rest.
   - Every <br class="lb"> the ODD writes starts a line: the line runs to the
     next one in the same paragraph and is wrapped in <span class="line">,
     carrying the image and rectangle of its region in the facsimile.
   - In the diplomatic view, hovering over a line shows that region of the page
     above it, and tells <pb-facsimile> to go there.
   - A checkbox in the register highlights every mention with its key. */
(function () {
  'use strict';

  var content = document.getElementById('letter-content');
  if (!content) return;

  // ── Facsimile drawer ───────────────────────────────────────

  /* pb-facsimile loads OpenSeadragon on demand and creates its viewer when the
     library announces itself. OpenSeadragon's default WebGL drawer can leave
     the viewer blank (it does in some Chrome setups, with no error); the
     canvas drawer is plenty for a page of manuscript. This listener is
     registered before pb-facsimile's, so it runs first. */
  function useCanvasDrawer() {
    if (window.OpenSeadragon && OpenSeadragon.DEFAULT_SETTINGS) {
      OpenSeadragon.DEFAULT_SETTINGS.drawer = 'canvas';
    }
  }
  useCanvasDrawer();
  window.addEventListener('es-bridge-openseadragon-loaded', useCanvasDrawer, { once: true });

  var KEY = 'opm-escher-view';
  var body = document.body;
  var iiifBase = content.getAttribute('data-iiif-base') || '';

  // ── View switch ────────────────────────────────────────────

  var buttons = document.querySelectorAll('[data-view]');

  function setView(view) {
    body.classList.toggle('escher--diplomatic', view === 'diplomatic');
    body.classList.toggle('escher--edited', view !== 'diplomatic');
    buttons.forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-view') === view));
    });
  }

  function savedView() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null; /* private mode: start from the edited text */
    }
  }

  setView(savedView() === 'diplomatic' ? 'diplomatic' : 'edited');

  /* A viewer created while its column was hidden measured a container of no
     size; once the column is back, have it measure again and fit the page. */
  function refitFacsimile() {
    var facsimile = document.querySelector('pb-facsimile');
    var viewer = facsimile && facsimile.viewer;
    if (!viewer) return;
    requestAnimationFrame(function () {
      if (viewer.forceResize) viewer.forceResize();
      viewer.viewport.goHome(true);
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      var view = button.getAttribute('data-view');
      setView(view);
      if (view === 'diplomatic') refitFacsimile();
      try { localStorage.setItem(KEY, view); } catch (e) { /* not remembered */ }
    });
  });

  function isDiplomatic() {
    return body.classList.contains('escher--diplomatic');
  }

  // ── Lines ──────────────────────────────────────────────────

  /* The last node of the line starting at br: the node before the next line
     break inside root, or the last node of root. */
  function endOfLine(root, br) {
    var walker = document.createTreeWalker(root);
    walker.currentNode = br;
    var last = null;
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node.nodeType === Node.ELEMENT_NODE && node.matches('br.lb')) {
        return node;
      }
      last = node;
    }
    return last;
  }

  /* Mapping coordinates are x1,y1,x2,y2; IIIF wants x,y,width,height. */
  function regionOf(coords) {
    var c = coords.split(',').map(function (n) { return parseInt(n, 10); });
    return [c[0], c[1], c[2] - c[0], c[3] - c[1]];
  }

  Array.prototype.slice.call(content.querySelectorAll('br.lb')).forEach(function (br) {
    var root = br.parentElement.closest('p, div') || content;
    var end = endOfLine(root, br);
    if (!end) return;

    var range = document.createRange();
    range.setStartBefore(br);
    if (end.nodeName === 'BR') {
      range.setEndBefore(end);
    } else {
      range.setEndAfter(end);
    }

    var line = document.createElement('span');
    line.className = 'line';
    var image = br.getAttribute('data-image');
    var coords = br.getAttribute('data-coords');
    if (image && coords) {
      line.setAttribute('data-image', image);
      line.setAttribute('data-region', regionOf(coords).join(','));
    }
    line.appendChild(range.extractContents());
    range.insertNode(line);
  });

  // ── Facsimile region on hover ──────────────────────────────

  /* One image, reused: positioned above the line under the pointer. */
  var snippet = document.createElement('img');
  snippet.className = 'line-region';
  snippet.alt = '';
  snippet.hidden = true;
  content.appendChild(snippet);

  var current = null;

  function showRegion(line) {
    var image = line.getAttribute('data-image');
    var region = line.getAttribute('data-region');
    var src = iiifBase + image + '/' + region + '/full/0/default.jpg';

    if (window.pbEvents) {
      window.pbEvents.emit('pb-show-annotation', 'transcription', {
        file: image,
        coordinates: region.split(',').map(Number)
      });
    }

    var buffer = new Image();
    buffer.addEventListener('load', function () {
      if (current !== line) return;
      snippet.src = src;
      snippet.style.visibility = 'hidden';
      snippet.hidden = false;
      snippet.classList.toggle('line-region--wide', buffer.naturalWidth > content.clientWidth);
      var box = content.getBoundingClientRect();
      var first = line.getClientRects()[0];
      if (!first) return;
      snippet.style.left = (snippet.classList.contains('line-region--wide') ? 0 : first.left - box.left) + 'px';
      snippet.style.top = (first.top - box.top - snippet.offsetHeight - 6) + 'px';
      snippet.style.visibility = '';
    });
    buffer.src = src;
  }

  content.querySelectorAll('.line[data-region]').forEach(function (line) {
    line.addEventListener('mouseenter', function () {
      if (!isDiplomatic()) return;
      current = line;
      line.classList.add('line--active');
      showRegion(line);
    });
    line.addEventListener('mouseleave', function () {
      current = null;
      line.classList.remove('line--active');
      snippet.hidden = true;
    });
  });

  // ── Register ───────────────────────────────────────────────

  document.querySelectorAll('.register input[data-ref]').forEach(function (checkbox) {
    var key = checkbox.getAttribute('data-ref');
    checkbox.addEventListener('change', function () {
      content.querySelectorAll('[data-ref]').forEach(function (mention) {
        if (mention.getAttribute('data-ref') === key) {
          mention.classList.toggle('highlight', checkbox.checked);
        }
      });
    });
  });
})();
