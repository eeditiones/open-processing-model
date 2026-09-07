<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# DocBook documentation

A worked `opm` project for handbook-style DocBook, matching the TEI Publisher
documentation setup: section chunking, global TOC, title and browse fragments,
and per-chunk breadcrumbs. This is the config
[Integration with TEI Publisher][tp-guide] refers to.

[tp-guide]: https://github.com/eeditiones/tei-publisher-py/blob/main/docs/guide/tei-publisher.md

Only one article ships here (Gentle Introduction). The rest of the
corpus lives in the Jinks docs profile (`../jinks/profiles/docs/data/doc`).
Screenshots referenced from those files are not included.

<!-- opm:repo-only -->
From a clone, `uv run` finds the repo project even from this directory.
`opm` then loads this `opm.toml` automatically.

```bash
cd examples/docbook
```
<!-- /opm:repo-only -->

## Transform

```bash
uv run opm transform data/doc/quickstart.xml --preview
uv run opm transform data/doc/quickstart.xml -t print --preview
uv run opm transform data/doc/quickstart.xml -t typst -o /tmp/quickstart.typ
```

`-t print` uses `templates/print.html.j2` (no handbook chrome / web components).
The ODD’s `docbook.css` supplies `@page` and `float: footnote` rules for Prince
or the browser print dialog.
## Chunk and preview

Sections are split at depth 2 (same as the `<?teipublisher … depth="2"?>`
processing instruction). The handbook shell fills title, TOC, and breadcrumbs:

```bash
uv run opm chunk data/doc/quickstart.xml --force --preview
```

Or chunk both sample articles (writes `chunks/<file>/`):

```bash
uv run opm chunk data/doc --force --preview
```

## Layout

- `odd/docbook.odd` — DocBook processing model (plus `docbook.css`)
- `templates/handbook.html.j2` — documentation shell with sidebar TOC
- `templates/print.html.j2` — paged-media shell for `-t print`
- `opm.toml` — `dbk_section_chunks`, depth 2, title/toc/breadcrumb fragments
- `data/doc/` — sample DocBook articles

## Licence

The project furniture here — stylesheets, templates, `opm.toml`, extension and helper
scripts — is released by e-editiones under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); `opm init --example` copies
it into your own project with no strings attached.

The ODD under `odd/` is the exception: it comes from TEI Publisher and is
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), copyright eXistSolutions GmbH,
as its own `teiHeader` states. Reuse it as you like; CC BY asks only that you keep that
statement in the file and credit eXistSolutions GmbH.

The documents under `data/` are not covered by that dedication. They are source texts with
their own provenance and rights, noted above.
