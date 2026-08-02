# Chunking

Large documents are awkward to serve as one giant HTML page. `opm chunk` splits a
document into smaller pieces, transforms each one, and writes the results plus a
manifest — ideal for static site generators and web components.

```bash
uv run opm chunk demo/tei-test.xml -o chunks/ --force
```

Most settings come from the `[chunking]` section of `opm.toml`; CLI options
override them. See [Configuration](configuration.md) for the full schema.

## Selecting chunks

Chunk roots are selected by an XPath expression (default `//text/body/div`):

```toml
[chunking]
xpath = "//text/body/div"
depth = 2          # maximum heading depth at which to split
```

For logic that XPath can't express, point `selector` at a Python callable
(dotted path) that returns the chunk elements. Built-ins:

| Selector | Use |
| --- | --- |
| `opm.navigation.tei_div_chunks` | TEI by-division (`depth`) |
| `opm.navigation.tei_pb_chunks` | TEI by page-break (`tei:pb` milestones, `view="page"`) |
| `opm.navigation.dbk_section_chunks` | DocBook by `section` |

```toml
[chunking]
selector = "opm.navigation.tei_pb_chunks"
view = "page"
```

## Output formats

`--format` chooses what is written per chunk:

- **`html`** (default) — each chunk rendered through a Jinja2 template
  (`chunking.template`), as standalone pages.
- **`json`** — one JSON file per chunk with `content`, `head`, `odd_css`, and
  `fragments` keys. Convenient for Eleventy, Hugo, and other static site
  generators that consume data files.
- **`pb-view`** — an index table plus part files for the tei-publisher
  `pb-view` web component. Use `--doc-path` to place parts under a document
  subdirectory.

```bash
uv run opm chunk demo/tei-test.xml --format json -o _data/chunks
uv run opm chunk demo/tei-test.xml --format pb-view --doc-path my-doc -o public
```

## Fragments

Alongside the main chunk content, you can extract **fragments** — secondary
pieces pulled from each chunk, such as a table of contents or index entries.
Fragments are configured under `[chunking]` and surface in the manifest and JSON
output so a frontend can place them independently of the main body.

## Manifest and navigation

Chunking writes a manifest JSON describing every chunk: its file, anchors,
fragment locations, and `prev`/`next` navigation links. Cross-chunk links follow
`chunking.link_pattern` (placeholders `{file}`, `{stem}`, `{anchor}`), so you can
match your site's URL scheme:

```toml
[chunking]
link_pattern = "/{stem}/"
```

## Previewing

Serve a chunked HTML directory locally:

```bash
uv run opm serve -d chunks/
```

## From Python

The CLI wraps [`opm.chunking.chunk_document`](../api/chunking.md); call it
directly to integrate chunking into your own build pipeline.
