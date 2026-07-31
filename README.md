<p align="center">
  <img src="docs/assets/logo-wordmark.svg#gh-light-mode-only" alt="opm — Open Processing Model" width="380">
  <img src="docs/assets/logo-wordmark-dark.svg#gh-dark-mode-only" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) implements the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) for transforming XML into various output formats. The implementation is a Python port of the core library of TEI Publisher: [`tei-publisher-lib`](https://github.com/eeditiones/tei-publisher-lib). While `tei-publisher-lib` compiles the processing model instructions found in an ODD into XQuery code, `opm` outputs Python instead.

`opm` does not require a database, runs entirely on the command line, is very fast for batch processing and has very slim dependencies.

## Quick start

`opm` uses [`uv`](https://docs.astral.sh/uv/) (Python ≥ 3.12). Install `uv`, then:

```bash
uv sync                                              # install dependencies

# Compile an ODD into a transform module
uv run opm compile odd/teipublisher.odd             # → modules/teipublisher-web.py

# Transform a document — HTML preview in the browser
uv run opm transform demo/tei-test.xml -m modules/teipublisher-web.py \
  --preview --template templates/tufte.html.j2

# Or pick the module from TOML with --type (web / docx / typst / …)
# uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview

# Chunk a large document into pages for a static site
uv run opm chunk demo/tei-test.xml -o chunks/ --force
uv run opm serve -d chunks/
```

## Tests

```bash
uv sync --group dev
uv run --group dev pytest                            # all tests
uv run --group dev pytest tests/test_odd_compiler.py # single file
```

## Documentation

The docs site is built with [MkDocs](https://www.mkdocs.org/) (Material theme +
mkdocstrings). To preview locally:

```bash
uv sync --group docs
uv run --group docs mkdocs serve                     # http://127.0.0.1:8000
uv run --group docs mkdocs build                     # static site into ./site
```
