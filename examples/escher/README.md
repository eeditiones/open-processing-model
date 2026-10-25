<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# Alfred Escher letters

An example `opm` project for a letter edition with two readings of each letter,
after the reading view of the
[Digitale Briefedition Alfred Escher](https://www.briefedition.alfred-escher.ch/briefe/):

- the **edited text** runs on as prose, with popovers on names and
  abbreviations and the letter's people and places in a register beside it;
- the **diplomatic text** keeps the manuscript's lines, alignment, additions
  (⌜ ⌝), deletions and hyphens, with the facsimile beside it. Hovering over a
  line shows that line's crop of the page above it and moves the viewer to it.

Five consecutive letters of the edition ship here (B0095–B0099, June to
September 1831): one from Alfred Escher to Johann Jakob Horner, then four to
his teacher Heinrich Schweizer, an unbroken run of their correspondence, so
both rows of the letter navigation have somewhere to go. The rest of the edition, some 5,000 letters,
is in the [edition's repository](https://github.com/stazh/briefedition-escher).

`odd/escher.odd` is the edition's own processing model, ported to opm. It
inherits the packaged `teipublisher` model (`schemaSpec/@source="teipublisher.odd"`).

<!-- opm:repo-only -->
The commands below call `opm` directly, as an installed copy would. From a clone
it lives in the project venv, so either prefix them with `uv run`, activate the
venv (`source .venv/bin/activate`), or put the working tree on your `PATH` once
with `uv tool install --editable .`. Either way `opm` loads this `opm.toml`
automatically.

```bash
cd examples/escher
```
<!-- /opm:repo-only -->

## Chunk and preview

```bash
opm chunk data/letters --force --preview
```

One page per letter goes to `chunks/B0096/index.html`, with a letter list at
`chunks/index.html`. Serve them (`opm serve`) rather than opening the files:
the facsimile comes from the edition's IIIF server, and the page loads the
TEI Publisher web components from a CDN.

The letters are addressed by their number in the edition, `B0096`, as at
`briefedition.alfred-escher.ch/briefe/B0096`, not by their file name. The
files and their `xml:id` say `K_0096`; `[chunking]` derives the directory from
that and puts the page at its `index.html`:

```toml
document_name = "'B' || substring-after(/TEI/@xml:id, 'K_')"
file_pattern = "index.html"
```

## Two readings, one page

The page holds the transcription once. The ODD does not choose a reading. It
classifies what the transcription records: `add` becomes `.addition`, `del`
`.deletion`, `lb[@break='no']` a `.hyphen`, and `p/@rend` a class of its own.
The **Edierter Text / Diplomatischer Text** switch in the toolbar
(`templates/escher.js`) sets `body.escher--edited` or `body.escher--diplomatic`,
and `templates/letter.css` shows what goes with each. The choice is remembered
per browser. Without JavaScript the page shows the edited text.

The edition did this with `<pb-select-feature>` toggling a `.toggle` class and
re-rendering the view; a static page only needs the class.

One deliberate difference: the edition's edited text hides additions along with
deletions. Here the edited text keeps them (unmarked), since an addition is the
writer's text.

## Lines and the facsimile

For each line of the manuscript, the edition records where it sits on the page
image, in a mapping table per letter (`data/regions/`):

```xml
<doc id="K_0096" n="1" image="K_0096_1r_crop.jpg">
  <area shape="rect" coords="111,427,1136,504" target="p1-l7"/>
```

The `lb` models look their own line up in that table, through two XPath
extension functions in `extensions/escher_functions.py`:
`tp:region_image(letter, line)` and `tp:region_coords(letter, line)`. The page
comes from the `p<n>-` prefix of `lb/@xml:id`, the rectangle from the `area`
that targets it. Each `lb` becomes `<br class="lb" data-image data-coords>`.
The first line of a page also emits a `<pb-facs-link>` that registers the page
image with `<pb-facsimile>`, unless the letter has no table.

The functions read a letter's table the first time one of its lines asks, and
keep it while that letter is processed. The edition has some 5,000 tables:
declaring them as a `[[transform.collections]]` and searching that from every
line would parse them all for each letter, and look at each of them for every
line.

`templates/escher.js` then wraps each line in a `<span class="line">`. In the
diplomatic view, hovering over a line asks the IIIF server for just that region
(`…/escher!<image>/<x,y,w,h>/full/0/default.jpg`) and shows it above the line.
It also emits `pb-show-annotation`, so the viewer turns to the page and frames
the line.

Two things the viewer needs, both in the templates:

- `cors="Anonymous"` on `<pb-facsimile>`: the tiles come from another origin.
- OpenSeadragon's canvas drawer rather than its default WebGL one. With WebGL,
  the viewer can stay blank in Chrome without any error. pb-facsimile has no
  option for it, so `escher.js` sets the default before the viewer is created.

## Letter navigation

As in the serafin example, `correspContext` becomes a hidden `<nav>` whose
`data-*` attributes name the neighbouring letters. `templates/letter.html.j2`
turns them into two rows of links: the edition's own order, and the letters
between the same correspondents. The `correspContext` targets are the
edition's letter numbers (`B0097`), so they name the neighbour's directory as
they stand: the link is `../B0097/`. A neighbour links only if it was chunked
in the same run, so at the ends of this five-letter sample the links are greyed out.

## Project layout

- `odd/escher.odd` — processing model (plus `escher.css`)
- `templates/escher.html.j2` — page shell: fonts, logo, chapbook design
- `templates/letter.html.j2` — a letter: navigation, head, text, register, facsimile
- `templates/index.html.j2` — the letter list
- `templates/letter.css` — the two readings, navigation, register, facsimile column
- `templates/chapbook.css` — the monograph example's "paper" design
- `templates/escher.js` — view switch, lines, hover snippet, register highlighting
- `extensions/escher_functions.py` — `tp:region_image`, `tp:region_coords`
- `opm.toml` — extension module, IIIF base URL, letter URLs, chunk fragments
- `data/letters/` — five letters
- `data/regions/` — their facsimile mapping tables

## Licence

The project furniture here — stylesheets, templates and `opm.toml` — is released
by e-editiones under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/);
`opm init --example` copies it into your own project with no strings attached.

Two files are the exception. `odd/escher.odd` (with `odd/escher.css`) and
`templates/escher.js` are ported from the Escher edition's TEI Publisher app,
copyright 2021–2026 eXistSolutions GmbH. eXistSolutions has relicensed them from
GPL-3.0 to the licence of the letters,
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), as the ODD's
`teiHeader` and the script's header state.

The documents under `data/` are not covered by the CC0 dedication. The letters
and mapping tables are published by the Alfred Escher-Stiftung, Zürich, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); cite them as:
Jung Joseph (Hrsg.), Digitale Briefedition Alfred Escher, Relaunch Januar 2022,
Zürich. The facsimiles are served by the edition and are not part of this
project.
