# Quickstart

This walkthrough scaffolds a local project, transforms a sample document, and
builds a chunked static site. After [installation](installation.md), you only
need the `opm` CLI.

## 1. Create a project

```bash
opm init
# or: opm init --vocabulary docbook
```

That writes `opm.toml`, templates, CSS, an ODD, `AGENTS.md` / `CLAUDE.md`
(agent guidance; existing copies are left untouched), and `data/sample.xml`
(skip the sample with `--no-sample`). TEI is the default: `odd/custom.odd`
inherits the packaged `teipublisher` model. DocBook copies `odd/docbook.odd`
into the project.

## 2. Transform a document

ODDs are compiled on demand into the user cache (no separate compile step).
Preview HTML in the browser:

```bash
opm transform data/sample.xml --preview
```

The cache path is printed on stderr, for example:

```text
Compiled …/custom.odd → ~/Library/Caches/opm/modules/custom-web-….py
```

Write to a file instead of previewing:

```bash
opm transform data/sample.xml -o output.html
```

Other output channels via `--type` (compiles the ODD for that mode):

```bash
opm transform data/sample.xml -t markdown --preview
opm transform data/sample.xml -t typst -o output.typ
opm transform data/sample.xml -t docx -o output.docx
```

Pass runtime parameters (exposed to XPath as `$parameters`) with `-p`:

```bash
opm transform data/sample.xml -p mode=toc -p display=browse -o output.html
```

`$parameters?root` is bound automatically to the viewed node — see
[ODD files](../guide/odd-files.md#parametersroot).

## 3. Chunk a document for a static site

```bash
opm chunk data/sample.xml --force
```

Or emit JSON data files for a static site generator (Eleventy, Hugo, …):

```bash
opm chunk data/sample.xml --format json -o _data/chunks
```

Add `--preview` to chunk and serve in one step:

```bash
opm chunk data/sample.xml --force --preview
```

Or serve an existing output directory:

```bash
opm serve
```

Most options have defaults in `opm.toml` — see
[Configuration](../guide/configuration.md).
For driving these steps from Python instead of the CLI, see the
[transform API](../api/transform.md) and [chunking API](../api/chunking.md).

## From this repository

Developers working in the git clone can still use the demo tree without `opm init`:

```bash
uv run opm transform examples/tei-test.xml --preview
uv run opm transform examples/tei-test.xml \
  --preview --template templates/tufte.html.j2
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm chunk examples/tei-test.xml -o chunks/ --force --preview
```

Worked projects live under `examples/`. `uv run` still finds the repo package
from those directories, and `opm` loads the local `opm.toml`:

```bash
cd examples/serafin
uv run opm chunk data/letters/serafin01.xml --force --preview

cd ../docbook
uv run opm chunk data/doc/quickstart.xml --force --preview
```
