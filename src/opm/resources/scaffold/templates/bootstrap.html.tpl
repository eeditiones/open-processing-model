[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  bootstrap: the document in a Bootstrap 5 page. Bootstrap brings its own
  grid, so this extends opm/base.html.tpl (the <head> handling) rather than
  the page layout.
#]
---json
{ "templating": { "extends": "opm/base.html.tpl" } }
---
[% template html_attributes %] data-bs-theme="auto"[% endtemplate %]

[% template styles %]
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
    rel="stylesheet"
    integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
    crossorigin="anonymous"
  >
[% endtemplate %]

[% template body %]
  <header class="border-bottom mb-4">
    <nav class="navbar navbar-expand-lg container py-3">
      <span class="navbar-brand fw-semibold mb-0 h1">TEI Publisher Preview</span>
    </nav>
  </header>
  <main class="container my-4 content">
    [[ $context?content_html ]]
  </main>
  [% if $context?chunk?prev or $context?chunk?next %]
  <footer class="border-top mt-4 py-3">
    <nav class="container d-flex justify-content-between">
      [% if $context?chunk?prev %]
      <a href="[[ $context?chunk?prev ]].html" class="btn btn-outline-secondary">&lsaquo; Previous</a>
      [% else %]
      <span></span>
      [% endif %]
      [% if $context?chunk?next %]
      <a href="[[ $context?chunk?next ]].html" class="btn btn-outline-secondary">Next &rsaquo;</a>
      [% endif %]
    </nav>
  </footer>
  [% endif %]
[% endtemplate %]

[% template body_end %]
  <script
    src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
    integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
    crossorigin="anonymous"
  ></script>
[% endtemplate %]
