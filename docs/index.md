<p align="center">
  <img src="assets/logo-wordmark.svg#only-light" alt="opm — Open Processing Model" width="380">
  <img src="assets/logo-wordmark-dark.svg#only-dark" alt="opm — Open Processing Model" width="380">
</p>

# Open Processing Model

**Open Processing Model** (`opm`) is an implementation of the [TEI Processing Model](https://tei-c.org/release/doc/tei-p5-doc/en/html/TD.html#TDPM) 
in Python. It provides a Python CLI and library for transforming
XML documents — TEI, DocBook, and others — into (currently) HTML, Markdown, DOCX, [Typst](https://typst.app/), HTML for print and ePub.
The transformation rules are not hard-coded: they are declared in an **ODD** file
using the TEI Processing Model, and `opm` compiles that ODD into a reusable
Python transform module.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd).
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

The design conceptually follows the [`tei-publisher-lib`](https://github.com/eeditiones/tei-publisher-lib) implementation in [TEI Publisher](https://tei-publisher.org) and aims to be as compatible as possible. While `tei-publisher-lib` compiles the processing model instructions found in an ODD into XQuery code, `opm` outputs Python instead. If you compare
the generated code of both, you'll notice a lot of similarities. However, `tei-publisher-lib` uses the full power of XQuery 3.1 inside an eXist-db database. `opm`, on the other hand, is limited to XPath 3.1 and completely file-system based.

## Uses

Typical usage scenarios for `opm` include:

* quick transformation of XML documents on the command line
* split large documents into chunks, so they can be read page by page
* prepare HTML data to be used by other systems such as static site generators
* provide [pre-rendered content for TEI Publisher](guide/tei-publisher.md) to speed up load times

## Design

`opm` was designed to use pure Python with minimal dependencies. It implements the full _TEI Processing Model_ including most of the extensions provided by _TEI Publisher_: mainly **templates**, context **parameter** passing and the possibility to define XPath extension functions. This means that most ODDs will be compatible and can be exchanged between _TEI Publisher_ and `opm`, allowing us to combine the benefits of a dynamic, database-backed website with the speed of static rendering.

ODD files are **compiled on demand** into Python modules and cached:

```
ODD file ── (compile on demand) ──▶ cached Python module ── transform ──▶ HTML / Markdown / DOCX / Typst
                                                        └── chunk ──────▶ pages + manifest (for static sites)
```

## Where to go next

- New here? Start with [Installation](getting-started/installation.md) and the
  [Quickstart](getting-started/quickstart.md).
- Learn the concepts: [ODD files](guide/odd-files.md),
  [Output formats](guide/output-formats.md),
  [XPath extensions](guide/xpath-extensions.md),
  [Templates & CSS](guide/templates-and-css.md),
  [Chunking](guide/chunking.md),
  [Integration with TEI Publisher](guide/tei-publisher.md), and the
  [`opm.toml` configuration](guide/configuration.md).
- Reference: the [CLI](cli.md) and the [Python API](api/index.md).
