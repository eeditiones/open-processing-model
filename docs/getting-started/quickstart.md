# Quickstart

This walkthrough takes a TEI document from an ODD file to rendered output and a
chunked static site. It uses the example ODD and document shipped in the repo
(and the packaged stock `teipublisher` ODD when you omit `--odd` / config).

## 1. Transform a document

ODDs are compiled on demand into the user cache (no separate compile step).
Preview HTML in the browser:

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd \
  --preview --template templates/tufte.html.j2
```

Or rely on the packaged stock ODD (same result for the default TEI Publisher
model):

```bash
uv run opm transform demo/tei-test.xml --preview
```

The cache path is printed on stderr, for example:

```text
Compiled …/teipublisher.odd → ~/Library/Caches/opm/modules/teipublisher-web-….py
```

Write to a file instead of previewing:

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -o output.html
```

Other output channels via `--type` (compiles the ODD for that mode):

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t markdown --preview
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t docx -o output.docx
```

With ODDs declared in a TOML config (see
[Configuration](../guide/configuration.md#selecting-an-odd-by-type)), omit
`--odd` and select the format with `--type`/`-t`:

```bash
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t docx -o output.docx
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t typst -o output.typ
```

Pass runtime parameters (exposed to XPath as `$parameters`) with `-p`:

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd \
  -p mode=toc -p display=browse -o output.html
```

`$parameters?root` is bound automatically to the viewed node — see
[ODD files](../guide/odd-files.md#parametersroot).

## 2. Chunk a document for a static site

```bash
uv run opm chunk demo/tei-test.xml -o chunks/ --force
```

Or emit JSON data files for a static site generator (Eleventy, Hugo, …):

```bash
uv run opm chunk demo/tei-test.xml --format json -o _data/chunks
```

## 3. Preview the chunked site

```bash
uv run opm serve -d chunks/
```

Most options have sensible defaults in `opm.toml` — see
[Configuration](../guide/configuration.md) so you can drop the repetitive flags.
For driving these steps from Python instead of the CLI, see the
[transform API](../api/transform.md) and [chunking API](../api/chunking.md).
