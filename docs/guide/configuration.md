# Configuration (`opm.toml`)

Place an `opm.toml` file in the project root to set defaults for all CLI
commands. Every section is optional, and CLI options always override config
values. Pass a different file with `-c` (for example `teipublisher.toml` for a
project-specific setup).

The schema below is loaded into
[`opm.config.ProjectConfig`](../api/config.md); paths are resolved relative to
the config file.

```toml
[project]
# Additional Python paths (relative to the config file) for custom extensions
pythonpath = ["extensions"]

[transform]
# Default transform module (used when --module is omitted)
module = "modules/teipublisher-web.py"
# XPath extension modules loaded for every transform (see XPath extensions guide)
xpath_extensions = ["extensions.my_functions"]
# XML documents available to XPath doc(); paths are relative to this config file
documents = ["data/authority.xml", "data/lookup.xml"]

[docx]
# Default Word style template for DOCX output (overridable with --template)
template = "templates/corporate.docx"

[typst]
# Default Typst (.typ.j2) template for Typst output
template = "templates/book.typ.j2"

[document]
# Default Jinja2 template for full-document HTML output
template = "templates/default.html.j2"
# Default CSS file injected into HTML output
css = "styles/main.css"

[webcomponents]
# Enable tei-publisher web components mode by default
enabled = false
# CDN URL template for pb-components (use {version} placeholder)
# cdn = "https://cdn.jsdelivr.net/npm/@teipublisher/pb-components@{version}/dist/pb-components-bundle.js"

[chunking]
# Transform module used for chunking (falls back to [transform] module)
module = "modules/teipublisher-web.py"
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
# URL pattern for cross-chunk links ({file}, {stem}, {anchor} placeholders)
link_pattern = "/{stem}/"
```

## Sections

| Section | Purpose | Related guide |
| --- | --- | --- |
| `[project]` | `pythonpath` additions so local extension modules import | [XPath extensions](xpath-extensions.md) |
| `[transform]` | Default transform `module`, `xpath_extensions`, and `documents` for `doc()` | [Output formats](output-formats.md) |
| `[document]` | HTML `template` and `css` | [Templates & CSS](templates-and-css.md) |
| `[docx]` | Word style `template` | [Output formats](output-formats.md#docx) |
| `[typst]` | Typst `template` | [Output formats](output-formats.md#typst) |
| `[webcomponents]` | `enabled` flag and `cdn` URL | [Templates & CSS](templates-and-css.md#web-components) |
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
