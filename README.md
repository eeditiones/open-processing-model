# Open Processing Model

A Python CLI and library for transforming XML documents (TEI, DocBook, …) using TEI Processing Model rules compiled from ODD files. Outputs HTML, Markdown, and DOCX.

## Setup (with uv)

### Python version requirement

- Minimum supported Python version: **3.12** (see `pyproject.toml` → `requires-python = ">=3.12"`).
- `uv` does **not** force-upgrade your system Python automatically, but it can use or provision a compatible interpreter for the project.
- If needed, install/provision Python 3.12 with:

```bash
uv python install 3.12
```

### 1) Install `uv`

If you do not have `uv` yet, install it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart your shell (or source your profile) so `uv` is on `PATH`.

### 2) Install project dependencies

From the project root:

```bash
uv sync
```

This creates `.venv` and installs runtime dependencies from `pyproject.toml` /
`uv.lock`. For pytest and other dev tools, also run `uv sync --group dev` (see
**Running tests** below).

### 3) Verify the installation

```bash
uv run opm --help
uv run --group dev pytest -q
```

### 4) Typical first run

The library compiles TEI Processing Model instructions from an ODD into a Python module, which can then be reused across transformations.

```bash
# Generate transform module from ODD
uv run opm compile odd/teipublisher.odd

# Apply transform to an XML file — HTML preview in browser
uv run opm transform modules/teipublisher-web.py demo/tei-test.xml \
  --preview --template templates/tufte.html.j2

# Generate a DOCX file
uv run opm compile odd/teipublisher.odd --mode docx
uv run opm transform modules/teipublisher-docx.py demo/tei-test.xml \
  -o output.docx

# Generate Markdown
uv run opm compile odd/teipublisher.odd --mode markdown
uv run opm transform modules/teipublisher-markdown.py demo/tei-test.xml --preview
```

## Running tests

The test suite uses [pytest](https://pytest.org/) (listed under the `dev` dependency group in `pyproject.toml`). From the project root, install dev dependencies if you have not already:

```bash
uv sync --group dev
```

Run all tests:

```bash
uv run --group dev pytest
```

Useful variants:

```bash
# Quiet (one line per file)
uv run --group dev pytest -q

# Verbose, stop on first failure
uv run --group dev pytest -v -x

# Single file or test node id
uv run --group dev pytest tests/test_odd_compiler.py -q
uv run --group dev pytest tests/test_odd_compiler.py::test_compile_teipublisher_odd_emits_valid_python -q
```

## CLI Commands

Use `uv run opm --help` to see global help.

### `opm compile`

Compile an ODD file into a Python transform module.

```bash
uv run opm compile odd/teipublisher.odd -o modules/teipublisher-web.py
```

Arguments and options:

- `odd` (required): path to the `.odd` file.
- `-o, --output`: write generated Python to this path (default: `modules/<odd-basename>-<mode>.py` under the current working directory).
- `-m, --mode`: ODD processing-model output channel — `web` (HTML), `markdown`, `docx`, `print`, or any other `@output` value defined in the ODD (default: `web`).
- `--module-name`: logical module name used in generated docstring (default: `generated_odd`).
- `-t, --target`: target language for code generation — currently only `python` (default: `python`).

### `opm transform`

Load a generated transform module and apply it to an XML file.

```bash
uv run opm transform modules/teipublisher-web.py input.xml -o output.html
uv run opm transform modules/teipublisher-docx.py input.xml -o output.docx
```

The transform module must define:

- `transform(root, options=None)` — run the processing model.
- `transform_output_channels()` — return the channel list (e.g. `['web']`, `['docx']`). Modules emitted by `opm compile` include this automatically.

Arguments and options:

- `-m, --module PATH`: path to the transform `.py` file. Falls back to `transform.module` in `opm.toml`.
- `input_xml` (required): input XML file path.
- `-o, --output PATH`: write output to a file. DOCX output requires this option (binary output cannot be previewed).
- `--preview`, `-v`: preview the result instead of printing to stdout:
  - **`web`** — open HTML in the default browser.
  - **`markdown`** — render with [Rich](https://rich.readthedocs.io/) in the terminal.
  - **Other channels** (e.g. `print`) — plain text in the terminal.
- `-p, --param KEY=VALUE`: set runtime parameters passed as XPath `$parameters` (repeatable).
- `--css PATH`: optional user stylesheet injected into `<head>` for full-document HTML output.
- `--template PATH`: dual-purpose template path:
  - For **HTML** output: path to a Jinja2 (`.j2`) template. If omitted, a packaged default template is used.
  - For **DOCX** output: path to a `.docx` file used as the Word style template. If omitted, falls back to `docx.template` in `opm.toml`, then the built-in default.
- `-x, --xpath EXPR`: XPath 3.1 expression; the selected element becomes the transform root instead of the whole document.
- `--xpath-extensions MODULE`: dotted import path of a Python module whose **public** callables are registered as XPath functions in the `tp:` namespace (repeatable).
- `--webcomponents / --no-webcomponents`: enable/disable tei-publisher web components mode. `alternate` behaviours emit `<pb-alternate>` and the document template loads `tei-publisher-components`. Falls back to `webcomponents.enabled` in `opm.toml`.
- `-c, --config PATH`: path to a TOML configuration file (default: `opm.toml` in the current directory).

Examples:

```bash
# Write modules/teipublisher-web.py (default path and mode)
uv run opm compile odd/teipublisher.odd

# Transform with runtime parameters
uv run opm transform modules/teipublisher-web.py input.xml \
  -p mode=toc -p display=browse -o output.html

# Preview markdown output in the terminal
uv run opm transform modules/teipublisher-markdown.py input.xml --preview

# Generate a DOCX using the built-in Word template
uv run opm transform modules/teipublisher-docx.py input.xml -o output.docx

# Generate a DOCX using a custom Word style template
uv run opm transform modules/teipublisher-docx.py input.xml \
  -o output.docx --template templates/my-styles.docx

# Preview HTML in the browser and also save to a file
uv run opm transform modules/teipublisher-web.py input.xml -o out.html --preview

# Use a custom Jinja2 template and stylesheet for HTML
uv run opm transform modules/teipublisher-web.py input.xml \
  --template templates/my-document.j2 --css styles/default-styles.css -o out.html
```

Notes:

- If you omit both `-o` and `--preview`, the serialized result is printed to stdout.
- With `--preview` alone, nothing is printed to stdout (only the preview).
- HTML template rendering and user CSS apply only when the transform returns a full document (`document` behaviour). Fragment output (e.g. with `--xpath`) is not wrapped.

### `opm chunk`

Chunk a large XML document into smaller HTML pages or JSON data files — useful for static site generators.

```bash
uv run opm chunk input.xml -o chunks/
```

Configuration is primarily read from the `[chunking]` section of `opm.toml` (see below). CLI options override config values.

Arguments and options:

- `input_xml` (required): XML file to transform and chunk.
- `-m, --module PATH`: path to a Python transform script. Falls back to `chunking.module` in config.
- `-o, --output-dir PATH`: directory to write chunked files (overrides `chunking.output_dir`).
- `-t, --template FILE`: Jinja2 template for chunk pages (overrides `chunking.template`).
- `-f, --force`: overwrite an existing output directory.
- `--webcomponents / --no-webcomponents`: enable/disable web components mode.
- `--xpath-extensions MODULE`: XPath extension module(s) (repeatable).
- `--format html|json`: output format — `html` (default, rendered via Jinja2) or `json` (one file per chunk with `content`, `head`, `odd_css`, and `fragments` keys, suitable for Eleventy and other static site generators).
- `-c, --config PATH`: TOML configuration file (default: `opm.toml`).

Examples:

```bash
# Chunk using settings from opm.toml
uv run opm chunk input.xml

# Override output directory, force overwrite
uv run opm chunk input.xml -o public/chunks --force

# Produce JSON data files for a static site generator
uv run opm chunk input.xml --format json -o _data/chunks
```

## DOCX Output

When `transform_output_channels()` returns `['docx']`, `opm transform` produces a `.docx` file (binary). The DOCX generator:

- Converts paragraphs, headings, inline styles, lists, links, and footnotes to OOXML.
- Injects missing built-in styles (`Hyperlink`, `footnote text`, `footnote reference`) when the template omits them.
- Accepts a custom Word `.docx` file as a style template via `--template` or the `[docx] template` config key — paragraph and character styles from that template are used in the generated document.

```bash
# Using a custom corporate Word template
uv run opm transform modules/teipublisher-docx.py input.xml \
  -o report.docx --template templates/corporate.docx
```

## Project Configuration (`opm.toml`)

Place an `opm.toml` file in the project root to set defaults that apply to all CLI commands. All sections are optional. You can also pass a different file with `-c` (e.g. `teipublisher.toml` for a project-specific setup).

```toml
[project]
# Additional Python paths (relative to the config file) for custom extensions
pythonpath = ["extensions"]

[transform]
# Default transform module (used when --module is omitted)
module = "modules/teipublisher-web.py"
# XPath extension modules loaded for every transform
xpath_extensions = ["extensions.my_functions"]

[docx]
# Default Word style template for DOCX output (overridable with --template)
template = "templates/corporate.docx"

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
# selector = "myextension.my_chunk_selector"
# Maximum heading depth for chunk splitting
depth = 2
# Output directory for chunk files
output_dir = "chunks"
# Jinja2 template for chunk pages
template = "templates/chunk.html.j2"
# URL pattern for cross-chunk links ({file}, {stem}, {anchor} placeholders)
link_pattern = "/{stem}/"
```
