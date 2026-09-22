<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# ODD documentation

A configuration for generating documentation from an ODD. Can also be used to generate the full
TEI P5 documentation.

<!-- opm:repo-only -->
The commands below call `opm` directly, as an installed copy would. From a clone
it lives in the project venv, so either prefix them with `uv run`, activate the
venv (`source .venv/bin/activate`), or put the working tree on your `PATH` once
with `uv tool install --editable .`. Either way `opm` loads this `opm.toml`
automatically.

```bash
cd examples/odd
```
<!-- /opm:repo-only -->

```bash
opm odd document <myodd.odd> --force --preview
```

writes a documentation website for the given ODD to `site/` and opens it in a browser.

Without `.odd` argument, it generates the TEI P5 documentation for the latest version.
The full `p5.odd` will be downloaded and cached. It serves as the base for all TEI ODDs.
To document an ODD of your own by default, set `source` under `[document]` in `opm.toml`.

## What is where

| file | what it decides |
| --- | --- |
| `opm.toml` | what to document (`[document]`), and the two chunking runs: the text, then one reference page per spec |
| `odd/tagdocs.odd`, `odd/tagdocs.css` | how every page renders — the processing models |
| `templates/page.html.j2` | the page around each chunk: header, sidebar, rails |
| `templates/document.css`, `search.js`, `theme.js` | the site's look, search box and light/dark switch |
| `templates/nav.xml` | the sidebar list |
| `templates/tagdocs.typ.j2` | the PDF: title page, contents, page layout |

Anything you delete from `templates/` falls back to the packaged file of the
same name; the fonts and the TEI logo always come from there.

## Other outputs

The same runs give a static site generator its input:

```bash
opm odd prepare -o schema.xml
opm chunk schema.xml --format json
```

and the same tree a PDF, through Typst (`templates/tagdocs.typ.j2` is the page
layout):

```bash
opm odd prepare -o schema.xml
opm transform schema.xml -t typst -o docs.pdf
# only the reference part (the A–Z appendices), or only the text:
opm transform schema.xml -t typst -p part=reference -o reference.pdf
```
