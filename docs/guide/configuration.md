# Configuration (`opm.toml`)

Place an `opm.toml` file in the project root to set defaults for all CLI
commands. `opm init` writes a working file; every section is optional, and CLI
options always override config values. Pass a different file with `-c` (for
example `examples/docbook/opm.toml` for a project-specific setup — see
[Integration with TEI Publisher](tei-publisher.md)).

The schema below is loaded into
[`opm.config.ProjectConfig`](../api/config.md); paths are resolved relative to
the config file.

```toml
[project]
# Additional Python paths (relative to the config file) for custom extensions
pythonpath = ["."]

[transform]
# Default ODD for every output mode (compiled on demand)
odd = "odd/my-customisation.odd"
# XPath extension modules loaded for every transform (see XPath extensions guide)
xpath_extensions = ["extensions.my_functions"]
# XML documents available to XPath doc(); paths are relative to this config file
documents = ["data/authority.xml", "data/lookup.xml"]
# Base rules compiled into the ODD stylesheet for every output mode, replacing
# the packaged defaults (overridable with --css)
css = "styles/default-styles.css"

[transform.web]
# Default Jinja2 template for full-document HTML output (overridable with --template)
template = "templates/default.html.j2"
# Emit tei-publisher web components (overridable with --webcomponents/--no-webcomponents).
# The bundle URL is a template value: set webcomponents_url in [transform.web.context]
# to serve it yourself or pin another version.
webcomponents = false

[transform.docx]
# Optional per-mode ODD override; omit to use [transform].odd
# odd = "odd/docx-special.odd"
# Default Word style template for DOCX output (overridable with --template)
template = "templates/corporate.docx"

[transform.typst]
# Default Typst (.typ.j2) template for Typst output
template = "templates/book.typ.j2"

[context]
# Free-form values handed to every Jinja2 template as `context`. TOML types are
# preserved; a [transform.<type>.context] table overlays this per output type.
site_name = "The Serafin Letters"
show_downloads = true
nav = [{ label = "Home", url = "/" }]

[chunking]
# ODD used for chunking (falls back to [transform].odd / packaged default)
# odd = "odd/my-customisation.odd"
# XPath expression selecting chunk root elements
xpath = "//text/body/div"
# Python callable for custom chunk selection logic
# selector = "extensions.my_chunk_selector"
# Maximum heading depth for chunk splitting
depth = 2
# Output directory for chunk files
output_dir = "chunks"
# Jinja2 template for chunk pages
template = "templates/chunk.html.j2"
# URL pattern for cross-chunk links ({file}, {stem}, {anchor}, {doc}, {doc_stem})
link_pattern = "/{doc}/{file}"
# Jinja2 template for the collection index written when chunking a directory
index_template = "templates/index.html.j2"
# Heading for that index (default: the input directory name)
index_title = "Correspondence"
# Files or directories copied into <output-root>/assets/ (stylesheets are
# always written to <output-root>/css/ automatically)
assets = ["templates/edition.css", "templates/parchment.jpg"]
```

## Sections

| Section | Purpose | Related guide |
| --- | --- | --- |
| `[project]` | `pythonpath` additions so local extension modules import | [XPath extensions](xpath-extensions.md) |
| `[transform]` | Shared settings (`odd`, `xpath_extensions`, `documents`, `parameters`, base `css`) | [Output formats](output-formats.md), [ODD `$parameters`](odd-files.md#parameters), [Templates & CSS](templates-and-css.md#two-kinds-of-css) |
| `[transform.web]` | Optional web-only `odd` override and HTML `template` | [Templates & CSS](templates-and-css.md) |
| `[transform.print]` | Optional print `odd` and HTML `template` | [Output formats](output-formats.md#print-paged-media) |
| `[transform.epub]` | Optional EPUB `odd`, `css` and `skip_title` | [Output formats](output-formats.md#epub) |
| `[transform.docx]` | Optional DOCX `odd` override and Word style `template` | [Output formats](output-formats.md#docx) |
| `[transform.typst]` | Optional Typst `odd` override and Typst `template` | [Output formats](output-formats.md#typst) |
| `[transform.json]` | Optional `odd` override for the JSON data output | [Output formats](output-formats.md#json) |
| `[transform.markdown]`, … | Other optional per-type `odd` (and `template`) overrides | [Output formats](output-formats.md) |
| `[transform.web] webcomponents` | Web-only flag enabling TEI Publisher web components | [Templates & CSS](templates-and-css.md#web-components) |
| `[context]` | Free-form values exposed to every template as `context` | [Templates & CSS](templates-and-css.md#template-context) |
| `[transform.<type>.context]` | Per-output-type overlay on `[context]` | [Templates & CSS](templates-and-css.md#template-context) |
| `[chunking]` | Splitting rules, output, templates, fragments | [Chunking](chunking.md) |
| `[index]` | `max_chars`, `min_chars`, `overlap`, `[[index.units]]` and `[[index.fields]]` for `opm index` | [Search indexing](search-indexing.md) |

Loaded programmatically, these map to
[`ProjectConfig`](../api/config.md) and
[`ChunkingConfig`](../api/config.md). The `[chunking]` section also accepts
`fragments`, `view`, `map`, `parameters`, and `doc_path` keys consumed by the
chunking pipeline.

`[transform].documents` is loaded into the XPath dynamic context for both
`opm transform` and `opm chunk`. During evaluation, the XPath base URI is set to
the main XML document being processed, so `doc("lookup.xml")` resolves relative
to that input document's URI and must match one of the configured document URIs.

The same URI is attached to the document node, so `document-uri()` and
`base-uri()` report the input file. Under `opm chunk` this holds inside a chunk
too: the chunk is a rebuilt copy of the page, but `$parameters?root` still
points into the source document, and `root($parameters?root)` reaches the whole
of it — which is how ODD models climb back to the `teiHeader` from a page.

### Selecting an ODD by type

`opm transform --type|-t` picks the ODD from config without passing `--odd`.
ODDs are compiled on demand into the user cache.

Precedence for each mode:

1. `--odd` / `-d` on the CLI
2. `[transform.<type>].odd` for the selected `--type`
3. `[transform].odd` (shared default)
4. Packaged stock teipublisher ODD

| `--type` | Config key (override) | Falls back to |
| --- | --- | --- |
| `web` (default when `--type` is omitted) | `[transform.web].odd` | `[transform].odd` |
| `print` | `[transform.print].odd` | `[transform].odd` |
| `epub` | `[transform.epub].odd` | `[transform].odd` |
| `docx` | `[transform.docx].odd` | `[transform].odd` |
| `typst` | `[transform.typst].odd` | `[transform].odd` |
| `markdown`, … | `[transform.<type>].odd` | `[transform].odd` |

Legacy configs that only set `[transform.web].odd` still work: that value is
treated as the shared default when `[transform].odd` is omitted. Legacy
top-level `[docx]` / `[typst]` sections are still accepted as a fallback.

```bash
opm transform examples/tei-test.xml -t web --preview
opm transform examples/tei-test.xml -t typst -o out.typ
opm transform examples/tei-test.xml -t docx -o out.docx
```
