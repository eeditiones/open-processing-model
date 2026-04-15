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
- `-o, --output`: write generated Python to this path (default: `<odd-basename>-<mode>.py` in the current working directory).
- `-m, --mode`: ODD processing-model output channel (default: `web`).
- `--module-name`: logical module name used in generated docstring (default: `generated_odd`).

### `teipublisher transform`

Load a generated transform module and apply it to an XML file.

```bash
uv run teipublisher transform teipublisher_web.py input.xml -o output.html
```

Arguments and options:

- `transform_script` (required): path to a Python module that defines `transform(root, options=None)`.
- `input` (required): input XML file path.
- `-o, --output`: write HTML output to a file (default: stdout).
- `-p, --param KEY=VALUE`: set runtime parameters passed as XPath `$parameters` (repeatable).

Examples:

```bash
# Write odd/teipublisher-web.py (default path and mode)
uv run teipublisher compile odd/teipublisher.odd

# Transform with runtime parameters
uv run teipublisher transform teipublisher_web.py input.xml \
  -p mode=toc -p display=browse -o output.html
```

Notes:

- If you omit `-o`, HTML is printed to stdout after that parameters line.
