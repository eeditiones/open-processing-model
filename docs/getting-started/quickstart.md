# Quickstart

This walkthrough scaffolds a local project, transforms a sample document, and
builds a chunked static site. After [installation](installation.md), you only
need the `opm` command-line interface.

> **Note:** If you cloned the repository, you'll find all example projects directly in the `/examples/` folder, so you can skip the scaffolding step. See the section [below](#running-from-the-repository).

## 1. Create a project

You might want to start by creating the directory where you want to store the project files, then open the terminal, go to that directory (`cd`) and run:

```bash
opm init
```
or pass the path as an argument: `opm init PATH`

Without additional arguments you'll be prompted to select the type of project: either an empty project for one of the
supported vocabularies, or a copy of one of the example projects. You can bypass interactive mode and directly create the type of project you want. E.g.:

```bash
opm init --vocabulary docbook        # empty project for a specific vocabulary
opm init --example jats              # copy of the JATS journal-article project
opm init --example jats --templates  # include all available templates into `/templates/`
opm init --list-examples             # list all available worked projects
```

An **empty project** writes a configuration file (`opm.toml`), templating and CSS files (`/templates/`), an ODD (`/odd/`), sample data (`/data/sample.xml`), agent guidance (`AGENTS.md` and `CLAUDE.md`; existing copies are left untouched) and  `.gitignore`. The ODD will depend on the selected vocabulary, TEI being the default one, and it .

An **example** is a complete project — ODD, templates, config and real source
documents — copied out of the package, with its own `README.md` describing what
it demonstrates,`.gitignore` and agent guidance.

| `--example` | Project |
| --- | --- |
| `jats` | Journal article: masthead, TOC rail, margin notes in print |
| `docbook` | Software handbook: section chunking, global TOC, breadcrumbs, PDF print and EPUB |
| `serafin` | Correspondence (TEI): transcription and translation, with person/place registers |
| `shakespeare` | Shakespeare play (TEI): chunked by page rather than division, with IIIF facsimiles |

The client distinguishes two modes of processing: `transform` and `chunk`.

* `transform` is meant to transform a single input file into a single output. It's mainly used for generating a quick HTML preview or
for media formats not targetting the web, like PDF, epub or markdown.
* `chunk` can process entire collections of document. It also paginates large documents into smaller units and provides different formats
for the generated output. In the simplest case, `chunk` can be used to generate a simple static website for your data.

## 2. Transform a document

ODDs are compiled on demand into the user cache. To preview the HTML transformation in the browser:

```bash
opm transform data/sample.xml --preview
```

To write to a file instead of previewing:

```bash
opm transform data/sample.xml -o output.html
```

Other output formats can be specified with the `--type` flag:

```bash
opm transform data/sample.xml -t markdown --preview
opm transform data/sample.xml -t typst -o output.typ
opm transform data/sample.xml -t docx -o output.docx
```

Parameters (exposed to XPath in the ODD as `$parameters`) can be passed with the `-p` flag:

```bash
opm transform data/sample.xml -p mode=toc -p display=browse -o output.html
```

See this 
[ODD files](../guide/odd-files.md#parameters)’s section to learn more about parameters.

## 3. Chunk a document for a static site

To divide a document in chunks, that is, in semantically structured divisions
that can be used for creating a static edition that you can navigate by chapter, poem, etc., run:

```bash
opm chunk data/sample.xml --force
```

To create JSON data files for a static site generator (e.g. Eleventy, Hugo):

```bash
opm chunk data/sample.xml --format json -o output/chunks
```

Add `--preview` to chunk and serve in one step (this will create a `chunks` folder and then serve it)

```bash
opm chunk data/sample.xml --force --preview
```

You can also serve an existing output directory with:

```bash
opm serve
```

Most options have defaults in `opm.toml` — see
[Configuration](../guide/configuration.md).
For driving these steps from Python instead of the CLI, see the
[Project API](../api/project.md).

## Running from the repository

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