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

Without `.odd` argument, it generates the TEI P5 documentation for the latest version by default.
The full `p5.odd` will be downloaded and cached, because it serves as the base for all TEI ODDs.

You can change the default ODD to render by setting `source` under `[document]` in `opm.toml`.

## A sample customisation

`data/tei_psalmy.odd` is a real customisation to try this on: the schema of
a didactic edition of Polish Psalters, made for the
[Jagiellonian Digital Platform](https://labedyt.dhlab.uj.edu.pl/index.html) by
Magdalena Turska and Helena Bermúdez Sabel. Besides the schema it carries its
own encoding guidelines, nine chapters on how the edition marks up psalms,
verses, readings and their analysis, with examples. The site shows these
chapters first, followed by reference pages for every element, class and
macro the schema keeps.

```bash
opm odd document data/tei_psalmy.odd --force --preview
```

The ODD is distributed under the Creative Commons Attribution-ShareAlike 4.0
International licence; see its `teiHeader`.

## PDF

```bash
opm odd prepare -o schema.xml
opm transform schema.xml -t typst -o docs.pdf
# only the reference part (the A–Z appendices), or only the text:
opm transform schema.xml -t typst -p part=reference -o reference.pdf
```

## Markdown

```bash
opm transform schema.xml -t markdown -o docs.md
opm transform schema.xml -t markdown --xpath 'id("HD")' -o docs.md # just one chapter
```

## What is where

| file | what it decides |
| --- | --- |
| `opm.toml` | what to document (`[document]`), and the three chunking runs: the text, the home page (`mode = "toc"`), then one reference page per spec |
| `odd/tagdocs.odd`, `odd/tagdocs.css` | how every page renders — the processing models |
| `templates/page.html.j2` | the page around each chunk: header, sidebar, rails, extending opm's page layout (`opm/layout.html.j2`) |
| `templates/document.css`, `search.js`, `theme.js` | the site's look, search box and light/dark switch |
| `templates/nav.xml` | the sidebar list |
| `templates/logo.svg` | the logo in the header and the browser tab; replace it with your own, or put another image beside it and name it under `[context]` in `opm.toml` |
| `templates/tagdocs.typ.j2` | the PDF: title page, contents, page layout |
| `data/tei_psalmy.odd` | a sample customisation with its own encoding guidelines |

Keep `page.html.j2` and `tagdocs.typ.j2`: `opm.toml` points to them, so the
site and the PDF cannot be built without them. Delete any other file in
`templates/` and opm uses its own copy instead; the fonts always come from
there. The stylesheets, scripts, fonts
and logo are copied into `assets/` in the site.

## Other outputs

The same runs give a static site generator its input:

```bash
opm odd prepare -o schema.xml
opm chunk schema.xml --format json
```