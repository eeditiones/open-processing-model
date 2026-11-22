[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  journal: a single-column scholarly article with a sticky masthead and a
  contents rail, on opm's packaged page layout (opm/layout.html.tpl). The
  masthead is the layout's menubar: the journal line in place of the logo
  (linking to the collection index), the article title on the right. The
  rail is the layout's `before` column. opm-theme-journal.css sets opm's design tokens
  and styles what is journal's own.

  Its stylesheet, opm-theme-journal.css, is listed under [transform.web] assets in
  opm.toml: copied next to the output and linked by the base template.
#]
---toml
[theme.body]
classes = ["jr"]

[templating]
extends = "opm/layout.html.tpl"
---
[% template body_class %][[
  string-join((
    if ($context?fragments?toc) then 'jr--with-toc' else (),
    if (exists($context?chunk)) then 'jr--chunk' else (),
    if ($context?fragments?journal) then 'jr--journal-meta' else ()
  ), ' ')
]][% endtemplate %]

[% template logo %]
  [% if $context?fragments?journal %]
  [% if $context?index_url %]<a class="jr-journal" href="[[ $context?index_url ]]">[[ $context?fragments?journal ]]</a>
  [% else %]<div class="jr-journal">[[ $context?fragments?journal ]]</div>[% endif %]
  [% endif %]
[% endtemplate %]

[% template menu.toggles %]
  [% if exists($context?chunk) and normalize-space($context?fragments?title) != '' %]<li class="jr-article">[[ normalize-space($context?fragments?title) ]]</li>[% endif %]
[% endtemplate %]

[% template before %]
  [% if $context?fragments?toc %]
  <nav class="jr-rail__nav" aria-label="Article contents">
    <p class="jr-rail__title">Contents</p>
    [[ $context?fragments?toc ]]
  </nav>
  [% endif %]
[% endtemplate %]

<article class="content">
  [[ $context?content_html ]]
</article>

[% if $context?chunk?prev or $context?chunk?next %]
<nav class="jr-pager" aria-label="Article navigation">
  <div class="jr-pager__slot">
    [% if $context?chunk?prev %]
    <a href="[[ $context?chunk?prev ]].html" rel="prev">
      <span class="jr-pager__dir">&larr; Previous</span>
    </a>
    [% endif %]
  </div>
  <div class="jr-pager__slot jr-pager__slot--next">
    [% if $context?chunk?next %]
    <a href="[[ $context?chunk?next ]].html" rel="next">
      <span class="jr-pager__dir">Next &rarr;</span>
    </a>
    [% endif %]
  </div>
</nav>
[% endif %]
