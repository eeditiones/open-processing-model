# Installation

The minimum supported Python version is **3.12**.

If you need help installing Python or are unsure of your Python version, go to [Troubleshooting](#troubleshooting) below.


## Users

Install the published package, then scaffold a project:

```bash
pip install open-processing-model
# or: uv add open-processing-model
opm init
```

`opm init` writes `opm.toml`, templates, a stub ODD, agent guidance
(`AGENTS.md`, `CLAUDE.md`), and a sample document into the current directory
(or a path you pass). Existing `AGENTS.md` / `CLAUDE.md` files are never
overwritten. Use `--vocabulary docbook` for a DocBook project.

On a terminal it first asks what to start from — an empty project, or a copy of
one of the worked examples that ship with the package (`opm init --list-examples`,
then `opm init --example jats`). See the [Quickstart](quickstart.md).

A one-off transform needs no project files: `opm transform my.xml --preview`
uses the packaged stock ODD, HTML/Typst templates, CSS, and Word style template.

### Troubleshooting

#### Installing Python

The quickest way to check the Python version on a system is via the command line or terminal.

* open your command line interface (type `cmd` in the Windows search bar or open terminal on macOS/Linux)
* type `python --version` and press Enter (or `python3 --version` if you get a `command not found` error)
* if you see a version number higher than **3.12** you can directly install the package.

If you need to install or upgrade Python, go to [python.org](https://www.python.org/)’s Download page, select the pertinent installer for your operating system, download it and run it. During installation, make sure to check the box that says *Add Python to PATH* so you can run Python from the command line. 

To verify the installation, follow the steps above to check the installed version.

#### Installing the package

If `pip install open-processing-model` returns an error similar to `command not found`, it usually means `pip` isn’t added to your system's PATH variable. Use `python3 -m pip install open-processing-model` (macOS/Linux) or `py -m pip install open-processing-model` (in Windows).

## Contributors

This repository uses [`uv`](https://docs.astral.sh/uv/) as its package manager.
`uv` does not force-upgrade your system Python, but it can provision a
compatible interpreter:

```bash
uv python install 3.12
```

### 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your shell (or source your profile) so `uv` is on `PATH`.

### 2. Install dependencies

From the project root:

```bash
uv sync
```

This creates `.venv` and installs the runtime dependencies. Optional dependency
groups:

```bash
uv sync --group dev     # pytest and other dev tools
uv sync --group docs    # zensical + mkdocstrings (this site)
```

### 3. Verify

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
uv run python scripts/gen_cli_docs.py  # refresh CLI reference from the Typer app
uv run --group docs zensical serve     # live-reload at http://127.0.0.1:8000
uv run --group docs zensical build     # static site into ./site
```
