# tei-publisher-py

This project exposes one CLI entry point: `teipublisher`.

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
uv run teipublisher --help
uv run --group dev pytest -q
```

### 4) Typical first run

```bash
# Generate transform module from ODD
uv run teipublisher compile odd/teipublisher.odd -o teipublisher_web.py

# Apply transform to an XML file
uv run teipublisher transform teipublisher_web.py input.xml -o output.html
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

Use `uv run teipublisher --help` to see global help.

### `teipublisher compile`

Compile an ODD file into a Python transform module.

```bash
uv run teipublisher compile odd/teipublisher.odd -o teipublisher_web.py
```

Arguments and options:

- `odd` (required): path to the `.odd` file.
- `-o, --output`: write generated Python to this path (default: `transform/<odd-basename>-<mode>.py` under the current working directory).
- `-m, --mode`: ODD processing-model output channel — `web` (HTML via `html_output_functions`), `markdown` (via `markdown_output_functions`), or other `@output` values such as `print` (default: `web`).
- `--module-name`: logical module name used in generated docstring (default: `generated_odd`).

### `teipublisher transform`

Load a generated transform module and apply it to an XML file.

```bash
uv run teipublisher transform teipublisher_web.py input.xml -o output.html
```

The transform module must define:

- `transform(root, options=None)` — run the processing model.
- `transform_output_channels()` — return the same channel list as in the generated `transform()` config (e.g. `['web']`, `['markdown']`). Modules emitted by `teipublisher compile` include this automatically.

Arguments and options:

- `transform_script` (required): path to the Python module (see above).
- `input_xml` (required): input XML file path.
- `-o, --output`: write serialized output to a file. If you also pass `--preview`, the file is written and then previewed.
- `--preview`, `-v`: preview the result instead of printing it to stdout. How preview works depends on the first channel from `transform_output_channels()`:
  - **`web`** — open the serialized HTML in the default browser (via a temporary file).
  - **`markdown`** — render with [Rich](https://rich.readthedocs.io/) as Markdown in the terminal.
  - **Other channels** (e.g. `print`) — print plain text in the terminal with Rich.
- `-p, --param KEY=VALUE`: set runtime parameters passed as XPath `$parameters` (repeatable).
- `-x, --xpath EXPR`: XPath 3.1 expression with the document root as context; the single selected element becomes the transform root (instead of the whole document). Unprefixed names use the document’s default element namespace.

Examples:

```bash
# Write transform/teipublisher-web.py (default path and mode)
uv run teipublisher compile odd/teipublisher.odd

# Transform with runtime parameters
uv run teipublisher transform teipublisher_web.py input.xml \
  -p mode=toc -p display=browse -o output.html

# Preview markdown output in the terminal (no stdout dump)
uv run teipublisher transform transform/teipublisher-markdown.py input.xml --preview

# Preview HTML in the browser and also save to a file
uv run teipublisher transform transform/teipublisher-web.py input.xml -o out.html --preview
```

Notes:

- If you omit both `-o` and `--preview`, the serialized result is printed to stdout.
- With `--preview` alone, nothing is printed to stdout (only the preview).
