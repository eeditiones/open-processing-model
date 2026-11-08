[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  journal: a single-column scholarly article with a sticky masthead and a
  contents rail, on opm's packaged page layout (opm/layout.html.tpl). The
  masthead is the layout's menubar: the journal line in place of the logo,
  the article title on the right. The rail is the layout's `before` column;
  journal.css styles it all.

  Its stylesheet, journal.css, is listed under [transform.web] assets in
  opm.toml: copied next to the output and linked by the base template.
#]
---toml
styles = [
  "https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400..700;1,8..60,400..600&display=swap",
]

[theme.body]
classes = ["jr"]

[templating]
extends = "opm/layout.html.tpl"
---
[% template meta %]
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
[% endtemplate %]

[# The article title is the `title` fragment without its markup. #]
[% template title %]<title>[[ (normalize-space($context?fragments?title), 'Journal article')[. != ''][1] ]]</title>[% endtemplate %]

[% template body_class %][[
  string-join((
    if ($context?fragments?toc) then 'jr--with-toc' else (),
    if (exists($context?chunk)) then 'jr--chunk' else (),
    if ($context?fragments?journal) then 'jr--journal-meta' else ()
  ), ' ')
]][% endtemplate %]

[% template logo %]
  [% if $context?fragments?journal %]<div class="jr-journal">[[ $context?fragments?journal ]]</div>[% endif %]
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
