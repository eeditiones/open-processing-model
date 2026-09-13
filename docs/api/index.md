# API Reference

`opm` can be driven entirely from the command line, and every command is a thin
wrapper over a public Python API. Use it when you want to embed transforms in
your own scripts, a static site generator, or a web service.

Start with [`opm.Project`](project.md). It loads `opm.toml` and does what the
commands do:

```python
from opm import Project

project = Project.load()
html = project.transform('data/doc.xml')
run = project.chunk('data', format='json', overwrite=True)
```

The modules below are the layer underneath, for finer control:

| You want to… | Start here |
| --- | --- |
| Load a project and transform, chunk or index with its settings | [`opm.Project`](project.md) |
| Run a transform on an XML file or element | [`opm.transform`](transform.md) |
| Turn Typst output into a PDF | [`opm.typst_compile`](typst-compile.md) |
| Split a document into pages / JSON for a site | [`opm.chunking`](chunking.md) |
| Build search / embedding records from a document | [`opm.indexing`](indexing.md) |
| Find what an ODD never runs, or never handles | [`opm.coverage`](coverage.md) |
| Read `opm.toml` settings programmatically | [`opm.config`](config.md) |
| Compile an ODD into a transform module | [`opm.odd_compiler`](odd-compiler.md) |
| Implement a new output format | [`opm.runtime.output_functions`](output-functions.md) |
| See or add what an output mode (`-t`) does | [`opm.output_modes`](output-modes.md) |
| Understand the tree-walking runtime / XPath extensions | [`opm.runtime`](runtime.md) |

The pages below are generated directly from the source docstrings, so they stay
in sync with the code.
