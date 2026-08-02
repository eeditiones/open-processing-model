# ODD files

An **ODD** (One Document Does it all) file is a TEI XML document which includes
*processing model* instructions. `opm` compiles an ODD on demand into a Python
transform module cached under the platform user cache directory.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd).
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

Example ODD files ship in the repo under `odd/` for demos and tests. The library
packages only the stock `teipublisher` ODD (plus `tp.css`) as the default when
no `--odd` / config entry is given:

- `odd/teipublisher.odd` — main TEI Publisher model (also packaged)
- `odd/docbook.odd`, `odd/shakespeare.odd`, … — project examples, not packaged

## Compiling on demand

Pass an ODD to `opm transform` / `opm chunk` (or set `odd = "…"` in config).
The first run compiles it into the user cache and prints the path on stderr;
later runs reuse the cache until the ODD (or its inherited sources / CSS)
changes.

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd --preview
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd -t docx -o out.docx
```

From Python, use [`opm.odd_cache.ensure_compiled_module`](../api/odd-compiler.md)
or the lower-level [`opm.odd_compiler.compile_odd`](../api/odd-compiler.md).
