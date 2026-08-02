<p align="center">
  <img src="assets/logo-wordmark.svg#only-light" alt="opm — Open Processing Model" width="380">
  <img src="assets/logo-wordmark-dark.svg#only-dark" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) is an implementation of the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) 
in Python. It provides a Python CLI and library for transforming
XML documents — TEI, DocBook, and others — into HTML, Markdown, DOCX, and Typst.
The transformation rules are not hard-coded: they are declared in an **ODD** file
using the TEI Processing Model, and `opm` compiles that ODD into a reusable
Python transform module.

The implementation is a Python port of the core library of TEI Publisher: [`tei-publisher-lib`](https://github.com/eeditiones/tei-publisher-lib).
While `tei-publisher-lib` compiles the processing model instructions found in an ODD into XQuery code, `opm` outputs Python instead. If you compare
the generated code of both, you'll notice a lot of similarities.

However, `tei-publisher-lib` uses the full power of XQuery 3.1 inside an eXist-db database. `opm`, on the other hand, is limited to XPath 3.1. For most ODDs  this should not be a problem. Other differences:

- `opm` processes one file at a time, while `tei-publisher-lib` can access any resource in the database.
- `opm` is very fast for batch processing.

One can also combine `opm` with TEI Publisher, e.g. to preprocess TEI content, so TEI Publisher can serve it as static content without having to transform it on the fly.

## How it works

```
ODD file ──(compile on demand)──▶ cached Python module ──transform──▶ HTML / Markdown / DOCX / Typst
                                                           └──chunk──────▶ pages + manifest (for static sites)
```

1. **Compile on demand** — an ODD file describes a processing model: which
   elements match which *models*, and what *behaviour* each produces. The first
   time you transform or chunk with an ODD, `opm` compiles it into a Python
   module in the user cache and prints that path on stderr.
2. **Transform** — `opm transform` loads that module (via `--odd`/`-d` or
   `--type`/`-t` looking up config), parses an XML document with lxml, and
   walks the element tree. Each element is routed through `_dispatch` to a
   handler that emits output through a concrete
   [`ProcessingModelFunctions`](api/output-functions.md) implementation
   (HTML, Markdown, Typst, or DOCX) — so the same generated code serves every
   format.
3. **Chunk** — `opm chunk` splits a large document by an XPath selector,
   transforms each chunk, and writes pages plus a manifest, ready for a static
   site generator or the tei-publisher web components.

## Where to go next

- New here? Start with [Installation](getting-started/installation.md) and the
  [Quickstart](getting-started/quickstart.md).
- Learn the concepts: [ODD files](guide/odd-files.md),
  [Output formats](guide/output-formats.md),
  [XPath extensions](guide/xpath-extensions.md),
  [Templates & CSS](guide/templates-and-css.md),
  [Chunking](guide/chunking.md), and the
  [`opm.toml` configuration](guide/configuration.md).
- Reference: the [CLI](cli.md) and the [Python API](api/index.md).
