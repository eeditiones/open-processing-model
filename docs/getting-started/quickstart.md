# Quickstart

This walkthrough takes a TEI document from an ODD file to rendered output and a
chunked static site. It uses the example ODD and document shipped in the repo.

## 1. Compile an ODD into a transform module

```bash
uv run opm compile odd/teipublisher.odd
```

This writes `modules/teipublisher-web.py` (default path and `web` output mode).
Compile other formats by changing the mode:

```bash
uv run opm compile odd/teipublisher.odd --mode markdown   # → modules/teipublisher-markdown.py
uv run opm compile odd/teipublisher.odd --mode docx       # → modules/teipublisher-docx.py
```

## 2. Transform a document

Preview HTML in the browser using a Jinja2 template:

```bash
uv run opm transform demo/tei-test.xml -m modules/teipublisher-web.py \
  --preview --template templates/tufte.html.j2
```

Write to a file instead of previewing:

```bash
uv run opm transform demo/tei-test.xml -m modules/teipublisher-web.py -o output.html
```

Markdown preview in the terminal, and DOCX to a file:

```bash
uv run opm transform demo/tei-test.xml -m modules/teipublisher-markdown.py --preview
uv run opm transform demo/tei-test.xml -m modules/teipublisher-docx.py -o output.docx
```

With modules declared in a TOML config (see
[Configuration](../guide/configuration.md#selecting-a-module-by-type)), omit
`--module` and select the format with `--type`/`-t`:

```bash
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t docx -o output.docx
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t typst -o output.typ
```

Pass runtime parameters (exposed to XPath as `$parameters`) with `-p`:

```bash
uv run opm transform demo/tei-test.xml -m modules/teipublisher-web.py \
  -p mode=toc -p display=browse -o output.html
```

## 3. Chunk a document for a static site

```bash
uv run opm chunk demo/tei-test.xml -o chunks/ --force
```

Or emit JSON data files for a static site generator (Eleventy, Hugo, …):

```bash
uv run opm chunk demo/tei-test.xml --format json -o _data/chunks
```

## 4. Preview the chunked site

```bash
uv run opm serve -d chunks/
```

Most options have sensible defaults in `opm.toml` — see
[Configuration](../guide/configuration.md) so you can drop the repetitive flags.
For driving these steps from Python instead of the CLI, see the
[transform API](../api/transform.md) and [chunking API](../api/chunking.md).
