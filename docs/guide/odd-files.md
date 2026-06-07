# ODD files

An **ODD** (One Document Does it all) file is a TEI XML document which includes
*processing model* instructions. `opm compile` turns an ODD into a Python transform module.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd). 
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

Example ODD files ship in the repo under `odd/`:

- `odd/teipublisher.odd` — the main, comprehensive TEI example
- `odd/docbook.odd` — DocBook
- `odd/shakespeare.odd` — a small, readable starting point

## Compiling

To use an ODD for a transformation, it first needs to be compiled into a Python transformation module.

```bash
uv run opm compile odd/teipublisher.odd            # → modules/teipublisher-web.py
uv run opm compile odd/teipublisher.odd --mode docx
```

See the [CLI reference](../cli.md#opm-compile) for all options, or
[`opm.odd_compiler.compile_odd`](../api/odd-compiler.md) to compile from Python.
