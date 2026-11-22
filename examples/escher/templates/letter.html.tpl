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

  The page is opm's packaged layout in the "paper" theme
  (opm-theme-paper.css, EB Garamond for the text, Alegreya Sans for the
  furniture); letter.css adds what a letter needs on top. The navigation
  above the letter, the register and the facsimile come from the
  edition-navigation, registers and iiif profiles ([project] profiles in
  opm.toml).
#]
---toml
[theme.body]
classes = ["opm-reader", "escher"]

[theme.layout.before]
width = "16rem"
label = "Kontexte"

[theme.layout.after]
width = "26rem"

[templating]
extends = "opm/layout.html.tpl"
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
    [% if $context?fragments?letter_head %]
    <header class="letter-head">
      [[ $context?fragments?letter_head ]]
    </header>
    [% endif %]

    <article class="content letter-text" id="letter-content" lang="[[ ($context?lang[. != ''], 'de')[1] ]]" data-iiif-base="[[ $context?features?iiif?base_uri ]]">
      [[ $context?content_html ]]
    </article>
  </div>
</div>

[% template body_end %]
  <script src="[[ $context?assets ]]/escher.js"></script>
[% endtemplate %]
