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

Chunk roots are almost always inner elements (`div`, `section`, a reconstructed
page), not the document element. The transform therefore emits an HTML
**fragment**, not `<html>…</html>`. In the template (and in JSON as `head`),
`head_html` is empty; ODD styles arrive as `odd_css`. See
[Templates & CSS](templates-and-css.md#document-vs-fragment-output) for how to
write a `<head>` that works for both `opm chunk` and `opm transform`.

```bash
uv run opm chunk demo/tei-test.xml --format json -o _data/chunks
uv run opm chunk demo/tei-test.xml --format pb-view --doc-path my-doc -o public
```

Pass a directory of XML files to chunk every document. HTML and JSON write each
document into its own subdirectory (`<output-dir>/<file>.xml/`); `pb-view`
appends the filename to `--doc-path`.

```bash
uv run opm chunk docs/ -o chunks/ --force
uv run opm chunk docs/ --format json -o _data/chunks
uv run opm chunk docs/ --format pb-view --doc-path letters -o public
```

## Fragments

Alongside the main chunk content, you can extract **fragments** — secondary
pieces pulled from the document or from each chunk, such as a table of contents,
breadcrumbs, or the work title. They are configured under `[chunking]` as an
array of tables and surface in the template as `fragments.<name>`, in each JSON
chunk, and (for `scope = "global"`) in the manifest. With `--format pb-view`,
global fragments become `{name}.json` part files (e.g. `toc.json`) plus a
sibling `{name}.html` with the same markup, and per-chunk fragments become
`{name}-{xml:id}.json`; both JSON parts are registered in `index.json` under
the fragment xpath and any `user.*` parameters so a second `pb-view` can load
them in static mode.

```toml
[[chunking.fragments]]
name = "title"
scope = "global"
xpath = "string((/article/info/title, /book/info/title)[1])"

[[chunking.fragments]]
name = "toc"
scope = "global"
xpath = "(/article, /book)[1]"
parameters = { mode = "toc" }

[[chunking.fragments]]
name = "breadcrumbs"
scope = "per-chunk"
xpath = "."
parameters = { mode = "breadcrumb" }
```

| Key | Meaning |
| --- | --- |
| `name` | Template / JSON key (`fragments.title`, `fragments.breadcrumbs`, …) |
| `scope` | `global` — evaluate once against the document root; `per-chunk` — once per chunk with the chunk as context |
| `xpath` | XPath 3.1 selecting the node(s) or string to emit (default `.`) |
| `parameters` | Extra `$parameters` for that transform (e.g. `mode = "breadcrumb"`) |
| `odd` / `mode` | Optional separate ODD and output channel for this fragment |

A string result (as with `string(…)`) is used as-is. An element is transformed
with the chunking ODD (or the fragment's own `odd`). In a Jinja template:

```jinja
<title>{{ fragments.title | striptags | trim }}</title>
…
{{ fragments.breadcrumbs | safe }}
```

## `$parameters?root`

While a chunk is transformed, `$parameters?root` is the **original node** that
chunk was copied from — the tei-publisher-lib convention documented under
[ODD files](odd-files.md#parametersroot). The document node is
`root($parameters?root)`.

`dbk_section_chunks` and `tei_pb_chunks` sometimes yield a detached copy (a fill
intro, a reconstructed page). The copy has no ancestors, but it keeps the
source `xml:id`, so `opm` maps it back. ODD models that need the rest of the
document should walk from `$parameters?root`, not from `.`:

```xpath
(($parameters?root)/ancestor::article/info/title,
 ($parameters?root)/ancestor::section/title,
 title)
```

`not($parameters?root is ..)` is then true only for ancestor titles, so the
current chunk’s heading stays unlinked in a breadcrumb trail.

`opm transform` (no chunking) binds `$parameters?root` to the document element,
so `root($parameters?root)//…` still reaches the header.

## Manifest and navigation

Chunking writes a manifest JSON describing every chunk: its file, anchors,
fragment locations, and `prev`/`next` navigation links. Cross-chunk links follow
`chunking.link_pattern` (placeholders `{file}`, `{stem}`, `{anchor}`, `{doc}`),
so you can match your site's URL scheme. `{doc}` is the per-document
subdirectory when chunking a directory of XML files (empty otherwise):

```toml
[chunking]
link_pattern = "/{doc}/{file}"
```

## Previewing

Serve a chunked HTML directory locally:

```bash
uv run opm serve -d chunks/
```

## From Python

The CLI wraps [`opm.chunking.chunk_document`](../api/chunking.md); call it
directly to integrate chunking into your own build pipeline.
