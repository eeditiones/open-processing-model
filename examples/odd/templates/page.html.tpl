[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  A page of the ODD documentation site, on opm's packaged page layout
  (opm/layout.html.tpl): its menubar shows the logo and site name, the edition,
  the search box and the theme switch; the navigation is the `before`
  column, the page `content`, "On this page" `after`. `opm odd document`
  copies the stylesheets, scripts, fonts and logo (context.logo, by default
  logo.svg) into assets/; document.css styles it all.
#]
---toml
[body]
classes = ["doc"]

[templating]
extends = "opm/layout.html.tpl"
---
[#
  The browser-tab icon. One SVG, which every current browser takes and which
  stays sharp at any size; no .ico or apple-touch-icon, because rasterizing
  one would mean a dependency the site builder does not have. A bare file
  name is resolved under the shared assets/ directory.
#]
[% template meta %]
  [% let $logo = string($context?logo) %]
  <link rel="icon" href="[[ if ($logo != '' and $context?assets and not(contains($logo, '/')) and not(contains($logo, ':'))) then $context?assets || '/' || $logo else $logo ]]" type="![[ if (ends-with($logo, '.svg')) then 'image/svg+xml' else () ]]">
  [% endlet %]
[% endtemplate %]

[% template title %]<title>[% if $context?chunk?xml_id and $context?chunk?xml_id != 'index' %][[ $context?chunk?xml_id ]] — [% endif %][[ $context?site_name ]]</title>[% endtemplate %]

[# Before the page paints, so a reader's light/dark choice never flashes. #]
[% template scripts %]
  <script src="[[ $context?assets ]]/theme.js"></script>
  <script src="[[ $context?assets ]]/search.js" defer></script>
[% endtemplate %]

[% template body_class %][% if $context?fragments?nav %]doc--with-nav[% endif %][% endtemplate %]

[% template menu_left %]
  [% if $context?edition %]<li class="doc-edition">[[ $context?edition ]]</li>[% endif %]
[% endtemplate %]

[% template menu_toggles %]
  <li class="doc-search" data-idents="idents.json">
    <form role="search">
      <label class="visually-hidden" for="doc-q">Find an element, class or macro</label>
      <input id="doc-q" type="search" placeholder="p, att.global, model.pLike…" autocomplete="off">
      <ul class="doc-search__hits" hidden></ul>
    </form>
  </li>
  <li>
    <button class="doc-theme" type="button" data-doc-theme hidden aria-label="Switch theme">
      <svg class="doc-theme__moon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"
              d="M15.2 3.6A8.6 8.6 0 1 0 20.4 14 6.8 6.8 0 0 1 15.2 3.6z"/>
      </svg>
      <svg class="doc-theme__sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="3.6" fill="none" stroke="currentColor" stroke-width="1.6"/>
        <path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
              d="M12 3.2v1.8M12 19v1.8M4.9 4.9l1.3 1.3M17.8 17.8l1.3 1.3M3.2 12h1.8M19 12h1.8M4.9 19.1l1.3-1.3M17.8 6.2l1.3-1.3"/>
      </svg>
    </button>
  </li>
[% endtemplate %]

[# The navigation, with the link to this page marked as the current one. #]
[% template before %]
  [% if $context?fragments?nav %]
  <nav class="doc-sidebar" aria-label="Site">
    <p class="doc-sidebar__label">Contents</p>
    [% let $link = 'href="' || $context?chunk?file || '"' %]
    [[ parse-xml-fragment(replace(serialize($context?fragments?nav), $link, $link || ' aria-current="page"', 'q')) ]]
    [% endlet %]
  </nav>
  [% endif %]
[% endtemplate %]

<div class="doc-main">
  [[ $context?content_html ]]
  [[ $context?fragments?chapterend ]]
</div>

[% template after %]
  <div class="doc-aside" aria-label="On this page" data-page-toc>
    [[ $context?fragments?chapternav ]]
    <p class="doc-aside__label">On this page</p>
    <ul></ul>
  </div>
[% endtemplate %]

[% template footer %]
  <div class="doc-footer">
    <span>[[ $context?site_name ]][% if $context?edition %] · [[ $context?edition ]][% endif %]</span>
    [% if $context?rights %]<span>[[ $context?rights ]]</span>[% endif %]
  </div>
[% endtemplate %]
