[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  monograph: multi-page, text-centric reading, on opm's packaged page layout
  (opm/layout.html.tpl). The layout writes the menubar and the breadcrumb
  toolbar; the template adds text-size buttons, the contents as the `before`
  column and page-turn links. opm-theme-paper.css styles it all.

  Design: "Der Römerbrief" — paper, ink and one rubric red; EB Garamond for
  the text, Alegreya Sans for UI chrome. Optional context values:
  context.author (small caps before the work title) and context.lang
  (language of the text, default "de", needed for hyphenation).

  Its stylesheet, opm-theme-paper.css, is listed under [transform.web] assets in
  opm.toml: copied next to the output and linked by the base template.
#]
---toml
[theme.body]
classes = ["opm-reader"]

[templating]
extends = "opm/layout.html.tpl"
---

[# The running head names the work, not the edition (site_name): the
   `title` fragment without its markup. #]
[% template! logo %]
<a href="[[ ($context?home_url, $context?index_url, 'index.html')[string(.) != ''][1] ]]">
  <span class="logo__title">[[ (normalize-space($context?fragments?title), 'Chapbook')[. != ''][1] ]]</span>
</a>
[% endtemplate %]

[% template body_class %][% if $context?fragments?toc %]opm-reader--with-toc[% endif %][% endtemplate %]

[# Reader-set text size, remembered per browser. #]
[% template menu.toggles %]
  <li class="opm-reader-zoom">
    <button type="button" data-chap-zoom="-0.1" title="Smaller text" aria-label="Smaller text">A&minus;</button>
    <button type="button" data-chap-zoom="0.1" title="Larger text" aria-label="Larger text">A+</button>
  </li>
[% endtemplate %]

[% template before %]
  [% if $context?fragments?toc %]
  <nav class="opm-reader-toc rb-toc[[ if (exists($context?chunk)) then ' rb-toc--chunk' else '' ]]" aria-label="Contents">
    <p class="opm-reader-toc__title">Contents</p>
    [# Links to the page being read come out as `#<its xml:id>`: mark them. #]
    [% if $context?chunk?xml_id %]
    [% let $link = 'href="#' || $context?chunk?xml_id || '"' %]
    [[ parse-xml-fragment(replace(serialize($context?fragments?toc), $link, $link || ' aria-current="page"', 'q')) ]]
    [% endlet %]
    [% else %]
    [[ $context?fragments?toc ]]
    [% endif %]
  </nav>
  [% endif %]
[% endtemplate %]

<div class="opm-reader-page[[ if (exists($context?chunk)) then ' opm-reader-page--chunk' else '' ]][[ if ($context?fragments?toc) then ' opm-reader-page--with-toc' else '' ]]">
  <div class="opm-reader-body">
    <article class="content" id="opm-reader-content" lang="[[ ($context?lang[. != ''], 'de')[1] ]]">
      [[ $context?content_html ]]
    </article>
  </div>

  [% if $context?chunk?prev or $context?chunk?next %]
  <nav class="opm-reader-folio-nav__foot" aria-label="Page navigation">
    <div>
      [% if $context?chunk?prev %]<a href="[[ $context?chunk?prev ]].html" rel="prev">&#8592;&ensp;Previous</a>[% endif %]
    </div>
    <div>
      [% if $context?chunk?next %]<a href="[[ $context?chunk?next ]].html" rel="next">Next&ensp;&#8594;</a>[% endif %]
    </div>
  </nav>
  [% endif %]
</div>

[% template body_end %]
  [% if $context?chunk?prev %]
  <div class="opm-reader-folio-nav__rail opm-reader-folio-nav__rail--prev">
    <a href="[[ $context?chunk?prev ]].html" rel="prev" title="Previous page (left arrow key)">
      <span class="opm-reader-folio-nav__chevron" aria-hidden="true">&#8592;</span>
      <span class="opm-reader-folio-nav__dir">Previous</span>
    </a>
  </div>
  [% endif %]
  [% if $context?chunk?next %]
  <div class="opm-reader-folio-nav__rail opm-reader-folio-nav__rail--next">
    <a href="[[ $context?chunk?next ]].html" rel="next" title="Next page (right arrow key)">
      <span class="opm-reader-folio-nav__chevron" aria-hidden="true">&#8594;</span>
      <span class="opm-reader-folio-nav__dir">Next</span>
    </a>
  </div>
  [% endif %]

  <script>
  (function () {
    var content = document.getElementById('opm-reader-content');

    [# The notes arrive apparatus-first already: `[transform] footnote_order`
       in opm.toml orders each page's footnotes before they are placed. #]
    if (content) {
      var KEY = 'opm-reader-font-size';
      try {
        var saved = localStorage.getItem(KEY);
        if (saved) content.style.fontSize = saved + 'rem';
      } catch (e) { /* private mode: text stays at its default size */ }

      document.querySelectorAll('[data-chap-zoom]').forEach(function (button) {
        button.addEventListener('click', function () {
          var step = parseFloat(button.getAttribute('data-chap-zoom'));
          var current = parseFloat(getComputedStyle(content).fontSize) / 16;
          var next = Math.max(0.8, Math.min(2, current + step)).toFixed(2);
          content.style.fontSize = next + 'rem';
          try { localStorage.setItem(KEY, next); } catch (e) { /* not remembered */ }
        });
      });
    }

    [# Arrow keys turn the page, as the rails do. #]
    var prev = document.querySelector('.opm-reader-folio-nav__rail--prev a');
    var next = document.querySelector('.opm-reader-folio-nav__rail--next a');
    if (!prev && !next) return;
    document.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      var active = document.activeElement;
      if (active && (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(active.tagName))) return;
      if (event.key === 'ArrowLeft' && prev) window.location.assign(prev.getAttribute('href'));
      else if (event.key === 'ArrowRight' && next) window.location.assign(next.getAttribute('href'));
    });
  })();
  </script>
[% endtemplate %]
