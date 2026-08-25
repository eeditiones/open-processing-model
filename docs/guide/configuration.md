# Configuration (`opm.toml`)

Place an `opm.toml` file in the project root to set defaults for all CLI
commands. `opm init` writes a working file; every section is optional, and CLI
options always override config values. Pass a different file with `-c` (for
example `teipublisher.toml` for a project-specific setup).

The schema below is loaded into
[`opm.config.ProjectConfig`](../api/config.md); paths are resolved relative to
the config file.

```toml
[project]
# Additional Python paths (relative to the config file) for custom extensions
pythonpath = ["extensions"]

[transform]
# Default ODD for every output mode (compiled on demand)
odd = "odd/teipublisher.odd"
# XPath extension modules loaded for every transform (see XPath extensions guide)
xpath_extensions = ["extensions.my_functions"]
# XML documents available to XPath doc(); paths are relative to this config file
documents = ["data/authority.xml", "data/lookup.xml"]

[transform.docx]
# Optional per-mode ODD override; omit to use [transform].odd
# odd = "odd/docx-special.odd"
# Default Word style template for DOCX output (overridable with --template)
template = "templates/corporate.docx"

[transform.typst]
# Default Typst (.typ.j2) template for Typst output
template = "templates/book.typ.j2"

[transform.web.webcomponents]
# Enable tei-publisher web components mode by default
enabled = false
# CDN URL template for pb-components (use {version} placeholder)
# cdn = "https://cdn.jsdelivr.net/npm/@teipublisher/pb-components@{version}/dist/pb-components-bundle.js"

[document]
# Default Jinja2 template for full-document HTML output
template = "templates/default.html.j2"
# Default CSS file injected into HTML output
css = "styles/main.css"

[chunking]
# ODD used for chunking (falls back to [transform].odd / packaged default)
# odd = "odd/teipublisher.odd"
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
# URL pattern for cross-chunk links ({file}, {stem}, {anchor}, {doc} placeholders)
link_pattern = "/{doc}/{file}"
```

## Sections

| Section | Purpose | Related guide |
| --- | --- | --- |
| `[project]` | `pythonpath` additions so local extension modules import | [XPath extensions](xpath-extensions.md) |
| `[transform]` | Shared settings (`odd`, `xpath_extensions`, `documents`, `parameters`) | [Output formats](output-formats.md), [ODD `$parameters`](odd-files.md#parameters) |
| `[transform.web]` | Optional web-only `odd` override | [Output formats](output-formats.md) |
| `[transform.docx]` | Optional DOCX `odd` override and Word style `template` | [Output formats](output-formats.md#docx) |
| `[transform.typst]` | Optional Typst `odd` override and Typst `template` | [Output formats](output-formats.md#typst) |
| `[transform.markdown]`, … | Other optional per-type `odd` (and `template`) overrides | [Output formats](output-formats.md) |
| `[transform.web.webcomponents]` | Web-only `enabled` flag and `cdn` URL for pb-components | [Templates & CSS](templates-and-css.md#web-components) |
| `[document]` | HTML `template` and `css` | [Templates & CSS](templates-and-css.md) |
| `[chunking]` | Splitting rules, output, templates, fragments | [Chunking](chunking.md) |

Loaded programmatically, these map to
[`ProjectConfig`](../api/config.md) and
[`ChunkingConfig`](../api/config.md). The `[chunking]` section also accepts
`fragments`, `view`, `map`, `parameters`, and `doc_path` keys consumed by the
chunking pipeline.

`[transform].documents` is loaded into the XPath dynamic context for both
`opm transform` and `opm chunk`. During evaluation, the XPath base URI is set to
the main XML document being processed, so `doc("lookup.xml")` resolves relative
to that input document's URI and must match one of the configured document URIs.

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
| `docx` | `[transform.docx].odd` | `[transform].odd` |
| `typst` | `[transform.typst].odd` | `[transform].odd` |
| `markdown`, `print`, … | `[transform.<type>].odd` | `[transform].odd` |

Legacy configs that only set `[transform.web].odd` still work: that value is
treated as the shared default when `[transform].odd` is omitted. Legacy
top-level `[docx]` / `[typst]` sections are still accepted as a fallback.

```bash
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t typst -o out.typ
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t docx -o out.docx
```
