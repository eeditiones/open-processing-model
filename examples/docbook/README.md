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
uv run opm transform data/doc/quickstart.xml -t typst -o /tmp/quickstart.typ
```

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

For TEI Publisher's `pb-view` cache layout, add `--format pb-view` and see
[Integration with TEI Publisher](../../docs/guide/tei-publisher.md).

## Layout

- `odd/docbook.odd` — DocBook processing model (plus `docbook.css`)
- `templates/handbook.html.j2` — documentation shell with sidebar TOC
- `opm.toml` — `dbk_section_chunks`, depth 2, title/toc/breadcrumb fragments
- `data/doc/` — sample DocBook articles
