# Installation

`opm` uses [`uv`](https://docs.astral.sh/uv/) as its package manager.

## Python version

The minimum supported Python version is **3.12**
(`pyproject.toml` → `requires-python = ">=3.12"`). `uv` does not force-upgrade
your system Python, but it can provision a compatible interpreter:

```bash
uv python install 3.12
```

## 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your shell (or source your profile) so `uv` is on `PATH`.

## 2. Install dependencies

From the project root:

```bash
uv sync
```

This creates `.venv` and installs the runtime dependencies. Optional dependency
groups:

```bash
uv sync --group dev     # pytest and other dev tools
uv sync --group docs    # mkdocs-material + mkdocstrings (this site)
```

## 3. Verify

```bash
uv run opm --help
uv run --group dev pytest -q
```

## Running tests

```bash
uv run --group dev pytest              # all tests
uv run --group dev pytest -v -x        # verbose, stop on first failure
uv run --group dev pytest tests/test_odd_compiler.py -q   # one file
```

## Building this documentation

```bash
uv run --group docs mkdocs serve       # live-reload at http://127.0.0.1:8000
uv run --group docs mkdocs build       # static site into ./site
```
