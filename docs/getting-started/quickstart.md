# Quickstart

This walkthrough scaffolds a local project, transforms a sample document, and
builds a chunked static site. After [installation](installation.md), you only
need the `opm` CLI.

## 1. Create a project

```bash
opm init
```

In a terminal that asks what to start from: an empty project for one of the
vocabularies, or a copy of one of the worked example projects. Both are also
reachable directly, which is what a script or a CI job wants:

```bash
opm init --vocabulary docbook     # empty project, no prompt
opm init --example jats           # copy of the JATS journal-article project
opm init --list-examples          # what is on offer
```

A run that is not attached to a terminal never prompts: it writes the empty TEI
project, as before.

An **empty project** writes `opm.toml`, templates, CSS, an ODD, `AGENTS.md` /
`CLAUDE.md` (agent guidance; existing copies are left untouched), and
`data/sample.xml`. TEI is the default: `odd/custom.odd` inherits the packaged
`teipublisher` model. DocBook and JATS copy `odd/docbook.odd` / `odd/jats.odd`
into the project.

An **example** is a complete project — ODD, templates, config and real source
documents — copied out of the package, with its own `README.md` describing what
it demonstrates. `.gitignore` and agent guidance are added; the generated
`chunks/` output is not copied.

| `--example` | Project |
| --- | --- |
| `jats` | Journal article: masthead, TOC rail, margin notes in print |
| `docbook` | Software handbook: section chunking, global TOC, breadcrumbs, print and EPUB |
| `serafin` | Correspondence: transcription and translation, with person/place registers |
| `shakespeare` | Shakespeare play: chunked by page rather than division, with IIIF facsimiles |

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
