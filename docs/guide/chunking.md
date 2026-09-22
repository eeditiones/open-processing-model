# Chunking

Large documents are awkward to serve as one giant HTML page. `opm chunk` splits a
document into smaller pieces, transforms each one, and writes the results plus a
manifest — this is ideal for static site generators and web components.

Three different types of output are supported (use `--format` to switch between them):

- **`html`** (default) — renders each chunk through a template
  (`chunking.template`), generating a series of HTML files. Use this for quick previews
  or to create a simple static edition which does not need a complex framework.
- **`json`** — one JSON file per chunk, including the rendered content and optional fragments. Ideal for integration into 
static site generators like [Eleventy](https://www.11ty.dev/), [Hugo](https://gohugo.io/), [Astro](https://astro.build/) and others 
that consume data files.
- **`pb-view`** — an index table plus part files to be consumed by TEI Publisher's
  viewer web component. Use this to pre-render content for fast display in an existing
  TEI Publisher-based website (see [Integration with TEI Publisher](tei-publisher.md)) for
  uploading those files into an app, and switching the webcomponent to static mode.

Example using the Shakespeare sample:

```bash
opm init --example shakespeare shakespeare-demo
cd shakespeare-demo

opm chunk data/F-ado.xml --force --preview    # chunk and preview in browser
opm chunk data/F-ado.xml -o pages/ --force    # override chunking.output_dir
# provide pre-rendered data to a TEI Publisher instance
# requests will call demo/F-ado.xml, so we need to specify this path prefix
opm chunk data --doc-path demo --format pb-view --force
```

Serafin example:

```bash
opm init --example serafin serafin-demo
cd serafin-demo

opm chunk data/letters -o chunks/ --force
opm chunk data/letters --format json -o output/chunks
opm chunk data/letters --format pb-view --doc-path letters -o public
```

Most settings come from the `[chunking]` section of `opm.toml`; which can be overridden by the CLI commands. See [Configuration](configuration.md) for the full schema.

## Selecting chunks

Chunk roots are selected by an XPath expression (default `//text/body/div`), configured as:

```toml
[chunking]
xpath = "//text/body/div"
depth = 2          # maximum heading depth at which to split
# file_pattern = "{xml_id}.html"   # stable names instead of 001.html
```

For logic that XPath can't express, you can use a `selector` (dotted path) to call Python objects
 that return the chunk elements. Built-in selectors:

| Selector | Use |
| --- | --- |
| `opm.navigation.tei_div_chunks` | TEI by-division (`depth`) |
| `opm.navigation.tei_pb_chunks` | TEI by page-break (`tei:pb` milestones, `view="page"`) |
| `opm.navigation.dbk_section_chunks` | DocBook by `section` |
| `opm.navigation.jats_sec_chunks` | JATS by `sec`, with `front` and `back` as their own chunks |

Configuration sample:

```toml
[chunking]
selector = "opm.navigation.tei_pb_chunks"
view = "page"
```

The bundled `shakespeare` example (`opm init --example shakespeare`) is a
page-chunked project (`opm chunk data/F-ado.xml --force`): a First Folio play split at every `<pb/>`. The `jats` example is
a counterpart in which chunks are done by semantic divisions instead of pages: a real journal article where `front` and `back` become chunks
alongside the body sections.

## Fragments

Alongside the main chunk content, you can extract **fragments** — secondary
pieces pulled from the document or from each chunk, such as a table of contents,
breadcrumbs, or the work title. Each one of them is configured under `[chunking.fragments]` and there are two different scopes: `global` (document root as context) and `per-chunk` (chunk as context). They are listed in the manifest, and you can retrieve them in the templates with `fragments.<name>`.

 With the flag `--format pb-view`,
global fragments become `{name}.json` part files (e.g. `toc.json`) plus a
sibling `{name}.html` with the same markup, and per-chunk fragments become
`{name}-{xml:id}.json`. All JSON parts are registered in `index.json` under
the fragment XPath and any `user.*` parameters so a second `pb-view` can load
them in static mode. Thus a fragment who is configured as:

```toml
[[chunking.fragments]]
name = "title"
scope = "global"
xpath = "(//teiHeader/fileDesc/titleStmt/title)[1]"
parameters = { mode = "title" }
```

... will be listed in the index as:

```json
"odd=shakespeare.odd&user.mode=title&view=page&xpath=(//teiHeader/fileDesc/titleStmt/title)[1]": "title.json"
```


More configuration examples:

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
| `xpath` | XPath expression (XPath 3.1) selecting the node(s) or string to emit (default `.`) |
| `parameters` | Extra `$parameters` for that transformation (e.g. `mode = "breadcrumb"`). <!-- TODO: add the specification of these other parameters somewhere else or in a clearly manner: DocBook `mode = "toc"` uses OPM's `opm-web` models (`details`/`pb-link`, matching `dapi:toc-div`) so a jinks `pb-load` of `toc.html` works with `toc.js`. Optional `target` overrides the pb-link emit channel (default `transcription`); `collapse = true` starts nested entries closed. -->| 
| `odd` / `mode` | Rare. Use a different ODD for this fragment only (`odd`), compiled for output channel `mode` (`web` by default — not the same as `$parameters?mode` above). Omit to reuse the chunking ODD. |

<!-- TODO: A string result (as with a bare `string(…)` xpath) is used as-is — fine inside a
Jinja template, but not valid as a standalone `.html` file. Prefer selecting an
element and transforming it (e.g. `parameters = { mode = "title" }`) when the
fragment is also written to disk. In a Jinja template:

```jinja
<title>{{ fragments.title | striptags | trim }}</title>
…
{{ fragments.breadcrumbs | safe }}
```
--> 
## Manifest and navigation

Chunking writes a manifest JSON describing every chunk: its file, anchors,
fragment locations, and `prev`/`next` navigation links. Cross-chunk links follow the
`chunking.link_pattern` configuration (placeholders `{file}`, `{stem}`, `{anchor}`, `{doc}`,
`{doc_stem}`), so you can match your site's URL scheme. `{doc}` is the
per-document subdirectory when chunking a directory of XML files (empty
otherwise), and `{doc_stem}` is that name without the `.xml` suffix<!-- — which is
what a framework route usually wants-->:

```toml
[chunking]
link_pattern = "/{doc}/{file}"          # /serafin01.xml/001.html
link_pattern = "/letters/{doc_stem}/{stem}/#{anchor}"   # /letters/serafin01/001/
```

## Several runs

One `[chunking]` table splits a document one way. When one document should
yield pages of different kinds — chapters and reference entries, letters and
the persons they mention — declare the table as an array instead, one
`[[chunking]]` entry per run:

```toml
[[chunking]]
name = "text"
output_dir = "site"
xpath = "//body/div"
file_pattern = "{xml_id}.html"

[[chunking.fragments]]      # belongs to the run above it
name = "toc"
scope = "global"
xpath = "."

[[chunking]]
name = "register"
xpath = "//listPerson/person"
file_pattern = "{xml_id}.html"
```

The runs execute in order, over each document, into one output directory:
only the first may set `output_dir`. Each run is handed the anchors of the runs
before it, so a register entry's `#chapter-3` link resolves to the text run's
page. `manifest.json` lists every run's chunks, each tagged with its `run`
name. The search index (`opm index`) covers all runs; an EPUB is built from the
first.

A single `[chunking]` table works exactly as before.

## `$parameters?root`

While a chunk is transformed, `$parameters?root` is the **original node** that
chunk was copied from (see [ODD files](odd-files.md#parametersroot)). The document node is
`root($parameters?root)`.

Chunks created by `dbk_section_chunks` and `tei_pb_chunks` sometimes yield a node detached from the original XML tree. Thus, this node has no ancestors, but it keeps the
source `xml:id`, so `opm` is able to map it back. ODD models that need the rest of the
document should walk from `$parameters?root`, and not from `.`. For example, to access the title of the document from a chunked article or section:

```xpath
(($parameters?root)/ancestor::article/info/title,
 ($parameters?root)/ancestor::section/title,
 title)
```

<!--`not($parameters?root is ..)` is then true only for ancestor titles, so the
current chunk’s heading stays unlinked in a breadcrumb trail.

`opm transform` (no chunking) binds `$parameters?root` to the document element,
so `root($parameters?root)//…` still reaches the header.
-->

## Manifest and navigation

Chunking writes a manifest JSON describing every chunk: its file, anchors,
fragment locations, and `prev`/`next` navigation links. Cross-chunk links follow
`chunking.link_pattern` (placeholders `{file}`, `{stem}`, `{anchor}`, `{doc}`,
`{doc_stem}`), so you can match your site's URL scheme. `{doc}` is the
per-document subdirectory every chunk run writes, and `{doc_stem}` is that name
without the `.xml` suffix — which is what a framework route usually wants:

```toml
[chunking]
link_pattern = "/{doc}/{file}"          # /serafin01.xml/001.html
link_pattern = "/letters/{doc_stem}/{stem}/#{anchor}"   # /letters/serafin01/001/
```

## Stylesheets and static assets

Chunking always writes the stylesheets as files under `<output-root>/css/` and
hands templates the path to the CSS (`odd_css_url`). <!--Chunk output is several pages
sharing one stylesheet, so embedding the same bytes in each page only makes the
output bigger and uncacheable. (`--format pb-view` has always written
`css/<odd>.css`; HTML output now matches it.)-->

The file `css/<odd>.css` holds the ODD's own `<rendition>` rules, preceded by the base
rules every ODD-rendered document needs (e.g. the `.alternate` / `.altcontent`
popover behind the `choice` behaviour , `.tei-cb` for column breaks, etc.; these can still be overridden by the ODD's `outputRendition`). 

`[transform] css` does not add a second stylesheet — it *replaces* those base
rules, so a project can change the default style without losing the ODD's
own renditions. <!--Because it changes the compiled stylesheet it is part of the ODD
cache key, so a project overriding it gets its own compiled module.-->

```jinja
<link rel="stylesheet" href="{{ odd_css_url }}">
```
<!--
The `odd_css` string is still passed, so a template that inlines it keeps
working, and the URL is empty when the stylesheet turns out to be empty — hence
the defensive form used by the packaged template:

```jinja
{% if odd_css_url %}<link rel="stylesheet" href="{{ odd_css_url }}">
{% elif odd_css %}<style>{{ odd_css }}</style>{% endif %}
```
-->
Anything else a page needs — the template's own stylesheet, an image, a font —
is listed under `assets`<!--, because the output directory is wiped on every
rebuild and nothing else puts files there-->:

```toml
[chunking]
assets = ["templates/letter.css", "templates/parchment.jpg", "templates/fonts"]
```

Each entry is copied into `<output-root>/assets/`, keeping its own name. An
entry may be a glob, which is how a project stops editing this list every time
it gains a document:

```toml
assets = ["iiif/*"]     # every iiif/<document>.xml/ lands in assets/
```

Templates receive an `assets` URL prefix for referencing them by hand, and
`asset_styles` — the stylesheets among them, as URLs, in the order declared —
so a template links them without naming any file:

```jinja
{% for href in asset_styles %}<link rel="stylesheet" href="{{ href }}">{% endfor %}
```

Declaration order is cascade order, with a glob's own matches sorted by name.
Only entries — or glob matches — whose suffix is `.css` are linked; a directory
copied as an asset is not scanned, so adding `fonts/` does not start injecting
stylesheets from inside it. A listed path that does not exist, or a pattern
matching nothing, fails the run rather than leaving the output a file short.

<!--A stylesheet in `assets/` references a sibling by plain filename
(`url("parchment.jpg")`), since CSS URLs resolve against the stylesheet's own
location rather than the page's — so one texture file serves the whole edition
instead of a base64 copy per page. That is why project design CSS belongs here
rather than in `[transform] css`: only assets can carry the files it depends on.

All these URLs are relative to the page that uses them: bare from the index at
the output root, `../`-prefixed from a chunk page in a per-document
subdirectory.-->

Images the document itself references need no entry. When a chunk page contains
an `<img>` whose `src` is a relative path, the file is looked up next to the
source XML, then in a sibling `images/` directory — the same rule EPUB output
follows — and copied to that path beside the chunk pages. Remote URLs, root-relative paths, and paths leading out of
the output directory are left alone; images that cannot be found are skipped.

<!--The `serafin` example does exactly this. Its pages dropped from 168 KB to 96 KB
and its index from 91 KB to 19 KB, with 42 KB of shared CSS and imagery fetched
once and cached.-->

## Collection index

Chunking writes one subdirectory per document, plus an `index.html` at the
output root listing them all — one document or fifty. `http.server` serves
`index.html` in preference to a directory listing, so `opm serve` shows a real
landing page with no further configuration.

Each entry links to its document's first chunk. What the entry *shows* comes
from the document's global fragments, so the index is built the same way TEI
Publisher builds `browse.html` — through the ODD. This is thus done by declaring a fragment using the
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
automatically, per document. To use a different
URL scheme, set it explicitly; `{doc}`, `{doc_stem}`, `{file}` and `{stem}`
expand exactly as in `link_pattern`:

```toml
parameters = { display = "browse", doc = "/exist/apps/edition/{doc}/{stem}" }
```

The same expansion applies to `[transform.parameters]`, with one placeholder
more: `{prefix}` is the path from a chunk page back to the output root, where
the shared `css/` and `assets/` live — `../` for the pages `opm chunk` writes.
A parameter holding a URL into `assets/` should use it rather than hard-coding
that hop:

```toml
[transform.parameters]
context-path = "{prefix}assets"
```

The index degrades gracefully when a project has no such models: it falls back
to a `title` fragment if one is declared, and to a readable form of the filename
otherwise. Every entry stays clickable in all three cases.

You can override the page itself with `chunking.index_template`. The template receives
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

The template also receives `odd_css`, resolved exactly as for chunk pages, so the  `tei-*` classes of a browse record are styled the same way on the
index as inside the edition.

```jinja
<style>{% include "letter.css" %}</style>
{% if odd_css %}<style>{{ odd_css }}</style>{% endif %}
...
<body class="letter">
  <nav class="app-menubar">…</nav>
```

`templates/index.html.j2` in the `serafin` example does this: it includes the same
`letter.css` as the chunk template and reuses its menubar, toolbar and page
shell, so the landing page cannot drift from the letters it links to. The
list's own rules live in that stylesheet too, under `.letter-list`, rather than
in a `<style>` block on the index — thus the design can be changed from just one place.

## Previewing

Chunk and preview in one step with the `--preview` flag. It serves the output directory and
opens the first page in a browser — `index.html` for a directory run, `001.html`
for a single document. Only HTML output is opened;
`--format json` / `pb-view` is served for another tool to fetch.

```bash
opm chunk data/F-ado.xml -o chunks/ --force --preview
```

Or serve an existing chunk directory:

```bash
opm serve -d chunks/
```

## From Python

The CLI wraps [`opm.chunking.chunk_document`](../api/chunking.md); call it
directly to integrate chunking into your own build pipeline.
