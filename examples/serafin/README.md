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

## Layout

- `odd/serafin.odd` — processing model (plus `serafin.css`)
- `templates/letter.html.j2` — parallel panes and tabbed register rail
- `opm.toml` — collections, `$global:register-root`, chunk fragments
- `data/letters/` — sample TEI
- `data/registers/` — persons, places, organizations, works
