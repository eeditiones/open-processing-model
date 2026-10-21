<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# Monograph

An example `opm` project for a critical edition of a book: the first chapter of
Karl Barth's *Der Römerbrief* (1922) from the
[Digitale Karl Barth-Gesamtausgabe](https://kbga.karl-barth.ch/texts/47009).

It shows the features a scholarly reading text typically needs: original page
numbers in the margin, two series of notes, lemma ranges, and a breadcrumb
trail through chapters and sections.

`odd/monograph.odd` inherits the packaged `teipublisher` model
(`schemaSpec/@source="teipublisher.odd"`) and overrides a few elements.

<!-- opm:repo-only -->
The commands below call `opm` directly, as an installed copy would. From a clone
it lives in the project venv, so either prefix them with `uv run`, activate the
venv (`source .venv/bin/activate`), or put the working tree on your `PATH` once
with `uv tool install --editable .`. Either way `opm` loads this `opm.toml`
automatically.

```bash
cd examples/monograph
```
<!-- /opm:repo-only -->

## Chunk and preview

```bash
opm chunk data/47009.xml --force --preview
```

`[chunking]` splits at `depth = 2`. The chapter opening (title, heading, and
first section) sits in the chapter `div` before its first child `div`, so it
becomes a page of its own ahead of the sections that follow.

## Print

```bash
opm transform data/47009.xml -t print -o print.html
prince print.html -o print.pdf
```

`templates/print.html.j2` and `templates/print.css` set the text as a book
page in the design of the Typst output: A5, running head and folio, the
original page numbers in the right margin, footnotes at the foot of the page.
Unlike Typst, CSS cannot move the apparatus behind the commentary, so each
page lists its notes in the order of their callouts.

## What the ODD adds

- **Original pagination.** `<pb ed="pga">` marks a page of the printed
  Gesamtausgabe. A `|` appears where the page turns (inside the word when
  `@break="no"`; omitted for `@rend="noPipe"`). The page number from `@xml:id`
  (`p047` → „S. 47“) sits in the right margin. Breaks of other editions
  (`@ed="A"`) are omitted.
- **Two note series.** Lettered notes (`@type="textcritical"`) are the
  text-critical apparatus; numbered ones are the commentary.
  `[transform] footnote_order` in `opm.toml` is set to
  `labelled_first`, so each page lists the lettered notes first. Notes with
  their own `@n` get `data-n`, which `monograph.css` uses to style the
  apparatus. See the [Footnotes](../../docs/guide/footnotes.md) guide.
- **Lemma ranges.** A text-critical note sits at the end of the passage it
  comments on; `<anchor type="note"/>` marks where that passage begins. The
  start shows as `a-`, the end as `-a`, and the footnote is labelled `a-a`.
- **Headings.** `<head type="sub">` (the Bible passage under a section title)
  is set smaller and closer to the heading above.
- **Breadcrumbs.** Each page shows the work, chapter, and current section.
  The `div` and `head` models answer `mode='breadcrumb'` with those titles as
  plain text.
- **Contents.** The `toc` fragment lists the chapters, and under the
  current chapter its sections with their Bible passages. Each entry links to
  the `xml:id` of its `div`, which opm resolves to the page holding it.
- **Highlights.** `<hi rend="bold">` — Barth's translation of the letter — is
  set in a light semibold.

## Project layout

| Path | Role |
| --- | --- |
| `odd/monograph.odd` | Processing model |
| `templates/monograph.html.j2` | Page shell (text-size buttons in the menu bar, contents, page turns) |
| `templates/chapbook.css` | Edition design: paper, type, layout (`--opm-*` aliases) |
| `templates/monograph.css` | TEI-specific styles: headings, notes, page breaks |
| `templates/book.typ.j2` | Typst/PDF output in the same design |
| `templates/print.html.j2`, `templates/print.css` | Print (paged media) output in the same design |
| `templates/epub.css` | EPUB output in the same design |
| `templates/default.docx` | DOCX output |
| `opm.toml` | ODD, assets, chunking and fragments |
| `data/47009.xml` | Sample TEI |

## Licence

The stylesheets, templates and `opm.toml` are released by e-editiones under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); `opm init --example`
copies them into your own project with no strings attached.

The ODD under `odd/` inherits from TEI Publisher's `teipublisher.odd`, which is
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), copyright 2017–2026
e-editiones and individual contributors, as its own `teiHeader` states.

`data/47009.xml` is not covered by that dedication. It comes from the Digitale
Karl Barth-Gesamtausgabe, published by the Karl Barth-Archiv, Basel, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); see its
`teiHeader` for the full citation.
