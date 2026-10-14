<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# Monograph

An example `opm` project for the critical edition of a book: the first chapter
of Karl Barth's *Der Römerbrief* (1922) from the
[Digitale Karl Barth-Gesamtausgabe](https://kbga.karl-barth.ch/texts/47009).
It shows the furniture a scholarly reading text needs: the pagination of the
printed edition in the margin, two series of notes, and a breadcrumb trail
through chapters and sections.

`odd/monograph.odd` inherits the packaged `teipublisher` model
(`schemaSpec/@source="teipublisher.odd"`) and overrides a handful of elements.

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

`[chunking]` splits the chapter at `depth = 2`. The opening of the chapter (its
title, the chapter heading and the first section) sits in the chapter `div`
before its first child `div`, and becomes a page of its own ahead of the
sections that follow.

## What the ODD adds

- **Original pagination.** `<pb ed="pga">` marks a page of the printed
  Gesamtausgabe. The text shows a `|` exactly where the page turns, inside the
  word when `@break="no"`, and none for `@rend="noPipe"`. The page number,
  taken from `@xml:id` (`p047` → „S. 47“), sits in the right margin on the
  baseline of that line. Breaks of other editions (`@ed="A"`) are omitted.
- **Two note series.** Lettered notes (`@type="textcritical"`) are the
  text-critical apparatus, numbered ones the commentary. The template's script
  lists the lettered notes first, as the printed edition does.
- **Headings.** `<head type="sub">`, the Bible passage under a section title,
  is set smaller and close to the heading above it.
- **Breadcrumbs.** Each page shows the work, the chapter and the current
  section. The `div` and `head` models answer `mode='breadcrumb'` with just
  those titles, as plain text.
- **Highlights.** `<hi rend="bold">` — Barth's translation of the letter — is
  set in a light semibold.

## Layout

- `odd/monograph.odd` — processing model
- `templates/chapbook.html.j2` — page shell (running head, contents, page turns)
- `templates/chapbook.css` — the edition's design: paper, type, layout
- `templates/monograph.css` — the TEI-specific parts: headings, notes, page breaks
- `templates/book.typ.j2`, `templates/default.docx` — Typst and DOCX output
- `opm.toml` — ODD, assets, chunking and fragments
- `data/47009.xml` — sample TEI

## Licence

The project furniture here — stylesheets, templates and `opm.toml` — is released
by e-editiones under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); `opm init --example` copies
it into your own project with no strings attached.

The ODD under `odd/` inherits from TEI Publisher's `teipublisher.odd`, which is
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), copyright 2017–2026
e-editiones and individual contributors, as its own `teiHeader` states.

`data/47009.xml` is not covered by that dedication. It comes from the Digitale Karl
Barth-Gesamtausgabe, published by the Karl Barth-Archiv, Basel, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); see its `teiHeader`
for the full citation.
