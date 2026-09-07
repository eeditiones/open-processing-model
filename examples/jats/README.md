<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# JATS journal article

A worked `opm` project for a JATS (Journal Article Tag Suite) article, the
vocabulary scholarly journals publish in. The source is Elisa Bastianello,
“Digital Editions at Bibliotheca Hertziana”, *Journal of Art Historiography*
27 (2022), [10.48352/uobxjah.00004200](https://doi.org/10.48352/uobxjah.00004200),
CC BY-NC 4.0 — a real article with front matter, twenty footnotes and a
reference list.

It shows what a journal article needs beyond the packaged `jats.odd`:
front-matter apparatus (affiliations, ORCID, DOI, licence), a static table of
contents, and a chunked reading surface.

<!-- opm:repo-only -->
The commands below call `opm` directly, as an installed copy would. From a clone
it lives in the project venv, so either prefix them with `uv run`, activate the
venv (`source .venv/bin/activate`), or put the working tree on your `PATH` once
with `uv tool install --editable .`. Either way `opm` loads this `opm.toml`
automatically.

```bash
cd examples/jats
```
<!-- /opm:repo-only -->

## Transform

```bash
opm transform data/article/hertziana-digital-editions.xml --preview
opm transform data/article/hertziana-digital-editions.xml -t print --preview
opm transform data/article/hertziana-digital-editions.xml -t typst -o /tmp/article.typ
opm transform data/article/hertziana-digital-editions.xml -t epub -o /tmp/article.epub
```

EPUB needs no configuration here: `jats_sec_chunks` supplies the chapters, so
front matter, body and references become three EPUB sections plus a nav TOC.

Typst goes through [`arkheion`](https://typst.app/universe/package/arkheion), an
arXiv-preprint layout: rules above and below the title, authors with ORCID
badges, a centred abstract, and the body starting on page one. The book shells
opm ships (`book.typ.j2`, `docbook.typ.j2`) open with a title page and a table of
contents — right for a monograph, wrong for a fifteen-page article.

## Print

`-t print` reads the same article, but the packaged print shell is a bare
`<body>` — no typography at all. `[transform.print]` points it at
`templates/print.html.j2`, which includes `journal.css` before its own
`print.css`: the paged view keeps the reading view's tokens, title block,
byline, abstract and reference list, and only drops what the web shell added
(sticky masthead, TOC rail, web components).

Footnotes are the one place the two views necessarily differ.
`PrintOutputFunctions` leaves a note inline where its marker stands, so a
paged-media engine can `float: footnote` it (`odd/jats.css` does, under
`@media print`). No browser implements that float, so `print.css` numbers the
notes with CSS counters on screen and floats them into a margin column beside
the text — bracketed inline below 60rem, where there is no margin to float
into. Printing from the browser falls back to inline notes; run Prince or
Paged.js over the same file for footnotes set at the foot of the page.

## Chunk and preview

`opm.navigation.jats_sec_chunks` splits at `sec`, and — unlike the TEI and
DocBook selectors — keeps `front` and `back` as chunks of their own. A journal
article holds its apparatus outside `body`, so without that the title, authors,
abstract and reference list would simply be dropped.

```bash
opm chunk data/article/hertziana-digital-editions.xml --force --preview
```

Three pages: front matter, `Content`, references.

Cross-chunk links survive the split: `<xref ref-type="bibr">` in a footnote on
page two comes out as `003.html#eb_Q5LGNTJI`, because `opm chunk` resolves every
`#id` (and every `pb-link`) against the chunk that owns the target.

## What this project adds to the packaged ODD

`odd/jats.odd` is `opm init --vocabulary jats`’s copy of the packaged model with
three groups of changes. Each is marked with a `<desc>` in the file.

- **TOC entries for front and back.** The packaged ODD builds the static TOC
  from `body/sec`, because that is what eXist-side JATS navigation chunks.
  `opm.navigation.jats_sec_chunks` also makes `front` and `back` chunks of their
  own, so here the root list is widened to `front | body/sec | back[node()]` and
  both get an entry. Neither carries an `@id`, so they anchor on the first
  descendant that has one. The `pb-link` these emit is rewritten by `opm chunk`
  into a plain anchor pointing at the owning chunk file.
- **Front-matter apparatus.** The packaged `article-meta` sequence stops after
  title, byline and abstract. Here it also renders `aff`, a citation line
  (volume, article number, DOI) and `permissions`, and the byline keeps the
  ORCID and e-mail hanging off each `contrib`.
- **A front-matter block for paged media.** `jats.css` puts `.frontmatter` on
  its own `@page Title`, but nothing carried that class: `front` is
  pass-through. An `output="opm-print"` model wraps it in a block, so the title
  page rule applies without changing the web or EPUB markup.

Three things this example needed first have since moved upstream, so a fresh
`opm init --vocabulary jats` gets them for free. The static TOC models
themselves, now in jinks' JATS profile and mirrored into the packaged
`jats.odd`, matching what the DocBook profile has had. The
publication date: upstream calls XSLT’s `format-date()`, which the XPath 3.1
engine does not provide, so every date rendered empty; it now calls
`tp:format_date()` from `opm.runtime.common_xpath_functions`, which `opm init`
lists under `[transform] xpath_extensions`. And the Typst title-block metadata —
`journal`, `volume`, `elocation`, `date`, `doi`, `license`, plus one
`author_records` entry per contributor holding name, e-mail, affiliation and
ORCID pipe-joined, which `templates/article.typ.j2` splits into arkheion’s
author dict. `authors` stays a plain name so the book shells keep working.

## Layout

- `odd/jats.odd` — JATS processing model (plus `jats.css`)
- `templates/journal.html.j2` + `journal.css` — journal reading surface:
  sticky masthead, sticky TOC rail, one measure, footnote apparatus. Both are
  byte-identical to what `opm init --vocabulary jats` now writes, which wires
  this shell as the project's `[document] template`; the masthead and rail
  appear here because this project declares the `journal` and `toc` fragments
- `templates/print.html.j2` + `print.css` — paged shell for `-t print`: the
  same article surface, margin notes instead of a masthead and rail
- `templates/article.typ.j2` — arkheion journal shell for `-t typst`
- `opm.toml` — `jats_sec_chunks`, title/journal/toc fragments
- `data/article/` — the source article

## Licence

The project furniture here — stylesheets, templates, `opm.toml`, extension and helper
scripts — is released by e-editiones under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); `opm init --example` copies
it into your own project with no strings attached.

The ODD under `odd/` is the exception: it comes from TEI Publisher and is
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), copyright 2017–2026
e-editiones and individual contributors, building on TEI Consortium material that is itself
CC BY 3.0 / BSD-2-Clause, as its own `teiHeader` states. Reuse it as you like; CC BY asks
only that you keep that statement in the file and credit those it names.

The documents under `data/` are not covered by that dedication. They are source texts with
their own provenance and rights, noted above.
