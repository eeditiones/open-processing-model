# Output formats

A single ODD drives every output format. The format is chosen at **compile**
time with `--mode`, which selects the ODD `@output` channel and the concrete
[`ProcessingModelFunctions`](../api/output-functions.md) implementation used to
emit output.

| Mode | Output | Implementation |
| --- | --- | --- |
| `web` (default) | HTML5 | `HtmlOutputFunctions` |
| `markdown` | Markdown | `MarkdownOutputFunctions` |
| `docx` | Word `.docx` (binary) | `DocxOutputFunctions` |
| `typst` | Typst markup | `TypstOutputFunctions` |
| `print`, … | any `@output` value in the ODD | — |

Models may use an optional `opm-` prefix on `@output` (e.g. `opm-web`) for rules
that apply only when compiling with this Python implementation. tei-publisher-lib
ignores those models. Among models that match the compile mode, the usual ODD
rule applies: the first whose conditions apply wins.

```bash
uv run opm compile odd/teipublisher.odd --mode web        # → modules/teipublisher-web.py
uv run opm compile odd/teipublisher.odd --mode markdown   # → modules/teipublisher-markdown.py
uv run opm compile odd/teipublisher.odd --mode docx       # → modules/teipublisher-docx.py
uv run opm compile odd/teipublisher.odd --mode typst      # → modules/teipublisher-typst.py
```

The generated module records its channel via `transform_output_channels()`, so
`opm transform` knows how to handle the result.

## HTML (`web`)

Full-document output is wrapped in a Jinja2 template and can include
ODD-generated CSS, a user stylesheet, and optional tei-publisher web components.
See [Templates & CSS](templates-and-css.md).

```bash
uv run opm transform modules/teipublisher-web.py demo/tei-test.xml \
  --preview --template templates/tufte.html.j2
```

## Markdown

```bash
uv run opm transform modules/teipublisher-markdown.py demo/tei-test.xml --preview
```

`--preview` renders the Markdown in the terminal with
[Rich](https://rich.readthedocs.io/).

## DOCX

DOCX is binary, so `-o` is required (it cannot be previewed). A custom Word
`.docx` can be supplied as a **style template** via `--template` or the
`[docx] template` config key; its paragraph and character styles are reused in
the output. Missing built-in styles (`Hyperlink`, `footnote text`,
`footnote reference`) are injected automatically.

```bash
uv run opm transform modules/teipublisher-docx.py demo/tei-test.xml -o report.docx \
  --template templates/corporate.docx
```

## Typst

Typst output uses a `.typ.j2` Jinja2 template (e.g. a `book` or `documentation`
layout), configured under `[typst]` in `opm.toml`.

## Adding a new format

Subclass [`ProcessingModelFunctions`](../api/output-functions.md) and implement
its behaviour methods. Because the generated transform code is format-agnostic,
the same compiled module works with any implementation you provide.
