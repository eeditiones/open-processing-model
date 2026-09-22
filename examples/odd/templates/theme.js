// SPDX-FileCopyrightText: 2026 e-editiones
// SPDX-License-Identifier: CC0-1.0

// Light/dark toggle. Runs in <head> before first paint so a stored choice does
// not flash; with nothing stored the stylesheet's prefers-color-scheme wins and
// no data-theme attribute is set at all.
(function () {
  var KEY = 'opm-doc-theme';
  var root = document.documentElement;

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function systemDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function current() {
    return root.getAttribute('data-theme') || (systemDark() ? 'dark' : 'light');
  }

  var saved = stored();
  if (saved === 'dark' || saved === 'light') {
    root.setAttribute('data-theme', saved);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.querySelector('[data-doc-theme]');
    if (!button) return;

    function label() {
      var next = current() === 'dark' ? 'light' : 'dark';
      button.setAttribute('aria-label', 'Switch to ' + next + ' theme');
    }

    button.hidden = false;
    label();
    button.addEventListener('click', function () {
      var next = current() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try {
        localStorage.setItem(KEY, next);
      } catch (e) {
        /* private mode: the choice just does not persist */
      }
      label();
    });
  });
})();
