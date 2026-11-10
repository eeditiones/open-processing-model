[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0

  A letter in two readings. The page carries the transcription once; the
  toolbar switch (escher.js) sets body.escher--edited or
  body.escher--diplomatic and letter.css shows the reading that goes with it:

  - edited: running text, popovers for names and abbreviations, and the
    register ("Kontexte") in the `before` column;
  - diplomatic: line by line as in the manuscript, with additions,
    deletions and hyphens, and the facsimile in the `after` column. Hovering
    over a line shows its crop of the page above it and moves the viewer to
    the line.

  The shell comes from escher.html.tpl.
#]
---toml
[theme.layout.before]
width = "16rem"
label = "Kontexte"

[theme.layout.after]
width = "26rem"

# The <pb-page> the web components need around the page. They resolve
# relative URLs against its endpoint; api-version is pinned so pb-page does
# not probe ./api/version. It loads a component theme stylesheet: point it at
# the packaged one rather than a components.css beside the page.
[pb_page]
endpoint = "."
api-version = "1.0.0"
theme = "https://cdn.jsdelivr.net/npm/@teipublisher/pb-components@3.6.8/css/components.css"

[templating]
extends = "escher.html.tpl"
---
[% template title %]
<title>[[ (normalize-space($context?fragments?breadcrumbs), $context?site_name)[. != ''][1] ]]</title>
[% endtemplate %]

[# As in the edition: the letter list, then the letter's signature. The title
   itself heads the letter. #]
[% template breadcrumb %]
  <a href="[[ ($context?index_url, '../index.html')[string(.) != ''][1] ]]">Briefe</a>[% if $context?document %] · AES [[ $context?document ]][% endif %]
[% endtemplate %]

[% template toggle %]
  <li class="view-switch" role="group" aria-label="Ansicht">
    <button type="button" data-view="edited" aria-pressed="true">Edierter Text</button>
    <button type="button" data-view="diplomatic" aria-pressed="false">Diplomatischer Text</button>
  </li>
[% endtemplate %]

<div class="opm-reader-page opm-reader-page--chunk">
  <div class="opm-reader-body">
    [% if exists($context?chunk) %]
    [#
      The edition_navigation fragment is a hidden <nav> whose data-* attributes
      carry the neighbouring letters' numbers (see correspContext in the ODD).
      Only letters chunked in this run have a page to link to; the example
      holds five letters of a far larger correspondence. $target gives the
      letter a link points to, or nothing.

      Every letter is chunked into a directory of its own, named by its number
      ([chunking] document_name), with the page as its index.html: link the
      directory, as the edition's own URLs (/briefe/B0097) do.
    #]
    [% let $nav = $context?fragments?edition_navigation %]
    [% let $value = function($name) { normalize-space(($nav//@*[local-name() = 'data-' || $name])[1]) } %]
    [% let $target = function($name) { $value($name)[. != ''][. = $context?documents?*] } %]
    [# Two rows, as in the edition: the edition's own order, then the
       letters exchanged between the same correspondents. #]
    <nav class="letter-nav" aria-label="Briefnavigation">
      [% for $row in (
          [
            map { 'name': 'previous', 'label': 'Vorheriger Brief in Edition', 'icon': 'M15 6 9 12l6 6' },
            map { 'name': 'next', 'label': 'Nächster Brief in Edition', 'icon': 'm9 6 6 6-6 6', 'end': true() }
          ],
          [
            map { 'name': 'previous-in-correspondence', 'label': 'Vorheriger Brief', 'icon': 'M13 6 7 12l6 6M18 6l-6 6 6 6' },
            map { 'name': 'next-in-correspondence', 'label': 'Nächster Brief', 'icon': 'm6 6 6 6-6 6M11 6l6 6-6 6', 'end': true() }
          ]
        ) %]
      <div class="letter-nav__row[[ if ($row(1)?name = 'previous') then '' else ' letter-nav__row--thread' ]]">
        [% for $link in $row?* %]
        [% if $link?name = 'next-in-correspondence' and $value('correspondence') != '' %]
        <span class="letter-nav__mark">Korrespondenz: [[ $value('correspondence') ]]</span>
        [% endif %]
        [% let $id = $target($link?name) %]
        <a class="letter-nav__link[[ if ($link?end) then ' letter-nav__link--end' else '' ]]" href="![[ $id ! ('../' || . || '/' || (if ($context?chunk?file != 'index.html') then $context?chunk?file else '')) ]]" title="![[ $id ]]" aria-hidden="![[ empty($id) ]]"><svg class="letter-nav__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="[[ $link?icon ]]"></path></svg><span class="letter-nav__dir">[[ $link?label ]]</span></a>
        [% endlet %]
        [% endfor %]
      </div>
      [% endfor %]
    </nav>
    [% endlet %]
    [% endlet %]
    [% endlet %]
    [% endif %]

    [% if $context?fragments?letter_head %]
    <header class="letter-head">
      [[ $context?fragments?letter_head ]]
    </header>
    [% endif %]

    <article class="content letter-text" id="letter-content" lang="[[ ($context?lang[. != ''], 'de')[1] ]]" data-iiif-base="[[ $context?iiif_base ]]">
      [[ $context?content_html ]]
    </article>
  </div>
</div>

[% template before %]
  [% if $context?fragments?register %]
  <section class="letter-register" aria-label="Kontexte">
    <h2 class="letter-register__title">Kontexte</h2>
    [[ $context?fragments?register ]]
  </section>
  [% endif %]
[% endtemplate %]

[#
  pb-facsimile collects the page images the first <lb/> of each page
  announces (<pb-facs-link facs>) and prefixes them with base-uri. The tiles
  come from another origin: without cors="Anonymous" OpenSeadragon's WebGL
  drawer may not upload them and the viewer stays empty. The sequence mode
  shows one page at a time instead of stacking them.
#]
[% template after %]
  <aside class="letter-facs" aria-label="Faksimile">
    <pb-facsimile base-uri="[[ $context?iiif_base ]]" cors="Anonymous" default-zoom-level="0"
      show-sequence-control show-navigator show-navigation-control subscribe="transcription"></pb-facsimile>
  </aside>
[% endtemplate %]

[% template body_end %]
  <script src="[[ $context?assets ]]/escher.js"></script>
[% endtemplate %]
