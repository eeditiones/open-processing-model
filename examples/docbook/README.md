# DocBook documentation

A worked `opm` project for handbook-style DocBook, matching the TEI Publisher
documentation setup: section chunking, global TOC, title and browse fragments,
and per-chunk breadcrumbs. This is the config
[Integration with TEI Publisher](../../docs/guide/tei-publisher.md) refers to.

Two articles ship here (Gentle Introduction and Installing). The rest of the
corpus lives in the Jinks docs profile (`../jinks/profiles/docs/data/doc`).
Screenshots referenced from those files are not included.

From a clone, `uv run` finds the repo project even from this directory.
`opm` then loads this `opm.toml` automatically.

```bash
cd examples/docbook
```

## Transform

```bash
uv run opm transform data/doc/quickstart.xml --preview
uv run opm transform data/doc/quickstart.xml -t print --preview
uv run opm transform data/doc/quickstart.xml -t typst -o /tmp/quickstart.typ
```

`-t print` uses `templates/print.html.j2` (no handbook chrome / web components).
The ODD’s `docbook.css` supplies `@page` and `float: footnote` rules for Prince
or the browser print dialog.
## Chunk and preview

Sections are split at depth 2 (same as the `<?teipublisher … depth="2"?>`
processing instruction). The handbook shell fills title, TOC, and breadcrumbs:

```bash
uv run opm chunk data/doc/quickstart.xml --force --preview
```

Or chunk both sample articles (writes `chunks/<file>/`):

```bash
uv run opm chunk data/doc --force --preview
```

## Layout

- `odd/docbook.odd` — DocBook processing model (plus `docbook.css`)
- `templates/handbook.html.j2` — documentation shell with sidebar TOC
- `templates/print.html.j2` — paged-media shell for `-t print`
- `opm.toml` — `dbk_section_chunks`, depth 2, title/toc/breadcrumb fragments
- `data/doc/` — sample DocBook articles