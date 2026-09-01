# API Reference

`opm` can be driven entirely from the command line, but every command is a thin
wrapper over a public Python API. Use these modules when you want to embed
transforms in your own scripts, a static site generator, or a web service.

| You want to… | Start here |
| --- | --- |
| Run a transform on an XML file or element | [`opm.transform`](transform.md) |
| Split a document into pages / JSON for a site | [`opm.chunking`](chunking.md) |
| Build search / embedding records from a document | [`opm.indexing`](indexing.md) |
| Find what an ODD never runs, or never handles | [`opm.coverage`](coverage.md) |
| Read `opm.toml` settings programmatically | [`opm.config`](config.md) |
| Compile an ODD into a transform module | [`opm.odd_compiler`](odd-compiler.md) |
| Implement a new output format | [`opm.runtime.output_functions`](output-functions.md) |
| Understand the tree-walking runtime / XPath extensions | [`opm.runtime`](runtime.md) |

The pages below are generated directly from the source docstrings, so they stay
in sync with the code.
