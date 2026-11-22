<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# Much Adoe about Nothing (First Folio)

An example `opm` project for a Shakespeare First Folio text, chunked **by page**
rather than by division. `data/F-ado.xml` is the Bodleian First Folio copy of
*Much Ado About Nothing* (Arch. G c.7), with the Folio's own page and column
breaks, catchwords, signatures and running heads left in the markup.

`odd/shakespeare.odd` inherits the packaged `teipublisher` model
(`schemaSpec/@source="teipublisher.odd"`) and overrides what a play needs:
speeches, stage directions, decorated capitals, and `pb`.

<!-- opm:repo-only -->
The commands below call `opm` directly, as an installed copy would. From a clone
it lives in the project venv, so either prefix them with `uv run`, activate the
venv (`source .venv/bin/activate`), or put the working tree on your `PATH` once
with `uv tool install --editable .`. Either way `opm` loads this `opm.toml`
automatically.

```bash
cd examples/shakespeare
```
<!-- /opm:repo-only -->

## Transform

```bash
opm transform data/F-ado.xml --preview
opm transform data/F-ado.xml -t markdown --preview
opm transform data/F-ado.xml -t typst -o folio.pdf
opm transform data/F-ado.xml -t docx -o folio.docx
opm transform data/F-ado.xml -t epub -o folio.epub
```

## Chunk and preview

```bash
opm chunk data/F-ado.xml --force --preview
opm serve
```

This writes 21 pages to `chunks/F-ado.xml/`, one per `<pb/>`, with the
stylesheets, assets and an `index.html` shared at `chunks/`. Serve them rather
than opening the files directly: the facsimile viewer fetches its manifest over
HTTP.

## Page chunking

The other examples split on structure — one file per letter (serafin), one per
section (docbook). This one splits on a **milestone**:

```toml
[chunking]
view = "page"
selector = "opm.navigation.tei_pb_chunks"
```

`tei_pb_chunks` runs from each `<pb/>` up to the next one and rebuilds that span
as a synthetic tree, carrying the enclosing `<div>`, `<sp>` and `<lg>` across
the page boundary. A speech split over a page break therefore stays a speech on
both pages, rather than collapsing into loose text. `view = "page"` matches the
lookup key a `pb-view` sends in that mode.

## Facsimiles

Chunk pages carry a IIIF viewer beside the text, the way the TEI Publisher
`view=page` demo does. Three pieces have to line up.

**The link.** Each `<pb/>` carries a `@facs`, and `teipublisher.odd` turns it
into a `<pb-facs-link>` that announces a manifest URL and a page index on the
`transcription` channel. The page index is
`count($get(.)/preceding::pb) + 1` — `$get()` earns its keep here, because the
page being transformed is a detached copy in which `preceding::pb` would find
nothing and every folio would claim to be page 1.

**The viewer.** The `iiif` profile, switched on in `opm.toml`, puts a
`<pb-tify>` in a column beside the text and subscribes it to the same channel,
so turning the page moves the facsimile with it:

```toml
[project]
profiles = ["iiif"]
```

The profile also loads `pb-tify.js`, which is published separately from the
main web components bundle, and wraps the page in the `<pb-page endpoint=".">`
the components need to find the manifest. Without that wrapper the viewer asks
for `/undefined/assets/…` and reports *Error loading IIIF manifest: File not
found*. The column only appears in web component mode, so `--no-webcomponents`
leaves the page as plain text. `templates/facsimile.css` fits the column into
the chapbook layout.

**The manifest.** A deployed TEI Publisher answers `api/iiif/<doc>`; nothing
does here. `teipublisher.odd` already has a `<pb>` model for that case, chosen
by `$parameters?static`, which builds the URL from `context-path` instead:

```toml
[transform.parameters]
static = "1"
context-path = "{prefix}assets"
```

That yields `facs="../assets/F-ado.xml/manifest.json"`: the pages sit in a
per-document subdirectory while `[chunking] assets` copies every
`iiif/<document>.xml/` to the output root, and `{prefix}` supplies the hop
between them. So the viewer works straight from `opm serve`, with no ODD
override anywhere.

`iiif/F-ado.xml/manifest.json` is checked in, built by
`scripts/build_manifest.py` from the 21 `pb/@facs` values:

```bash
python scripts/build_manifest.py
```

The script reads each image's IIIF `info.json` for its true dimensions — the
folios differ, and Tify places deep-zoom tiles from them — and writes to
`iiif/<document-name>/manifest.json` in the project. `[chunking] assets` is what
puts it where the `<pb>` model looks, under `assets/` in the output. With no
argument the script covers every document in `data/`; name one to rebuild just
that. Re-run it after changing a source document, or if the image server moves.

The images come from the same public server the TEI Publisher demo uses, so they
are fetched over the network: that is the one part of this example that is not
self-contained.

## Print edition

`opm transform -t typst` produces a reading text laid out after the Folger
Shakespeare: through-line numbers in the left margin, small-caps speech
prefixes, centred act and scene headings, and a running head carrying the act
and scene.

```bash
opm transform data/F-ado.xml -t typst -o folio.typ && typst compile folio.typ
```

The line numbers are Typst's own `par.line`, which numbers *typeset* lines — so
a wrapped turn-under stays unnumbered, the convention the Folger follows.
`templates/book.typ.tpl` is hand-written rather than built on a package: the
Typst drama templates on Universe format *new* stageplays to Dramatists Guild
or screenplay rules, which is a different genre from a numbered scholarly text.

Everything the print layout needs is either in `odd/shakespeare.odd`, scoped
with `output="typst"` so the web models are untouched, or in the template:

- **Act and scene headings.** Only the supplied heads (`[Act 1, Scene 2]`)
  state both numbers, so they drive the headings; the first scene of an act
  also opens the act. The Folio's own heading (*Actus primus, Scena prima.*) is
  pulled in underneath, since where it stands it would print before the act.
- **Speech prefixes.** Small caps in print, italic on the web. The Folio marks
  them `@rend="italic"`, which arrives in Typst as emphasis, so the template
  unwinds it before applying small caps.
- **Stage directions.** `text-align` has no equivalent in the Typst generator,
  so the alignment travels as a `@cssClass` the template resolves. Note that
  `@cssClass` names arrive with hyphens folded to underscores.
- **`[transform.typst.context]`.** The Folio title runs to two sentences and is
  unusable as a running head, so print gets `short_title`; the web templates go
  on using the full one. `line_number_every` sets the numbering interval.

## EPUB edition

`opm transform -t epub` produces a reading text of the play: one chapter per
scene, speeches hanging under small-caps prefixes, verse a line to a line.

```bash
opm transform data/F-ado.xml -t epub -o folio.epub
```

## Layout

- `odd/shakespeare.odd` — processing model (plus `shakespeare.css`)
- `templates/chapbook.html.tpl` — reading view, extending opm's page layout (`opm/layout.html.tpl`); its stylesheet `templates/opm-theme-chapbook.css` is listed under `assets`
- `templates/facsimile.css` — fits the `iiif` profile's viewer column into the chapbook layout
- `templates/book.typ.tpl` — Folger-style print edition (line numbers, running heads)
- `templates/epub.css` — EPUB reading text (scene chapters, no page furniture)
- `opm.toml` — page chunking, `[context]`, `$global:` settings, chunk fragments
- `iiif/<document>.xml/manifest.json` — IIIF manifests, copied to `chunks/assets/`
- `scripts/build_manifest.py` — regenerates that manifest from `pb/@facs`
- `data/F-ado.xml` — the Folio text

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
