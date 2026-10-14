# Footnotes

For most output formats, footnotes are handled by the target: Typst, EPUB,
Word, and print CSS each place notes themselves. HTML (`web`) and Markdown are
the exception — opm collects the note bodies while rendering and places them at
the end of the run.

By default notes appear in document order. That is fine for a single series, but
critical editions often use two: a lettered text-critical apparatus and a
numbered commentary. In the source the two are interleaved; in print the
apparatus usually comes first:

```xml
<p>…den Sinn<note n="a" type="textcritical">Druckmanuskript: «Sinne»</note>
   dieser Stelle<note xml:id="n14">Vgl. Kierkegaard, <title>Einübung</title>, 73.</note>…</p>
```

Notes that carry their own TEI `@n` keep that label and do not consume the
running counter, so the commentary still reads 1, 2, 3 even when apparatus
notes (a, b, c) sit between them.

### Lemma ranges

When a note covers a span of text, put an `<anchor type="note"/>` at the start
and the `<note>` at the end with `@target` pointing at the anchor:

```xml
…vielmehr <anchor type="note" xml:id="fn-b"/>eine nur als Ausnahme mögliche,
ja unmögliche Erscheinung<note n="b" target="fn-b" type="textcritical">…</note>…
```

The start is marked `b-`, the end `-b`, and the footnote is labelled `b-b`.
Point notes without an anchor still show a single marker (`b`).

## Configuring the order

Set `[transform] footnote_order` in `opm.toml` to a Python callable:

```toml
[transform]
footnote_order = "opm.runtime.footnote_order.labelled_first"
```

Or pass it on the command line:

```bash
opm chunk data/47009.xml --footnote-order opm.runtime.footnote_order.labelled_first
```

Two orderings ship with opm (see
[`opm.runtime.footnote_order`](../api/runtime.md#footnote-ordering)):

- **`labelled_first`** — notes with a non-numeric marker first, then the rest
  (the two-series case above)
- **`by_place`** — TEI `@place="foot"` before `@place="end"`

The hook runs once per output unit: once for a whole-document transform, once
per chunk page, or once per `section.opm-page` when pages are enabled. Notes are
already numbered when it runs, so reordering never changes markers or breaks
`#fn_…` links.

## Writing your own

An ordering is a plain Python function. It receives the footnotes in document
order and returns the ones to emit:

```python
# extensions/my_notes.py
def sources_last(footnotes, config):
    """Bibliographic notes after the commentary."""
    sources = [fn for fn in footnotes if fn.node.get('type') == 'source']
    rest = [fn for fn in footnotes if fn.node.get('type') != 'source']
    return rest + sources
```

```toml
[project]
pythonpath = ["."]

[transform]
footnote_order = "extensions.my_notes.sources_last"
```

Each item is a [`Footnote`](../api/runtime.md#render-context) record with
fields such as `marker`, `label`, `place`, and `node` (the source element). You
can drop notes from the return list to omit them from the output.

## Styling two series

A note with its own `@n` gets `data-n` on both the reference and the body, so
CSS can distinguish the series without parsing the marker:

```css
.footnote[data-n] .fn-number { font-style: italic; }
.tei-note[data-n] > a.note   { font-style: italic; }
```

The same attribute is set in `print` mode, so one rule covers both.

## Example

[`examples/monograph`](https://github.com/eeditiones/open-processing-model/tree/main/examples/monograph)
is Karl Barth's *Römerbrief* with both series and
`footnote_order = "opm.runtime.footnote_order.labelled_first"`:

```bash
cd examples/monograph
uv run opm chunk data/47009.xml --force --preview
```
