# Chunking

While `opm transform` transforms a single input to a single output, `opm chunk` operates on a whole collection of XML files.
It can also split large documents into smaller pieces to make them easier to read. The split may happen at page boundaries – if marked up –
or per division and is configurable.

Besides the main content, chunking may also produce other content fragments, e.g. for a sidebar
or breadcrumbs. Every piece of content is transformed through ODD.

In `html` mode, the combined result of each chunking run – i.e. main content plus fragments – will be passed on
to a template, which assembles the different pieces into an output page. However, there are two other modes, which generate raw
data instead of a complete page. Those are intended to be consumed by external tools, which will handle the final rendering.

The three different types of output modes are (use `--format` to switch between them):

- **`html`** (default) — renders each chunk through a template
  (`chunking.template`, else the `[transform.web]` template), generating a series of HTML files. Use this for quick previews
  or to create a simple static edition which does not need a complex framework.
- **`json`** — one JSON file per chunk, including the rendered content and optional fragments. Ideal for integration into 
static site generators like [Eleventy](https://www.11ty.dev/), [Hugo](https://gohugo.io/), [Astro](https://astro.build/) and others 
that consume data files.
- **`pb-view`** — an index table plus part files to be consumed by [TEI Publisher's](https://tei-publisher.org)
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

### Selecting the documents

The input of `opm chunk` is one XML file, a directory, or a glob pattern:

- **A directory** stands for the `*.xml` files directly inside it. Subdirectories
  are not searched.
- **A glob pattern** selects files anywhere below a directory, and only those
  whose name fits. `**` matches any number of subdirectories. Quote the pattern,
  so that opm expands it rather than the shell:

    ```bash
    opm chunk 'data/collation/**/*.col.xml' --force
    ```

A directory and a pattern are both treated as a collection: every document goes
to a subdirectory of its own, and an `index.html` lists them. The subdirectory
is named after the file (`aarets-historie.col.xml/`) unless `document_name` derives
a name from the document. If two files in different directories have the same
name, opm stops and asks you to set `document_name`.

To build the same set of documents every time, put the input in `opm.toml`.
A relative path is resolved against the directory of `opm.toml`, and
`opm chunk` without an argument then reads it. An input given on the command
line is then ignored, and `opm chunk` reports that it is:

```toml
[chunking]
input = "data/collation/**/*.col.xml"
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

## Naming documents

Each document gets a directory of its own below the output directory, named
after its file: `data/letters/K_0096.xml` is published as `K_0096.xml/001.html`.
To use an identifier from the document instead, give an XPath. It is evaluated
on each document's root and its string value becomes the directory name:

```toml
[chunking]
document_name = "'B' || substring-after(/TEI/@xml:id, 'K_')"   # B0096/
file_pattern = "index.html"                                     # B0096/index.html
```

The name is also what templates get as `document`, and what `documents` lists,
so links between documents can be built from identifiers found in the TEI
(see the `escher` example). Two documents with the same name, or a document
whose expression gives an empty string, stop the run with an error.

A `/` in the name nests the directory. Pages then sit one level deeper, and
their links to the shared `css/` and `assets/` and to the index climb back
accordingly:

```toml
[chunking]
document_name = "substring-before(/TEI/@xml:id, '.') || '/collation'"   # aarets-historie/collation/
```

A document's directory may not lie inside another document's (`a/` and
`a/b/`).
`--format pb-view` ignores the setting: pb-view fetches its data by file path.

## Fragments

Alongside the main chunk content, you can extract **fragments** — secondary
pieces pulled from the document or from each chunk, such as a table of contents,
breadcrumbs, or the work title. Each one of them is configured under `[chunking.fragments]` and there are two different scopes: `global` (document root as context) and `per-chunk` (chunk as context). They are listed in the manifest, and you can retrieve them in the templates with `fragments.<name>`.

Global fragments also appear when you run `opm transform` on the whole
document. The page template gets them under the same name, so one template
can show the work title on chunk pages and on the single page alike.

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
template, but not valid as a standalone `.html` file. Prefer selecting an
element and transforming it (e.g. `parameters = { mode = "title" }`) when the
fragment is also written to disk. In a template:

```html
<title>[[ normalize-space($context?fragments?title) ]]</title>
…
[[ $context?fragments?breadcrumbs ]]
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

### Runs with documents of their own

Any run, the first included, may set `input`. It then reads only those files
and names their directories with its own `document_name`, so several
collections, each with its own ODD, template and splitting, are published
side by side. Here each work gets its collation
and its introduction side by side, in `<slug>/collation/` and `<slug>/intro/`:

```toml
[[chunking]]
name = "collation"
input = "data/collation/*/*.col.xml"
document_name = "substring-before(/TEI/@xml:id, '.col') || '/collation'"
odd = "odd/collation.odd"

[[chunking]]
name = "intro"
input = "data/intro/*/intro_*.xml"
document_name = "substring-before(/TEI/@xml:id, '.intro') || '/intro'"
odd = "odd/intro.odd"
template = "templates/handbook.html.tpl"
xpath = "/TEI/text"        # the whole text on one page
```

Two runs may read the same files, for two presentations of the same
documents, as long as their `document_name` puts them in different
directories. A run can also switch web components on for its own pages, for
example for a facsimile view beside a plain reading view:

```toml
[[chunking]]
name = "single"
input = "data/works/*/*.xml"
document_name = "/TEI/@xml:id || '/single'"
xpath = "/TEI/text"                       # the whole text on one page

[[chunking]]
name = "facs"
input = "data/works/*/*.xml"
document_name = "/TEI/@xml:id || '/facs'"
selector = "opm.navigation.tei_pb_chunks" # one page per <pb>
view = "page"
webcomponents = true                      # for the iiif profile's viewer
parameters = { iiif-viewer = "pb-facsimile" }
```

`document_name` can also use the file's location: `document-uri(/)` is its
`file:` URL, so `tokenize(document-uri(/), '/')[last() - 1]` is the name of
the directory it is in.

Runs without an `input` read the input given on the command line, together,
as before. A run with an `input` ignores it, and `opm chunk` reports this; if
every run has one, the command-line input is not used at all. A file may be
read by one input only, and the directories of all runs must stay apart. The
collection index lists the documents of every run.

A single `[chunking]` table works exactly as before.

## Auxiliary pages

The primary purpose of OPM is to transform a set of input documents into a collection of outputs.
This is what `[[chunking]]` was designed for.

However, `[[chunking]]` makes some assumptions:

* it always needs at least one XML input file
* every processed document produces exactly one output directory in html mode
* appends to the list of documents appearing on the default browse page

On its own, `[[chunking]]` is sufficient to create a nice basic website
with reading views for each document and a landing page listing the content.

But a full website usually needs more than that: besides the main content, there will be auxiliary pages, which may or may not
have been generated from XML. The configuration therefore supports another category: `pages`. This allows you to render any number
of auxiliary content pages by appending their configurations to the `[[pages]]` array. Contrary to `[[chunking]]`, `[[pages]]` are
more generic: 

* they don't require an XML input at all, but can just be static HTML
* you have full control over where the output is stored

In other words: _pages_ are the missing building block you need to create a full static website with OPM.

`opm chunk` automatically processes `[[pages]]`, but only if the output format is `html`. For the other formats, `json` and `pb-view`,
`[[pages]]` is ignored: those are exchange formats, which produce raw data, not a complete website.

```toml
# A static page: no source, the template alone is rendered.
[[pages]]
path = "about.html"
template = "templates/about.html.tpl"
context = { page_title = "About" }    # this page's <title>

# One page listing every place.
[[pages]]
path = "places/index.html"
context = { page_title = "Places" }
source = "data/registers/places.xml"   # the page's own source, not the letters
xpath = "//listPlace"                  # must select exactly one node
parameters = { mode = "register-overview" }

# One page per place, named by its xml:id: places/Krakow.html, …
[[pages]]
path = "places/{xml_id}.html"
source = "data/registers/places.xml"
xpath = "//listPlace/place"
```

A page with `source` is rendered through the same ODD machinery as a chunk —
same selector, fragments, link rewriting — so the difference is only the
contract with the site: a fixed `path` (a placeholder like `{xml_id}`,
`{ident}`, `{stem}` or `{index}` yields one page per selected node; without a
placeholder the path is a single page and must select exactly one node), no
per-document subdirectory, no prev/next, and no listing in `index.html`.
Link to a page from the menubar with `[context.menu] items`. Pages receive the
chunking runs' anchors, so they can link into the reading view; links to a
page itself use its stable path. A page template also receives
`site_documents`: for every document of the site its `name` and the `href`
of its first page. Which documents mention a register entry is up to the ODD,
which can search them with `collection()` (see the registers profile). Links written the TEI Publisher way, from
the site root and without `.html` (`places/Krakow`), are pointed at the page
opm wrote. A page directory's `manifest.json` is tagged
`"role": "page"` so the collection index skips it.

A page's `context` table is merged over the project's `[context]` for that
page only, the way a template's frontmatter is: tables combine key by key.
That is how a page passes its template what the project as a whole does not
know, such as its title: `page_title` becomes the page's `<title>` in the
standard layout, and a template can read it as `$context?page_title`. A
project that changes a profile's page merges its `context` with the
profile's the same way.

The menubar is not derived from pages: it reads `[context.menu] items` only,
so a page you want linked there — e.g. a profile's browse page — is listed
explicitly:

```toml
[context.menu]
items = [{ label = "Places", url = "places/index.html" }]
```

Menu URLs are relative to the site root and the layout prefixes them with the
page's path back to it (`../` from a chunk page, nothing at the root) — where
a TEI Publisher application prefixes them with the context-path. Set
`enabled = false` on a `[[pages]]` entry to switch a page (e.g. one a profile
contributed) off.

Pages inherit the first chunking run's ODD, template, assets and parameters;
`template`, `odd`, `parameters` and `[[pages.fragments]]` override them per
page. Pages are HTML-only: `--format json` and `--format pb-view` skip them,
since those feed an external site generator that builds its own pages. Use
`--no-pages` to build the reading view alone, or `--page places` to build only
the pages whose path starts with a prefix.

A page with `path = "index.html"` is the site's own landing page: it takes
the place of the collection index `opm chunk` would otherwise write there. Its
template can read the project's `[[transform.collections]]` with
`collection()`, so a landing page can list things that are not chunked
documents themselves, and link those that are through `site_documents`:

```toml
[[transform.collections]]
uri = "urn:works"
documents = ["data/index/*/index.xml"]

[[pages]]
path = "index.html"
template = "templates/works-index.html.tpl"
```

```html
[% for $work in collection('urn:works') %]
[% let $slug = tokenize(document-uri($work), '/')[last() - 1] %]
[% let $intro = $context?site_documents?*[?name = $slug || '/intro'] %]
<h2>[[ ($work//tei:titleStmt/tei:title)[1] ]]</h2>
[% if exists($intro) %]<a href="[[ $intro?href ]]">Introduction</a>[% endif %]
[% endlet %][% endlet %]
[% endfor %]
```

Profiles can declare `[[pages]]` in their `opm-profile.toml` (see
[Profiles](profiles.md)); a project entry with the same `path` replaces the
profile's, so the project can repoint `source` at its own data.

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

```html
<link rel="stylesheet" href="[[ $odd_css_url ]]">
```
<!--
The `odd_css` string is still passed, so a template that inlines it keeps
working, and the URL is empty when the stylesheet turns out to be empty — hence
the defensive form used by the packaged template:

```html
[% if $odd_css_url %]<link rel="stylesheet" href="[[ $odd_css_url ]]">
[% elif $odd_css %]<style>[[ $odd_css ]]</style>[% endif %]
```
-->
Anything else a page needs, such as the template's own stylesheet, images,
fonts or scripts, is listed under `assets` in `[transform.web]`. Chunking
copies these files into `<output-root>/assets/`, shared by all pages, unless
`[chunking]` names its own `assets`. See [Assets](assets.md) for how to list
them and refer to them from templates. A template that extends opm's page
layout (see [Template inheritance](templates-and-css.md#template-inheritance))
also gets the layout's own stylesheet, written to
`<output-root>/css/opm-layout.css`.

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
output root listing them all. Each entry in the `index.html` links to its document first page.

How a document appears in the list is determined by the ODD and is taken from a fragment named `browse` in `opm.toml`. The default ODD renders a short title if parameter `display` is set to `browse`:

```toml
[[chunking.fragments]]
name = "browse"
scope = "global"
xpath = "(/article/info, /book/info)[1]"   # TEI: "//teiHeader"
parameters = { display = "browse" }
```

The corresponding ODD models build the link to the document from `$parameters?doc`. That parameter is supplied automatically, per document. To use a different URL scheme, set it explicitly; `{doc}`, `{doc_stem}`, `{file}` and `{stem}` expand exactly as in `link_pattern`:

```toml
parameters = { display = "browse", doc = "/exist/apps/edition/{doc}/{stem}" }
```

The index page degrades gracefully when a project has no such models: it falls back to a `title` fragment if one is declared, and to a readable form of the filename otherwise. Every entry stays clickable in all three cases.

The default template for the index page includes a hero section above the list of documents. This includes the name of your edition, a short description and how many documents it holds. Set the name and the description
in `opm.toml`:

```toml
[context]
site_name = "Briefedition Alfred Escher"
description = "Letters to and from Alfred Escher, 1831–1882."
```

The hero may also have a background image. Add the image to your project, have opm copy it into the output's `assets/` folder, and name it under `[context.theme.index.hero]`:

```toml
[transform.web]
assets = ["templates/cover.jpg"]

[context.theme.index.hero]
image = "cover.jpg"
position = "center 30%"
text = "light"            # or "dark" for a pale picture
```

`opm` darkens the picture behind light text, or lightens it behind dark text,
so the words stay readable. `image` can also be a path or a full URL.

Readers can narrow the list by typing into the filter box (press <kbd>/</kbd> to
jump there), and switch between a list and a grid of cards. The words on the
page, the view it opens with and when the filter box appears are set under
`[context.theme.index]`; see `opm/defaults.toml` in the package for all of them:

```toml
[context.theme.index]
eyebrow = "Briefe"
filter_placeholder = "Briefe filtern …"
view = "grid"
```

You can override the page itself with `chunking.index_template`. The template receives
`documents` — each with `name`, `stem`, `label`, `href`, `chunks` and
`fragments` — plus `title`:

```html
[% for $doc in $documents?* %]
  <article>
    [[ ($doc?fragments?browse, $doc?fragments?title, $doc?label)[1] ]]
    <a href="[[ $doc?href ]]">[[ $doc?chunks ]] sections</a>
  </article>
[% endfor %]
```

Because `fragments` is passed whole, adding an author or date column needs no
code — just another global fragment in `opm.toml` and a reference to it here.

The template also receives `odd_css` and the assets' stylesheets, exactly as
chunk pages do, so the `tei-*` classes of a browse record are styled the same
way on the index as inside the edition.

An index template of your own works best if it extends the same page layout
as your pages, `opm/layout.html.tpl`, and keeps its own rules in the same
stylesheet. The landing page then cannot drift from the pages it links to,
and the design can be changed in one place:

```html
---json
{ "templating": { "extends": "opm/layout.html.tpl" } }
---
[% template breadcrumb %][[ $context?title ]][% endtemplate %]

<ul class="letter-list">…</ul>
```

Often you need no template at all: the packaged index already uses the page
layout, and its texts can be changed under `[context.theme.index]`. The
`serafin` and `escher` examples do this. See
[Template inheritance](templates-and-css.md#template-inheritance).

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
