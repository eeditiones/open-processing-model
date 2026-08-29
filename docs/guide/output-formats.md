# Output formats

A single ODD drives every output format. The format is chosen at **compile**
time via `--type` / `-t` (or the matching config table), which selects the ODD
`@output` channel and the concrete
[`ProcessingModelFunctions`](../api/output-functions.md) implementation used to
emit output.

| Mode | Output | Implementation |
| --- | --- | --- |
| `web` (default) | HTML5 | `HtmlOutputFunctions` |
| `print` | HTML for paged-media CSS | `PrintOutputFunctions` (extends HTML) |
| `markdown` | Markdown | `MarkdownOutputFunctions` |
| `docx` | Word `.docx` (binary) | `DocxOutputFunctions` |
| `typst` | Typst markup | `TypstOutputFunctions` |

`print` (and later `epub`) also accept ODD models tagged `@output="web"`, matching
tei-publisher-lib’s `output: ["print", "web"]` fallback. Models without `@output`
still apply to every mode.

Models may use an optional `opm-` prefix on `@output` (e.g. `opm-web`) for rules
that apply only when compiling with this Python implementation. tei-publisher-lib
ignores those models. Among models that match the compile mode, the usual ODD
rule applies: the first whose conditions apply wins.

```bash
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t markdown --preview
uv run opm transform examples/tei-test.xml -t docx -o out.docx
uv run opm transform examples/tei-test.xml -t typst -o out.typ
```

Each compile writes (or reuses) a cached module under the user cache directory;
the path is printed on stderr.

## Choosing an ODD at transform time

Pass an ODD with `--odd`/`-d`, or select from your TOML config with `--type`/`-t`
(and `-c` if the config is not `opm.toml`):

| `--type` | Config key (override) | Falls back to |
| --- | --- | --- |
| `web` | `[transform.web].odd` | `[transform].odd` |
| `print` | `[transform.print].odd` | `[transform].odd` |
| `docx` | `[transform.docx].odd` | `[transform].odd` |
| `typst` | `[transform.typst].odd` | `[transform].odd` |
| `markdown`, … | `[transform.<type>].odd` | `[transform].odd` |

```bash
# Explicit ODD (compiled on demand)
uv run opm transform examples/tei-test.xml --preview

# Looked up from config (see Configuration)
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t typst -o out.typ
uv run opm transform examples/tei-test.xml -t docx -o out.docx
```

`--odd`/`-d` overrides config lookup. Omitting both falls back to
`[transform.<type>].odd`, then `[transform].odd`, then the packaged stock
teipublisher ODD. Details are in
[Configuration](configuration.md#selecting-an-odd-by-type).

## HTML (`web`)

Full-document output is wrapped in a Jinja2 template and can include
ODD-generated CSS, a user stylesheet, and optional tei-publisher web components.
See [Templates & CSS](templates-and-css.md).

```bash
uv run opm transform data/sample.xml \
  --preview --template templates/tufte.html.j2
```

## Print (paged media)

`print` emits HTML like `web`, but notes and alternates are inline
`<span class="footnote">` / `margin-note` spans so CSS paged media can
`float: footnote` (Prince, Paged.js, browser print). Interactive callouts and
web components are disabled. ODD models with `@output="print"` apply in addition
to `@output="web"` and unscoped models.

The Jinja shell is separate from the web reading view. Resolution:

1. `--template` / `-t` override
2. `[transform.print] template`
3. Packaged `default_print.html.j2` (minimal; **not** the web `[document] template`)

Paged layout itself comes from the ODD’s CSS (often `@page` / `@media print` in
a tagsDecl stylesheet). OPM only produces the markup; PDF rendering is external.

```bash
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t print -o print.html
```

The DocBook example wires a dedicated shell:

```bash
cd examples/docbook
uv run opm transform data/doc/quickstart.xml -t print --preview
```

See `examples/docbook/templates/print.html.j2` and `[transform.print]` in that
project’s `opm.toml`.

## Markdown

```bash
uv run opm transform examples/tei-test.xml -t markdown --preview
```

`--preview` renders the Markdown in the terminal with
[Rich](https://rich.readthedocs.io/).

## DOCX

DOCX is binary, so `-o` is required (it cannot be previewed). A custom Word
`.docx` can be supplied as a **style template** via `--template` or the
`[transform.docx] template` config key; its paragraph and character styles are reused in
the output. If none is given, the packaged `default.docx` is used (the same file
`opm init` copies into `templates/`). Missing built-in styles (`Hyperlink`,
`footnote text`, `footnote reference`) are injected automatically.

```bash
uv run opm transform examples/tei-test.xml -t docx -o report.docx \
  --template templates/corporate.docx
# Or: -t docx -o report.docx
```

## Typst

Typst output uses a `.typ.j2` Jinja2 template configured under `[transform.typst]`.
Project templates include `templates/book.typ.j2` (TEI) and
`templates/docbook.typ.j2` (DocBook UI classes); both use ilm. The packaged
fallback is `default_document.typ.j2`.

```bash
uv run opm transform examples/tei-test.xml -t typst -o out.typ
```

## Adding a new format

Subclass [`ProcessingModelFunctions`](../api/output-functions.md) and implement
its behaviour methods. Because the generated transform code is format-agnostic,
the same compiled module works with any implementation you provide. Modes that
extend HTML (like `print`) typically subclass `HtmlOutputFunctions` and override
only the behaviours that differ.
