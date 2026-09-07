# CLI Reference

The `opm` command is a [Typer](https://typer.tiangolo.com/) application. This page is generated from `opm.cli` by `scripts/gen_cli_docs.py`. Run `opm --help` (or `opm <command> --help`) for the same information in your terminal.

## `opm`

Open Processing Model: transform XML via ODD processing models (ODDs compile on demand into the user cache).

**Usage:**

```text
opm [OPTIONS] COMMAND [ARGS]...
```

**Options:**

| Option | Description |
| --- | --- |
| `--install-completion` | Install completion for the current shell. |
| `--show-completion` | Show completion for the current shell, to copy it or customize the installation. |
| `--help` | Show this message and exit. |


**Commands:**

- [`init`](#opm-init): Create a local project: an empty one, or a...
- [`transform`](#opm-transform): Transform an XML document via an ODD with...
- [`chunk`](#opm-chunk): Chunk a large XML document into smaller...
- [`index`](#opm-index): Emit embedding-ready JSONL records for a...
- [`coverage`](#opm-coverage): Diagnose an ODD against a corpus: what...
- [`serve`](#opm-serve): Start a local HTTP server rooted at the...

### `opm init`

Create a local project: an empty one, or a copy of a bundled example.

**Usage:**

```text
opm init [OPTIONS] [DIRECTORY]
```

**Arguments:**

| Argument | Description |
| --- | --- |
| `DIRECTORY` | Project directory (default: current directory). |


**Options:**

| Option | Description |
| --- | --- |
| `--force` | Overwrite existing generated files. |
| `--vocabulary TEXT` | Empty project for this vocabulary: tei, docbook, jats (default: tei). |
| `--example, -e TEXT` | Start from a bundled example project instead of an empty one: jats, docbook, serafin, shakespeare. |
| `--list-examples` | List the bundled example projects and exit. |
| `--copy-base-odd` | TEI only: also copy packaged teipublisher.odd and tp.css into odd/. |
| `--title TEXT` | Edition title used in README (default: directory name). |
| `--help` | Show this message and exit. |

### `opm transform`

Transform an XML document via an ODD with processing instructions and return the result (HTML, markdown, …).

**Usage:**

```text
opm transform [OPTIONS] [INPUT_XML]
```

**Arguments:**

| Argument | Description |
| --- | --- |
| `INPUT_XML` | Input XML file |


**Options:**

| Option | Description |
| --- | --- |
| `--odd, -d PATH` | ODD file to compile on demand into the user cache. Overrides transform.<type>.odd in config. |
| `--type, -t TYPE` | Transform type / ODD output channel (web, docx, typst, markdown, …). Selects transform.<type>.odd from config when --odd is omitted; also sets the compile mode for --odd. |
| `--channel CHANNEL` | With -t json only: which ODD output channel to record decisions for (web, print, epub, markdown, docx, typst). Default: web. |
| `--output, -o PATH` | Write transform output to this file (default: stdout unless --preview) |
| `--preview, -v` | Preview output: channel web/print → browser, markdown → Rich (paged in a TTY so bold/italic survive), docx/epub → the platform default application; other channels (e.g. typst) → plain text in the terminal. |
| `--param, -p KEY=VALUE` | Runtime parameter for XPath $parameters (repeatable), e.g. -p mode=toc -p display=browse |
| `--css PATH` | Optional external CSS file injected into <head> for full-document HTML output. |
| `--template PATH` | Template path: Jinja2 for HTML/print/Typst output, or .docx for DOCX output. |
| `--xpath, -x EXPR` | XPath 3.1 expression evaluated with the document root as the context item; the single selected element becomes the transform root. Unprefixed names use the same default element namespace as the document root. $parameters is bound from --param. |
| `--xpath-extensions TEXT` | Dotted import path(s) of Python module(s) whose public callables become XPath functions in the tp: namespace (repeat option to add modules; e.g. --xpath-extensions extensions.common --xpath-extensions extensions.dates). Importing these modules runs top-level code: only use trusted code. |
| `--webcomponents, --no-webcomponents` | Enable/disable tei-publisher web components mode: alternate behaviours emit <pb-alternate> and the document template loads tei-publisher-components. Falls back to transform.web.webcomponents.enabled in the project config. |
| `--config, -c PATH` | Path to a TOML configuration file (default: opm.toml in the current directory). |
| `--help` | Show this message and exit. |

### `opm chunk`

Chunk a large XML document into smaller HTML pages or JSON data files.

**Usage:**

```text
opm chunk [OPTIONS] [INPUT_XML]
```

**Arguments:**

| Argument | Description |
| --- | --- |
| `INPUT_XML` | XML file to transform and chunk, or a directory of XML files. |


**Options:**

| Option | Description |
| --- | --- |
| `--odd, -d PATH` | ODD file to compile on demand for chunking (overrides chunking.odd in config). |
| `--output-dir, -o PATH` | Directory to write chunked files (overrides chunking.output_dir in config). |
| `--template, -t FILE` | Jinja2 template for chunk pages (overrides chunking.template in config). |
| `--force, -f` | Remove the existing output directory without prompting. |
| `--depth INTEGER` | Maximum division/section depth for chunk splitting (overrides chunking.depth in config). |
| `--webcomponents, --no-webcomponents` | Enable/disable tei-publisher web components mode. Falls back to transform.web.webcomponents.enabled in the project config. |
| `--xpath-extensions TEXT` | Dotted import path(s) of Python module(s) whose public callables become XPath functions in the tp: namespace (repeatable). Falls back to transform.xpath_extensions in opm.toml. |
| `--format TEXT` | Output format for chunk files: "html" (default, rendered via Jinja2 template), "json" (one JSON file per chunk containing content, head, odd_css, and fragments — suitable for static site generators such as Eleventy), or "pb-view" (index.json lookup table plus one part file per chunk, consumable by the dynamic pb-view web component in static mode). |
| `--doc-path TEXT` | For --format pb-view: document path subdirectory. Data is written to <output-dir>/<doc-path>/ and must match the pb-document @path; CSS stays shared at <output-dir>/css/. Falls back to chunking.doc_path in config. |
| `--preview, -v` | After chunking, start a local HTTP server rooted at the output directory and open the first page in a browser (HTML output only). |
| `--port, -p INTEGER` | Port for --preview (default: 8080). |
| `--config, -c PATH` | Path to a TOML configuration file (default: opm.toml in the current directory). |
| `--help` | Show this message and exit. |

### `opm index`

Emit embedding-ready JSONL records for a search index or vector store.

Records come from the processing model, not the raw source, so the ODD's
editorial decisions carry into the index: omitted apparatus stays out, and
``alternate`` contributes the reading the page displays.

**Usage:**

```text
opm index [OPTIONS] [INPUT_XML]
```

**Arguments:**

| Argument | Description |
| --- | --- |
| `INPUT_XML` | XML file to index, or a directory of XML files (searched recursively). Defaults to ./data when it exists. |


**Options:**

| Option | Description |
| --- | --- |
| `--odd, -d PATH` | ODD file to compile on demand (overrides transform.json.odd in config). |
| `--output, -o PATH` | JSONL file to write (default: stdout). |
| `--max-chars INTEGER` | Split a section longer than this at record boundaries. Falls back to index.max_chars in opm.toml (default: 1500). |
| `--min-chars INTEGER` | Drop units shorter than this — bare headings are retrieval noise. Falls back to index.min_chars in opm.toml (default: 40). |
| `--overlap INTEGER` | Records of context carried into the next part when a unit splits. Falls back to index.overlap in opm.toml (default: 1). |
| `--config, -c PATH` | Path to a TOML configuration file (default: opm.toml in the current directory). |
| `--help` | Show this message and exit. |

### `opm coverage`

Diagnose an ODD against a corpus: what never runs, and what is never handled.

Reports the models and elementSpecs you wrote that no document exercised,
models that can never fire at all, elements no model matched, and elements
whose spec exists but whose predicates were all false. Models inherited from
an extended ODD are counted separately — a local elementSpec replaces the
inherited one wholesale, so they are not yours to change.

Coverage transforms whole documents; chunking config is ignored.

**Usage:**

```text
opm coverage [OPTIONS] [INPUT_XML]
```

**Arguments:**

| Argument | Description |
| --- | --- |
| `INPUT_XML` | XML file or directory of XML files to measure the ODD against. Defaults to ./data when it exists. |


**Options:**

| Option | Description |
| --- | --- |
| `--odd, -d PATH` | ODD file to compile on demand (overrides transform.json.odd in config). |
| `--channel CHANNEL` | ODD output channel to report on (web, print, epub, markdown, docx, typst). Default: web. |
| `--param, -p TEXT` | Transform parameter KEY=VALUE (repeatable), as for opm transform. |
| `--all, -a` | List every finding instead of the first 20 per section. |
| `--json` | Print the whole report as JSON instead of tables. |
| `--config, -c PATH` | Path to opm.toml. |
| `--help` | Show this message and exit. |

### `opm serve`

Start a local HTTP server rooted at the chunks output directory.

**Usage:**

```text
opm serve [OPTIONS]
```

**Options:**

| Option | Description |
| --- | --- |
| `--port, -p INTEGER` | Port to listen on (default: 8080). |
| `--directory, -d PATH` | Directory to serve (default: chunking.output_dir from config, or "chunks"). |
| `--config, -c PATH` | Path to a TOML configuration file (default: opm.toml in the current directory). |
| `--help` | Show this message and exit. |
