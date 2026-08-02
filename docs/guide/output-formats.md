# Output formats

A single ODD drives every output format. The format is chosen at **compile**
time via `--type` / `-t` (or the matching config table), which selects the ODD
`@output` channel and the concrete
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
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t web --preview
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t markdown --preview
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t docx -o out.docx
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t typst -o out.typ
```

Each compile writes (or reuses) a cached module under the user cache directory;
the path is printed on stderr.

## Choosing an ODD at transform time

Pass an ODD with `--odd`/`-d`, or select from your TOML config with `--type`/`-t`
(and `-c` if the config is not `opm.toml`):

| `--type` | Config key |
| --- | --- |
| `web` | `[transform.web].odd` |
| `docx` | `[transform.docx].odd` |
| `typst` | `[transform.typst].odd` |
| `markdown`, `print`, … | `[transform.<type>].odd` |

```bash
# Explicit ODD (compiled on demand)
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd --preview

# Looked up from config (see Configuration)
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t typst -o out.typ
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t docx -o out.docx
```

`--odd`/`-d` overrides `--type` config lookup. Omitting both falls back to
`[transform.web]` or the packaged stock teipublisher ODD. Details are in
[Configuration](configuration.md#selecting-an-odd-by-type).

## HTML (`web`)

Full-document output is wrapped in a Jinja2 template and can include
ODD-generated CSS, a user stylesheet, and optional tei-publisher web components.
See [Templates & CSS](templates-and-css.md).

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd \
  --preview --template templates/tufte.html.j2
```

## Markdown

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t markdown --preview
```

`--preview` renders the Markdown in the terminal with
[Rich](https://rich.readthedocs.io/).

## DOCX

DOCX is binary, so `-o` is required (it cannot be previewed). A custom Word
`.docx` can be supplied as a **style template** via `--template` or the
`[transform.docx] template` config key; its paragraph and character styles are reused in
the output. Missing built-in styles (`Hyperlink`, `footnote text`,
`footnote reference`) are injected automatically.

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t docx -o report.docx \
  --template templates/corporate.docx
# Or: -c teipublisher.toml -t docx -o report.docx
```

## Typst

Typst output uses a `.typ.j2` Jinja2 template (e.g. a `book` or `documentation`
layout), configured under `[transform.typst]` in `opm.toml`.

```bash
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t typst -o out.typ
```

## Adding a new format

Subclass [`ProcessingModelFunctions`](../api/output-functions.md) and implement
its behaviour methods. Because the generated transform code is format-agnostic,
the same compiled module works with any implementation you provide.
