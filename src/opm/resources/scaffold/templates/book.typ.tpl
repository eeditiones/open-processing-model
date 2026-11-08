[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0
#]
// TEI Typst document shell (ilm).
// Override via [transform.typst] template in project config or --template

#import "@preview/zebraw:0.6.3": *
#show: zebraw.with(..zebraw-themes.zebra, lang: true, lang-color: color.mix((blue, 15%), (white, 85%)))

#import "@preview/ilm:2.1.0": *

#set text(lang: "en")

#show: ilm.with(
  title: [[[ ($context?metadata?title?*, 'Your Title')[1] ]]],
  authors: [[
    let $authors := $context?metadata?authors?*
    return if (count($authors) > 1) then '(' || string-join($authors ! ('"' || . || '"'), ', ') || ')'
    else '"' || $authors[1] || '"'
  ]],
  abstract: [[[ ($context?metadata?abstract?*, '')[1] ]]],
  figure-index: (enabled: true),
  table-index: (enabled: true),
  listing-index: (enabled: true)
)
#set text(font: ("New Computer Modern", "Times New Roman"))
#show raw: set text(font: ("Iosevka", "DejaVu Sans Mono", "Courier New"))

[% include "opm_css_fns_default.typ.j2" %]

#show: marginalia.setup.with(
  inner: (far: 1.8cm),
  outer: (far: opm-margin-note-far, width: opm-margin-note-width, sep: opm-margin-note-sep),
  top: 2.5cm,
  bottom: 2.5cm,
)

// Extra handlers for ODD @cssClass / @rend names (see templates/docbook.typ.tpl):
// #let opm-css-fns = opm-css-fns + (
//   center: (body) => align(center, body),
//   note: (body) => block(
//     width: 100%,
//     inset: (left: 0.8em, y: 0.35em),
//     stroke: (left: 4pt + rgb("#d07f00")),
//     body,
//   ),
// )

[[ $context?odd_typst ]]

#set heading(numbering: "1.")
#set par(justify: true)

[% include "opm_css.typ.j2" %]

[[ $context?content_typst ]]
