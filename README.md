<p align="center">
  <img src="docs/assets/logo-wordmark.svg#gh-light-mode-only" alt="opm — Open Processing Model" width="380">
  <img src="docs/assets/logo-wordmark-dark.svg#gh-dark-mode-only" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) implements the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) for transforming XML into various output formats. The implementation is a Python port of the core library of TEI Publisher: [`tei-publisher-lib`](https://github.com/eeditiones/tei-publisher-lib). While `tei-publisher-lib` compiles the processing model instructions found in an ODD into XQuery code, `opm` outputs Python instead.

`opm` does not require a database, runs entirely on the command line, is very fast for batch processing and has very slim dependencies.

## Quick start

Python ≥ 3.12. Install the package, then scaffold a project:

```bash
pip install open-processing-model
# or: uv add open-processing-model

opm init                          # TEI project in the current directory
# opm init --vocabulary docbook   # DocBook instead

opm transform data/sample.xml --preview
opm chunk data/sample.xml --force
opm serve
```

A one-off transform needs no project files (`opm transform my.xml --preview`
uses the packaged stock ODD and templates). `opm init` writes editable
`opm.toml`, templates, CSS, and an ODD.

## Contributors

This repository uses [`uv`](https://docs.astral.sh/uv/). From a clone:

```bash
uv sync

uv run opm transform demo/tei-test.xml --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm chunk demo/tei-test.xml -c teipublisher.toml -o chunks/ --force
uv run opm serve -d chunks/
```

## Tests

```bash
uv sync --group dev
uv run --group dev pytest                            # all tests
uv run --group dev pytest tests/test_odd_compiler.py # single file
```

## Documentation

The docs site is built with [Zensical](https://zensical.org/) (successor to
Material for MkDocs, plus mkdocstrings). To preview locally:

```bash
uv sync --group docs
uv run python scripts/gen_cli_docs.py                # refresh CLI reference from the Typer app
uv run --group docs zensical serve                   # http://127.0.0.1:8000
uv run --group docs zensical build                   # static site into ./site
```
