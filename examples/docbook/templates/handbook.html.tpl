[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  handbook: documentation-oriented reading (Starlight-inspired), on opm's
  packaged page layout (opm/layout.html.tpl). The layout writes the menubar
  and the breadcrumb toolbar; the site navigation is its `before` column, and
  the "On this page" outline sits beside the text inside the content block.
  handbook.css styles it all.

  Its stylesheet, handbook.css, is listed under [transform.web] assets in
  opm.toml: copied next to the output and linked by the base template.
#]
---toml
styles = [
  "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=Sora:wght@500;600;700&display=swap",
]

[theme.body]
classes = ["handbook"]

[theme.layout.before]
span_top = true

[templating]
extends = "opm/layout.html.tpl"
---
[% template meta %]
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
[% endtemplate %]

[% template title %]
<title>[[ (normalize-space($context?fragments?title), 'Handbook')[. != ''][1] ]]</title>
[% endtemplate %]

[# The menubar names the site, else the document. #]
[% template logo %]
<a href="[[ ($context?home_url, $context?index_url, 'index.html')[string(.) != ''][1] ]]">
  [% let $logo = string($context?logo) %]
  [% if $logo != '' %]<img class="logo__image" src="[[ if ($context?assets and not(contains($logo, '/')) and not(contains($logo, ':'))) then $context?assets || '/' || $logo else $logo ]]" alt="">[% endif %]
  [% endlet %]
  <span class="logo__title">[[ (string($context?site_name), normalize-space($context?fragments?title), 'Handbook')[. != ''][1] ]]</span>
</a>
[% endtemplate %]

[% template body_class %][% if $context?fragments?toc %]handbook--with-toc[% endif %][% endtemplate %]

[% template before %]
  [% if $context?fragments?toc %]
  <nav class="hb-sidebar" aria-label="Site navigation">
    [[ $context?fragments?toc ]]
  </nav>
  [% endif %]
[% endtemplate %]

<div class="hb-main">
  <div class="hb-page[[ if (exists($context?chunk)) then ' hb-page--chunk' else '' ]]">
    <article class="content">
      [[ $context?content_html ]]
    </article>

    [% if $context?chunk?prev or $context?chunk?next %]
    <nav class="hb-pager" aria-label="Page navigation">
      <div class="hb-pager__prev">
        [% if $context?chunk?prev %]
        <a href="[[ $context?chunk?prev ]].html">
          <span class="hb-pager__dir">Previous</span>
          <span class="hb-pager__label">Previous page</span>
        </a>
        [% endif %]
      </div>
      <div class="hb-pager__next">
        [% if $context?chunk?next %]
        <a href="[[ $context?chunk?next ]].html">
          <span class="hb-pager__dir">Next</span>
          <span class="hb-pager__label">Next page</span>
        </a>
        [% endif %]
      </div>
    </nav>
    [% endif %]
  </div>

  <aside class="hb-outline" aria-label="On this page" hidden>
    <p class="hb-outline__title">On this page</p>
    <nav class="hb-outline__nav"></nav>
  </aside>
</div>

[% template body_end %]
  <script>
  (function () {
    var article = document.querySelector('.hb-page .content');
    var outline = document.querySelector('.hb-outline');
    var nav = document.querySelector('.hb-outline__nav');
    if (!article || !outline || !nav) return;

    var heads = article.querySelectorAll('h2[id], h3[id]');
    if (!heads.length) {
      heads = article.querySelectorAll('h2, h3');
      Array.prototype.forEach.call(heads, function (h, i) {
        if (!h.id) {
          var base = (h.textContent || 'section').trim()
            .toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').slice(0, 48);
          h.id = base ? base + (i ? '-' + i : '') : 'section-' + i;
        }
      });
    }
    if (!heads.length) return;

    var ul = document.createElement('ul');
    Array.prototype.forEach.call(heads, function (h) {
      var li = document.createElement('li');
      li.className = h.tagName === 'H3' ? 'hb-outline__h3' : 'hb-outline__h2';
      var a = document.createElement('a');
      a.href = '#' + h.id;
      a.textContent = (h.textContent || '').trim();
      li.appendChild(a);
      ul.appendChild(li);
    });
    nav.appendChild(ul);
    outline.hidden = false;
  })();
  </script>
[% endtemplate %]
