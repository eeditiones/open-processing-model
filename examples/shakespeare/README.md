# Much Adoe about Nothing (First Folio)

A worked `opm` project for a Shakespeare First Folio text, chunked **by page**
rather than by division. `data/F-ado.xml` is the Bodleian First Folio copy of
*Much Ado About Nothing* (Arch. G c.7), with the Folio's own page and column
breaks, catchwords, signatures and running heads left in the markup.

`odd/shakespeare.odd` inherits the packaged `teipublisher` model
(`schemaSpec/@source="teipublisher.odd"`) and overrides what a play needs:
speeches, stage directions, decorated capitals, and `pb`.

From a clone, `uv run` finds the repo project even from this directory. `opm`
then loads this `opm.toml` automatically.

```bash
cd examples/shakespeare
```

## Transform

```bash
uv run opm transform data/F-ado.xml --preview
uv run opm transform data/F-ado.xml -t markdown --preview
uv run opm transform data/F-ado.xml -t typst -o folio.typ
uv run opm transform data/F-ado.xml -t docx -o folio.docx
```

## Chunk and preview

```bash
uv run opm chunk data/F-ado.xml --force --preview
uv run opm serve
```

This writes 21 pages to `chunks/`, one per `<pb/>`. Serve them rather than
opening the files directly: the facsimile viewer fetches its manifest over
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

## Template context

`[context]` carries project values to the Jinja2 templates, untouched by XPath:

```toml
[context]
page_label = "Folio"
```

The chapbook template reads it for the running header and the drop-cap opening,
so the pages read *Folio 12* rather than the template's default *Cap. 12*.
Nothing else needs changing to relabel the edition.

## Facsimiles

Chunk pages carry a IIIF viewer beside the text, the way the TEI Publisher
`view=page` demo does. Three pieces have to line up.

**The link.** Each `<pb/>` carries a `@facs`, and `teipublisher.odd` turns it
into a `<pb-facs-link>` that announces a manifest URL and a page index on the
`transcription` channel. The page index is
`count($get(.)/preceding::pb) + 1` — `$get()` earns its keep here, because the
page being transformed is a detached copy in which `preceding::pb` would find
nothing and every folio would claim to be page 1.

**The viewer.** `templates/chapbook.html.j2` puts a `<pb-tify>` in an aside
column and subscribes it to the same channel, so turning the page moves the
facsimile with it:

```html
<pb-tify subscribe="transcription" emit="transcription"></pb-tify>
```

`pb-tify` is published as its own entry point rather than inside
`pb-components-bundle.js`, so the template loads a second module. Its URL is
`[context] facsimile_viewer` — unset that and both the script and the whole
facsimile column disappear, no template edit needed.

The page also needs a `<pb-page endpoint=".">` around the content. TEI
Publisher components resolve relative URLs against the endpoint of an ancestor
`pb-page`; with none, `getEndpoint()` is `undefined` and the viewer asks for
`/undefined/assets/…` and reports *Error loading IIIF manifest: File not
found*. `endpoint="."` resolves the manifest beside the page. `api-version` is
pinned so `pb-page` does not probe `./api/version`, and `theme` points at the
packaged `components.css` it would otherwise look for next to the page.

**The manifest.** A deployed TEI Publisher answers `api/iiif/<doc>`; nothing
does here. `teipublisher.odd` already has a `<pb>` model for that case, chosen
by `$parameters?static`, which builds the URL from `context-path` instead:

```toml
[transform.parameters]
static = "1"
context-path = "assets"
```

That yields `facs="assets/F-ado.xml/manifest.json"`, and `[chunking] assets`
copies `iiif/F-ado.xml/` to exactly that path in the output. So the viewer works
straight from `opm serve`, with no ODD override anywhere.

`iiif/F-ado.xml/manifest.json` is checked in, built by
`scripts/build_manifest.py` from the 21 `pb/@facs` values:

```bash
uv run python scripts/build_manifest.py
```

The script reads each image's IIIF `info.json` for its true dimensions — the
folios differ, and Tify places deep-zoom tiles from them — and writes to
`iiif/<document-name>/manifest.json`, the path the `<pb>` model above points at.
Re-run it after changing the source document, or if the image server moves.

The images come from the same public server the TEI Publisher demo uses, so they
are fetched over the network: that is the one part of this example that is not
self-contained.

## Layout

- `odd/shakespeare.odd` — processing model (plus `shakespeare.css`)
- `templates/chapbook.html.j2` — reading view (`chapbook.css` is inlined by it)
- `templates/book.typ.j2` — Typst document shell
- `opm.toml` — page chunking, `[context]`, `$global:` settings, chunk fragments
- `iiif/F-ado.xml/manifest.json` — IIIF manifest, copied to `chunks/assets/`
- `scripts/build_manifest.py` — regenerates that manifest from `pb/@facs`
- `data/F-ado.xml` — the Folio text
