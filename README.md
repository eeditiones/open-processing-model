<p align="center">
  <img src="docs/assets/logo-wordmark.svg#gh-light-mode-only" alt="opm — Open Processing Model" width="380">
  <img src="docs/assets/logo-wordmark-dark.svg#gh-dark-mode-only" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) implements the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) for transforming XML into various output formats. The design conceptually follows the [`tei-publisher-lib`](https://github.com/eeditiones/tei-publisher-lib) implementation in [TEI Publisher](https://tei-publisher.org) and aims to be as compatible as possible. While `tei-publisher-lib` compiles the processing model instructions found in an ODD into XQuery code, `opm` outputs Python instead.

`opm` does not require a database, runs entirely on the command line, is very fast for batch processing and has very slim dependencies.

## Quick start

Python ≥ 3.12. Install the package, then scaffold a project:

```bash
pip install open-processing-model
# or: uv add open-processing-model

opm init                          # asks: empty project, or one of the examples
# opm init --vocabulary docbook   # empty DocBook project, no prompt
# opm init --example jats         # copy of a worked example project

opm transform data/sample.xml --preview
opm chunk data/sample.xml --force
opm serve
```

A one-off transform needs no project files (`opm transform my.xml --preview`
uses the packaged stock ODD and templates). `opm init` writes editable
`opm.toml`, templates, CSS, and an ODD — or, with `--example`, copies one of the
worked projects under [`examples/`](examples) (`--list-examples` shows them).

## Development

This repository uses [`uv`](https://docs.astral.sh/uv/). From a clone:

```bash
uv sync

uv run opm transform examples/tei-test.xml --preview
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm chunk examples/tei-test.xml -o chunks/ --force
uv run opm serve -d chunks/

# Worked projects (run from the example directory):
cd examples/serafin && uv run opm chunk data/letters/serafin01.xml --force --preview
cd examples/docbook && uv run opm chunk data/doc/quickstart.xml --force --preview
cd examples/jats && uv run opm chunk data/article/hertziana-digital-editions.xml --force --preview
```

### `opm` without `uv run`

To get `opm` on your `PATH` while still running the working tree, install the
clone as an editable tool:

```bash
uv tool install --editable . --force
```

Code changes are picked up straight away — the tool venv links to `src/`, so
there is nothing to re-sync after an edit. **Dependency changes are not**: when
`[project] dependencies` in `pyproject.toml` gains an entry, run the same
command again, or the installed `opm` keeps the dependency set it was resolved
with and fails on the new import.

Note that `.venv/bin/opm` shadows the tool whenever the project venv is on
`PATH`; `which -a opm` shows which one you are about to run.

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

## Supporters

Development of `opm` is supported by:

<p align="center">
  <a href="https://www.ernst-goehner-stiftung.ch/"><img src="docs/assets/EGS_Logo_Standard_RGB.svg#gh-light-mode-only" alt="Ernst Göhner Stiftung" height="40"><img src="docs/assets/EGS_Logo_Standard_RGB_white.svg#gh-dark-mode-only" alt="Ernst Göhner Stiftung" height="40"></a>
  &nbsp;&nbsp;&nbsp;
  <a href="https://www.sagw.ch/"><img src="docs/assets/SAGW_Logo_addition_supported_pos.svg#gh-light-mode-only" alt="Swiss Academy of Humanities and Social Sciences" height="54"><img src="docs/assets/SAGW_Logo_addition_supported_pos_white.svg#gh-dark-mode-only" alt="Swiss Academy of Humanities and Social Sciences" height="54"></a>
  &nbsp;&nbsp;&nbsp;
  <a href="https://www.zb.uzh.ch/"><img src="docs/assets/ZB_Logo_RGB_1024px.png" alt="Zentralbibliothek Zürich" height="50"></a>
  &nbsp;&nbsp;&nbsp;
  <a href="https://theologie.unibas.ch/de/karl-barth-zentrum/"><img src="docs/assets/karl-barth.png#gh-light-mode-only" alt="Karl Barth-Stiftung" height="40"><img src="docs/assets/karl-barth-white.png#gh-dark-mode-only" alt="Karl Barth-Stiftung" height="40"></a>
  &nbsp;&nbsp;&nbsp;
  <a href="https://www.zde.uzh.ch/"><img src="docs/assets/uzh-logo-black.png#gh-light-mode-only" alt="Universität Zürich" height="40"><img src="docs/assets/uzh-logo-white.png#gh-dark-mode-only" alt="Universität Zürich" height="40"></a>
</p>

<p align="center">
  <sub>
    Ernst Göhner Stiftung &nbsp;·&nbsp; SAGW &nbsp;·&nbsp; Zentralbibliothek Zürich &nbsp;·&nbsp;
    Karl Barth-Stiftung &nbsp;·&nbsp; UZH, Zentrum Digitale Editionen &amp; Editionsanalytik
  </sub>
</p>

### An initiative of

<p>
  <a href="https://e-editiones.org/">
    <img src="docs/assets/e-editiones-logo-color.svg#gh-light-mode-only" alt="e-editiones" height="40">
    <img src="docs/assets/e-editiones-logo-white.svg#gh-dark-mode-only" alt="e-editiones" height="40">
  </a>
</p>
