[#
  SPDX-FileCopyrightText: 2026 e-editiones
  SPDX-License-Identifier: CC0-1.0
#]
// JATS journal article shell (arkheion: rules above and below the title, authors
// with ORCID badges, centred abstract). Override via [transform.typst] template
// in project config or --template.
//
// The book shells opm ships (book.typ.tpl, docbook.typ.tpl) open with a title page
// and a table of contents, which is wrong for a fifteen-page article: a journal
// article starts on page one with its own masthead.

#import "@preview/zebraw:0.6.3": *
#import "@preview/arkheion:0.1.0": arkheion, arkheion-appendices

[% include "opm_css_fns_default.typ.j2" %]

// No `marginalia.setup` here on purpose: it would replace arkheion's page
// geometry with its own. Add it back (see book.typ.tpl) if your ODD emits margin
// notes — JATS has no element that does.

[[ $context?odd_typst ]]

[% include "opm_css.typ.j2" %]

// The title block below is built from ODD-rendered content, so every #tei_* and
// #opm-css definition above has to be in scope before the show rule runs.
#show: zebraw.with(..zebraw-themes.zebra, lang: true, lang-color: color.mix((blue, 15%), (white, 85%)))

[#
  Metadata values arrive Typst-*markup* escaped (`a\@b.c`), which is right
  inside `[…]` content but invalid inside a "…" string literal. $tstr strips
  the escapes where a string is required: arkheion needs author names as
  strings for `set document`.
#]
[% let $tstr = function($value) { replace(replace(string($value), '\', '', 'q'), '"', '\"', 'q') } %]
[% let $journal = string(($context?metadata?journal?*)[1]) %]
[% let $volume = string(($context?metadata?volume?*)[1]) %]
[% let $elocation = string(($context?metadata?elocation?*)[1]) %]
[% let $date = string(($context?metadata?date?*)[1]) %]
[% let $doi = string(($context?metadata?doi?*)[1]) %]
[% let $license = string(($context?metadata?license?*)[1]) %]
#show: arkheion.with(
  title: "[[ $tstr(($context?metadata?title?*, 'Untitled')[1]) ]]",
  authors: (
    [% for $record in $context?metadata?author_records?* %]
    [% let $p = tokenize($record, '\|') %]
    (
      name: "[[ $tstr($p[1]) ]]",
      email: "[[ $tstr($p[2]) ]]",
      affiliation: "[[ $tstr($p[3]) ]]",
      [% if $p[4] %]
      orcid: "[[ $tstr($p[4]) ]]",
      [% endif %]
    ),
    [% endlet %]
    [% endfor %]
  ),
  abstract: [[[ ($context?metadata?abstract?*, '')[1] ]]],
  // arkheion centres `date` under the byline — the natural slot for the line a
  // journal cites itself by.
  date: [[[ string-join((
      if ($journal) then '#emph[' || $journal || ']' else (),
      if ($volume) then ' ' || $volume else (),
      if ($date) then ' (' || $date || ')' else (),
      if ($elocation) then ', article ' || $elocation else (),
      if ($doi) then ' · #link("https://doi.org/' || $tstr($doi) || '")[doi:' || $doi || ']' else ()
    ), '')
  ]]],
)

#show raw: set text(font: ("Iosevka", "DejaVu Sans Mono", "Courier New"))

// A journal article numbers its sections rarely; arkheion turns numbering on.
#set heading(numbering: none)

[[ $context?content_typst ]]

[% if $license %]
#v(2em)
#line(length: 100%, stroke: 0.5pt)
#align(center)[#text(size: 8pt)[#link("[[ $tstr($license) ]]")[[[ $license ]]]]]
[% endif %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
[% endlet %]
