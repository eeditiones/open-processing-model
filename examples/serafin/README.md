# Serafin letters

A worked `opm` project for the 15th-century correspondence of Mikołaj Serafin:
parallel Latin source and Polish translation, with people/place registers.

The tree is self-contained. `odd/serafin.odd` inherits the packaged
`teipublisher` model (`schemaSpec/@source="teipublisher.odd"`). Two letters and
the full registers ship here; the rest of the corpus lives in the TEI Publisher
jinks profile.

From a clone, `uv run` finds the repo project even from this directory.
`opm` then loads this `opm.toml` automatically.

```bash
cd examples/serafin
```

## Transform

```bash
uv run opm transform data/letters/serafin01.xml --preview
uv run opm transform data/letters/serafin01.xml -t epub -o letter.epub
```

## Chunk and preview

Each letter is one TEI document. Chunking splits the source text, then fills
translation, letter head, breadcrumbs, and register fragments:

```bash
uv run opm chunk data/letters/serafin01.xml --force --preview
```

Or chunk both sample letters (writes `chunks/<file>/`):

```bash
uv run opm chunk data/letters --force --preview
```

## Parallel text in print

`opm transform -t typst` sets the Latin transcription and the Polish translation
side by side, aligned segment by segment:

```bash
uv run opm transform data/letters/serafin01.xml -t typst -o letter.typ && typst compile letter.typ
```

The alignment is the encoding's: every translation `<seg>` carries
`@corresp="#<id>"` pointing at its source `<seg>`, so `odd/serafin.odd` looks the
counterpart up and emits the pair as one row of a two-column grid. The
translation `<text>` is then omitted, or it would print again underneath.

## Parallel text in an EPUB

Nothing can stand beside anything in a reflowing book, so the EPUB sets the two
texts one after the other, a chapter each.

```bash
uv run opm transform data/letters/serafin01.xml -t epub -o letter.epub
```

`[chunking]` selects only the source: the reading view fills the translation
from a fragment, into a second panel. An EPUB has neither, so
`[transform.epub] xpath = "//text[@type]"` selects both `<text>` elements
instead — which is also what brings them within reach of the `output="epub"`
models in `odd/serafin.odd`, whose headings name the chapters and, through them,
the table of contents.

## Gaps in print

`<gap/>` follows the [Leiden conventions](https://en.wikipedia.org/wiki/Leiden_Conventions)
in Typst output, the standard sigla for lacunae in a critical edition:

| Source | Print |
| --- | --- |
| `<gap quantity="4" unit="chars"/>` | `[....]` — one dot per lost character |
| `<gap quantity="12" unit="chars"/>` | `[c. 12]` — the count, once dots stop being countable |
| `<gap quantity="3" unit="words"/>` | `[- - -]` — dashes mark an extent undetermined in characters |
| `<gap/>` | `[- - -]` |

## Layout

- `odd/serafin.odd` — processing model (plus `serafin.css`)
- `templates/letter.html.j2` — parallel panes and tabbed register rail
- `templates/letter.typ.j2` — parallel-text print edition (two aligned columns)
- `opm.toml` — collections, `$global:register-root`, chunk fragments
- `data/letters/` — sample TEI
- `data/registers/` — persons, places, organizations, works
