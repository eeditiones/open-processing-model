# Chunking

Large documents are awkward to serve as one giant HTML page. `opm chunk` splits a
document into smaller pieces, transforms each one, and writes the results plus a
manifest — ideal for static site generators and web components.

```bash
uv run opm chunk examples/tei-test.xml -o chunks/ --force
uv run opm chunk examples/tei-test.xml --depth 1 --force   # override chunking.depth
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
| `opm.navigation.jats_sec_chunks` | JATS by `sec`, with `front` and `back` as their own chunks |

```toml
[chunking]
selector = "opm.navigation.tei_pb_chunks"
view = "page"
```

`examples/shakespeare` is a worked page-chunked project: a First Folio play
split at every `<pb/>`, where speeches spanning a page break stay intact on
both pages. `examples/jats` is the JATS counterpart: a real journal article
where `front` and `back` become chunks alongside the body sections.

## Output formats

`--format` chooses what is written per chunk:

- **`html`** (default) — each chunk rendered through a Jinja2 template
  (`chunking.template`), as standalone pages.
- **`json`** — one JSON file per chunk with `content`, `head`, `odd_css`, and
  `fragments` keys. Convenient for Eleventy, Hugo, and other static site
  generators that consume data files.
- **`pb-view`** — an index table plus part files for the tei-publisher
  `pb-view` web component. Use `--doc-path` to place parts under a document
  subdirectory. See [Integration with TEI Publisher](tei-publisher.md) for
  uploading those files into an app and switching `pb-view` to static mode.

Chunk roots are almost always inner elements (`div`, `section`, a reconstructed
page), not the document element. The transform therefore emits an HTML
**fragment**, not `<html>…</html>`. In the template (and in JSON as `head`),
`head_html` is empty; ODD styles arrive as `odd_css`. See
[Templates & CSS](templates-and-css.md#document-vs-fragment-output) for how to
write a `<head>` that works for both `opm chunk` and `opm transform`.

```bash
uv run opm chunk examples/tei-test.xml --format json -o _data/chunks
uv run opm chunk examples/tei-test.xml --format pb-view --doc-path my-doc -o public
```

Pass a directory of XML files to chunk every document. HTML and JSON write each
document into its own subdirectory (`<output-dir>/<file>.xml/`); `pb-view`
appends the filename to `--doc-path`.

```bash
uv run opm chunk examples/serafin/data/letters -c examples/serafin/opm.toml \
  -o chunks/ --force
uv run opm chunk examples/serafin/data/letters -c examples/serafin/opm.toml \
  --format json -o _data/chunks
uv run opm chunk examples/serafin/data/letters -c examples/serafin/opm.toml \
  --format pb-view --doc-path letters -o public
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
xpath = "(/article/info/title, /book/info/title)[1]"
parameters = { mode = "title" }

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
| `parameters` | Extra `$parameters` for that transform (e.g. `mode = "breadcrumb"`). DocBook `mode = "toc"` uses OPM's `opm-web` models (`details`/`pb-link`, matching `dapi:toc-div`) so a jinks `pb-load` of `toc.html` works with `toc.js`. Optional `target` overrides the pb-link emit channel (default `transcription`); `collapse = true` starts nested entries closed. |
| `odd` / `mode` | Rare. Use a different ODD for this fragment only (`odd`), compiled for output channel `mode` (`web` by default — not the same as `$parameters?mode` above). Omit to reuse the chunking ODD. |

A string result (as with a bare `string(…)` xpath) is used as-is — fine inside a
Jinja template, but not valid as a standalone `.html` file. Prefer selecting an
element and transforming it (e.g. `parameters = { mode = "title" }`) when the
fragment is also written to disk. In a Jinja template:

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

## Stylesheets and static assets

Chunking always writes the stylesheets as files under `<output-root>/css/` and
hands templates `odd_css_url`. Chunk output is several pages
sharing one stylesheet, so embedding the same bytes in each page only makes the
output bigger and uncacheable. (`--format pb-view` has always written
`css/<odd>.css`; HTML output now matches it.)

`css/<odd>.css` holds the ODD's own `<rendition>` rules, preceded by the base
rules every ODD-rendered document needs — the `.alternate` / `.altcontent`
popover behind `choice`, `.tei-cb` column breaks, margin notes. Those describe
markup the runtime emits rather than anything a project chose, so they travel
with the ODD stylesheet wherever it goes, `--format pb-view` included, and an
ODD's `outputRendition` can still override them.

`[document] css` does not add a second stylesheet — it *replaces* those base
rules, so a project can restyle what the runtime emits without losing the ODD's
own renditions. Because it changes the compiled stylesheet it is part of the ODD
cache key, so a project overriding it gets its own compiled module.

```jinja
<link rel="stylesheet" href="{{ odd_css_url }}">
```

The `odd_css` string is still passed, so a template that inlines it keeps
working, and the URL is empty when the stylesheet turns out to be empty — hence
the defensive form used by the packaged template:

```jinja
{% if odd_css_url %}<link rel="stylesheet" href="{{ odd_css_url }}">
{% elif odd_css %}<style>{{ odd_css }}</style>{% endif %}
```

Anything else a page needs — the template's own stylesheet, an image, a font —
is listed under `assets`, because the output directory is wiped on every
rebuild and nothing else puts files there:

```toml
[chunking]
assets = ["templates/letter.css", "templates/parchment.jpg", "templates/fonts"]
```

Each entry is copied into `<output-root>/assets/`. Templates receive an
`assets` URL prefix for referencing them by hand, and `asset_styles` — the
stylesheets among them, as URLs, in the order declared — so a template links
them without naming any file:

```jinja
{% for href in asset_styles %}<link rel="stylesheet" href="{{ href }}">{% endfor %}
```

Declaration order is cascade order. Only entries you list explicitly with a
`.css` suffix are linked; a directory copied as an asset is not scanned, so
adding `fonts/` does not start injecting stylesheets from inside it.

A stylesheet in `assets/` references a sibling by plain filename
(`url("parchment.jpg")`), since CSS URLs resolve against the stylesheet's own
location rather than the page's — so one texture file serves the whole edition
instead of a base64 copy per page. That is why project design CSS belongs here
rather than in `[document] css`: only assets can carry the files it depends on.

All these URLs are relative to the page that uses them: bare from the index at
the output root, `../`-prefixed from a chunk page in a per-document
subdirectory.

`examples/serafin` does exactly this. Its pages dropped from 168 KB to 96 KB
and its index from 91 KB to 19 KB, with 42 KB of shared CSS and imagery fetched
once and cached.

## Collection index

Chunking a *directory* writes one subdirectory per document, plus an
`index.html` at the output root listing them all. `http.server` serves
`index.html` in preference to a directory listing, so `opm serve` shows a real
landing page with no further configuration.

Each entry links to its document's first chunk. What the entry *shows* comes
from the document's global fragments, so the index is built the same way TEI
Publisher builds `browse.html` — through the ODD. Declare a fragment using the
`display='browse'` models the stock ODDs already provide:

```toml
[[chunking.fragments]]
name = "browse"
scope = "global"
xpath = "(/article/info, /book/info)[1]"   # TEI: "//teiHeader"
parameters = { display = "browse" }
```

Those models emit the whole browse record — heading, author, description — and
build their own link from `$parameters?doc`. That parameter is supplied
automatically, per document, so no further wiring is needed. To use a different
URL scheme, set it explicitly; `{doc}`, `{file}` and `{stem}` expand exactly as
in `link_pattern`:

```toml
parameters = { display = "browse", doc = "/exist/apps/edition/{doc}/{stem}" }
```

The index degrades gracefully when a project has no such models: it falls back
to a `title` fragment if one is declared, and to a readable form of the filename
otherwise. Every entry stays clickable in all three cases.

Override the page itself with `chunking.index_template`. The template receives
`documents` — each with `name`, `stem`, `label`, `href`, `chunks` and
`fragments` — plus `title`:

```jinja
{% for doc in documents %}
  <article>
    {{ doc.fragments.browse or doc.fragments.title or doc.label }}
    <a href="{{ doc.href }}">{{ doc.chunks }} sections</a>
  </article>
{% endfor %}
```

Because `fragments` is passed whole, adding an author or date column needs no
code — just another global fragment in `opm.toml` and a reference to it here.

The template also receives `odd_css`, resolved exactly as for chunk pages, so a browse record's `tei-*` classes are styled the same way on the
index as inside the edition. Since Jinja loads includes from the template's own
directory, an index template sitting beside the chunk template can pull in the
same stylesheets and share its page shell:

```jinja
<style>{% include "letter.css" %}</style>
{% if odd_css %}<style>{{ odd_css }}</style>{% endif %}
...
<body class="letter">
  <nav class="app-menubar">…</nav>
```

`examples/serafin/templates/index.html.j2` does this: it includes the same
`letter.css` as the chunk template and reuses its menubar, toolbar and page
shell, so the landing page cannot drift from the letters it links to. The
list's own rules live in that stylesheet too, under `.letter-list`, rather than
in a `<style>` block on the index — one place to change the design.

## Previewing

Chunk and preview in one step. `--preview` serves the output directory and
opens the first page in a browser — `index.html` for a directory run, `001.html`
for a single document, which writes no index. Only HTML output is opened;
`--format json` / `pb-view` is served for another tool to fetch.

```bash
uv run opm chunk examples/tei-test.xml -o chunks/ --force --preview
```

Or serve an existing chunk directory:

```bash
uv run opm serve -d chunks/
```

## From Python

The CLI wraps [`opm.chunking.chunk_document`](../api/chunking.md); call it
directly to integrate chunking into your own build pipeline.
