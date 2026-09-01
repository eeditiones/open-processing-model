# Output formats

A single ODD drives every output format. The format is chosen at **compile**
time via `--type` / `-t` (or the matching config table), which selects the ODD
`@output` channel and the concrete
[`ProcessingModelFunctions`](../api/output-functions.md) implementation used to
emit output.

| Mode | Output | Implementation |
| --- | --- | --- |
| `web` (default) | HTML5 | `HtmlOutputFunctions` |
| `print` | HTML for paged-media CSS | `PrintOutputFunctions` (extends HTML) |
| `epub` | EPUB 3 (`.epub` ZIP) | `EpubOutputFunctions` + packager |
| `markdown` | Markdown | `MarkdownOutputFunctions` |
| `docx` | Word `.docx` (binary) | `DocxOutputFunctions` |
| `typst` | Typst markup | `TypstOutputFunctions` |
| `json` | The processing model's decisions as data | `JsonOutputFunctions` |

`print`, `epub` and `json` also accept ODD models tagged `@output="web"`, matching
tei-publisher-lib’s `output: ["print"|"epub", "web"]` fallback. Models without `@output`
still apply to every mode.

Models may use an optional `opm-` prefix on `@output` (e.g. `opm-web`) for rules
that apply only when compiling with this Python implementation. tei-publisher-lib
ignores those models. Among models that match the compile mode, the usual ODD
rule applies: the first whose conditions apply wins.

```bash
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t epub -o book.epub
uv run opm transform examples/tei-test.xml -t markdown --preview
uv run opm transform examples/tei-test.xml -t docx -o out.docx
uv run opm transform examples/tei-test.xml -t typst -o out.typ
uv run opm transform examples/tei-test.xml -t json -o out.json
```

Each compile writes (or reuses) a cached module under the user cache directory;
the path is printed on stderr.

## Choosing an ODD at transform time

Pass an ODD with `--odd`/`-d`, or select from your TOML config with `--type`/`-t`
(and `-c` if the config is not `opm.toml`):

| `--type` | Config key (override) | Falls back to |
| --- | --- | --- |
| `web` | `[transform.web].odd` | `[transform].odd` |
| `print` | `[transform.print].odd` | `[transform].odd` |
| `epub` | `[transform.epub].odd` | `[transform].odd` |
| `docx` | `[transform.docx].odd` | `[transform].odd` |
| `typst` | `[transform.typst].odd` | `[transform].odd` |
| `json` | `[transform.json].odd` | `[transform].odd` |
| `markdown`, … | `[transform.<type>].odd` | `[transform].odd` |

```bash
# Explicit ODD (compiled on demand)
uv run opm transform examples/tei-test.xml --preview

# Looked up from config (see Configuration)
uv run opm transform examples/tei-test.xml -t web --preview
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t typst -o out.typ
uv run opm transform examples/tei-test.xml -t docx -o out.docx
```

`--odd`/`-d` overrides config lookup. Omitting both falls back to
`[transform.<type>].odd`, then `[transform].odd`, then the packaged stock
teipublisher ODD. Details are in
[Configuration](configuration.md#selecting-an-odd-by-type).

## HTML (`web`)

Full-document output is wrapped in a Jinja2 template and can include
ODD-generated CSS, a user stylesheet, and optional tei-publisher web components.
See [Templates & CSS](templates-and-css.md).

```bash
uv run opm transform data/sample.xml \
  --preview --template templates/tufte.html.j2
```

## Print (paged media)

`print` emits HTML like `web`, but notes and alternates are inline
`<span class="footnote">` / `margin-note` spans so CSS paged media can
`float: footnote` (Prince, Paged.js, browser print). Interactive callouts and
web components are disabled. ODD models with `@output="print"` apply in addition
to `@output="web"` and unscoped models.

The Jinja shell is separate from the web reading view. Resolution:

1. `--template` / `-t` override
2. `[transform.print] template`
3. Packaged `default_print.html.j2` (minimal; **not** the web `[document] template`)

Paged layout itself comes from the ODD’s CSS (often `@page` / `@media print` in
a tagsDecl stylesheet). OPM only produces the markup; PDF rendering is external.

```bash
uv run opm transform examples/tei-test.xml -t print --preview
uv run opm transform examples/tei-test.xml -t print -o print.html
```

The DocBook example wires a dedicated shell:

```bash
cd examples/docbook
uv run opm transform data/doc/quickstart.xml -t print --preview
```

See `examples/docbook/templates/print.html.j2` and `[transform.print]` in that
project’s `opm.toml`. `examples/jats` does the same the other way round: its
print shell includes the web view’s `journal.css`, so the paged article keeps
the reading view’s typography and only loses the masthead and TOC rail.

## EPUB

`epub` compiles with EPUB-oriented HTML behaviours (synthetic fragment ids,
`epub:type` pagebreaks, footnote asides) and packages the result as an EPUB 3
ZIP (mimetype, OPF, `nav.xhtml`, NCX, chapters, CSS, images). Chapters are
selected with the same `[chunking]` rules used by `opm chunk` (default:
TEI `tei_div_chunks` / DocBook `dbk_section_chunks` at depth 1).

`[transform.epub]` may override that selection with its own `xpath`, `selector`
or `depth`: what belongs in a book is not always what the reading view pages
through — `examples/serafin` chunks only the source text and fills the
translation into a second panel, which an EPUB has not got. A page-milestone
selector (`tei_pb_chunks`) is always replaced by divisions, since a reading
system repaginates anyway.

```bash
uv run opm transform examples/tei-test.xml -t epub -o book.epub
```

Optional config:

```toml
[transform.epub]
# odd = "odd/my-epub.odd"
css = "templates/epub.css"   # appended last to the packaged stylesheet
skip_title = false           # omit the generated title page when true
# xpath = "//text[@type]"    # chapter selection, when it differs from [chunking]
# selector = "opm.navigation.tei_div_chunks"
# depth = 2

[chunking]
selector = "opm.navigation.tei_div_chunks"
depth = 1
```

Like DOCX, the result is binary — write it with `-o` (terminal preview is not
supported). Packaging uses stdlib `zipfile` + lxml (no ebooklib).

A chapter is named in the table of contents by the heading it opens with once
transformed, consecutive headings joined (*Act 2, Scene 1*) — so the ODD can
name a chapter the source does not. Failing that: the chunk's own `head` /
`title`, then the page number of a `pb` it opens on.

### Styling

`OEBPS/stylesheet.css` is a cascade of three parts, each able to override the
one before:

1. **The packaged baseline** (`opm/resources/styles/epub.css`) — typography for
   headings, lists, code, tables, figures, footnotes and the title page. It
   also defines fallbacks for the `--jinks-*` / `--pb-*` custom properties that
   web-oriented ODD stylesheets reference, so rules carried over from the
   reading view degrade instead of dropping out.
2. **The ODD stylesheet** — base rules plus `outputRendition` styles.
3. **`[transform.epub] css`** — the project stylesheet, for restyling anything
   the reading view brought along that does not suit an e-reader (sticky
   chrome, `color-mix()`, viewport units). `examples/docbook/templates/epub.css`
   is a worked example that recreates the handbook’s web look;
   `examples/shakespeare/templates/epub.css` is the opposite case, dropping the
   reading view’s two-column Folio layout and its page furniture for a plain
   reading text.

Rules a project wants in *every* view belong in the ODD stylesheet, not here.
`@rend` tokens in particular reach the output as bare class names that the
processing model never defines, so they are the ODD stylesheet’s to declare —
see `examples/shakespeare/odd/shakespeare.css`.

Reading systems render EPUB 3 XHTML, which has no room for custom elements or
their attributes. Web components are therefore degraded rather than emitted:
`pb-code-highlight` becomes `<pre><code>`, `pb-link` becomes an `<a>` pointing
at its cross-reference, and anything else — including custom elements
introduced by a `pb:template` — becomes a transparent `<div>` or `<span>`.
Fragment links are rewritten to name the chapter file that holds the target, so
cross-references keep working after the document is split.

Images referenced by `img/@src` are resolved next to the source document and in
a sibling `images/` directory. Images that cannot be found are left out of the
manifest, since an OPF entry without a file makes the package invalid.

## Markdown

```bash
uv run opm transform examples/tei-test.xml -t markdown --preview
```

`--preview` renders the Markdown in the terminal with
[Rich](https://rich.readthedocs.io/).

## DOCX

DOCX is binary, so `-o` is required (it cannot be previewed). A custom Word
`.docx` can be supplied as a **style template** via `--template` or the
`[transform.docx] template` config key; its paragraph and character styles are reused in
the output. If none is given, the packaged `default.docx` is used (the same file
`opm init` copies into `templates/`). Missing built-in styles (`Hyperlink`,
`footnote text`, `footnote reference`) are injected automatically.

```bash
uv run opm transform examples/tei-test.xml -t docx -o report.docx \
  --template templates/corporate.docx
# Or: -t docx -o report.docx
```

## Typst

Typst output uses a `.typ.j2` Jinja2 template configured under `[transform.typst]`.
Project templates include `templates/book.typ.j2` (TEI) and
`templates/docbook.typ.j2` (DocBook UI classes); both use ilm. The packaged
fallback is `default_document.typ.j2`.

```bash
uv run opm transform examples/tei-test.xml -t typst -o out.typ
```

## JSON

`-t json` does not render the document. It records **what the processing model
did to it**: which behaviour ran for each element, which model won, where the
element came from, and what text it contributed.

```bash
uv run opm transform examples/tei-test.xml -t json -o out.json
```

!!! note "Not the same as `opm chunk --format json`"

    `opm chunk --format json` wraps rendered **HTML** in a JSON envelope for
    static site generators. `-t json` emits structured **data** about the
    transformation itself. They serve different consumers.

Every element that reaches a behaviour produces a record — inline and
`pass_through` ones included. A wrong inline model is the commonest ODD bug, and
folding its text into the enclosing block would hide which model matched;
likewise, when the model you expected did not fire because a `pass_through` one
matched first, emitting nothing would make the element vanish entirely:

```json
{
  "id": "pi-first-steps",
  "xpath": "/TEI/text[1]/body[1]/div[2]",
  "line": 84,
  "col": 7,
  "element": "div",
  "behaviour": "section",
  "model": "tei-div11",
  "children": [
    { "element": "head", "behaviour": "heading", "level": 2, "children": ["First steps"] },
    { "element": "p", "behaviour": "paragraph", "children": ["To open the visual editor…"] }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `id` | `@xml:id` / `@id`, when the element has one |
| `xpath` | Path to the source element, by name — see below |
| `line`, `col` | Where the element's start tag begins in the source file |
| `element` | Local name |
| `behaviour` | The behaviour that ran; `null` when no model matched |
| `model` | Key into the top-level `models` table |
| `children` | Ordered mix of text runs and child records |
| `suppressed` | Present and `true` for `omit` / `index` / `metadata` |

`xpath` names its elements (`/TEI/text[1]/body[1]/div[2]`) rather than using
lxml's `/*/*[3]/*[1]`, which is all `getpath()` can emit when a default
namespace has no prefix bound. Because opm resolves unprefixed names against
the document's default namespace, these paths run directly against the same
document:

```bash
uv run opm transform doc.xml -x '/TEI/text[1]/body[1]/div[2]' --preview
```

Elements outside that default namespace — MathML inside TEI, say — keep the
positional form for those steps (`…/formula[1]/*[1]/*[1]`), since an unprefixed
step would not match them.

`line` and `col` point at the `<` of the start tag, 1-based, so a record can be
opened directly:

```bash
uv run opm transform doc.xml -t json -o out.json
# then, for any record:  $EDITOR +84 doc.xml   /   code -g doc.xml:84:7
```

They come from a second pass with expat rather than from lxml's `sourceline`,
which reports where a start tag *ends* — an element whose attributes wrap onto
another line is reported below its own `<`. Columns matter because dense TEI
puts many elements on one line: 53% of the elements in `examples/tei-test.xml`
share a line with another.

Positions need the source file, which the CLI passes automatically. A caller
transforming a tree it built in memory gets records without `line`/`col` rather
than an error, and if the file does not match the tree the whole map is dropped
— a position pointing at the wrong element is worse than none. Elements from a
chunk selector that rebuilt its region are resolved back to the originals they
were copied from.

**Text lives in `children` and nowhere else.** Each run appears once, on the
record that produced it, interleaved with child records in source order. Join
`children` recursively when you want the full text of a subtree.

There is deliberately no rolled-up `text` field. It would be pure duplication,
and for mixed content it reads as corrupt — a paragraph containing a link would
report its own runs as a sentence with a hole in it:

```json
"text": "Numerous projects realized with  prove that it is:"
```

with the link's words on the nested record instead. Rolling up *descendant*
text avoids the hole but stores every passage once per tree level, which is
worse: an embedding store would then hold the same sentences at three
granularities.

Two things this makes visible that no other output can:

**Suppressed content.** `omit`, `index` and `metadata` produce no output, so a
renderer cannot distinguish "the ODD dropped this" from "it was never in the
source". Here they leave a record marked `"suppressed": true`.

**Unmatched elements.** An element with no matching model never reaches a
behaviour at all — its text just surfaces in some ancestor. In JSON it appears
with `"behaviour": null`, so you can find everything an ODD does not cover:

```bash
uv run opm transform doc.xml -t json -o out.json
python -c "
import json
from collections import Counter
d = json.load(open('out.json'))
def walk(r):
    if isinstance(r, dict):
        if r.get('behaviour') is None: yield r['element']
        for c in r.get('children', []): yield from walk(c)
print(Counter(e for root in d['document'] for e in walk(root)))
"
```

### Choosing which channel to inspect

`-t json` on its own records the **web** channel's decisions. That is the wrong
answer when the ODD you are debugging targets another one — typst and docx
models in particular are the hardest to eyeball, since there is no browser to
open. `--channel` picks the channel whose models participate:

```bash
uv run opm transform doc.xml -t json --channel typst -o typst-decisions.json
uv run opm transform doc.xml -t json --channel docx  -o docx-decisions.json
```

Accepted channels are `web` (default), `print`, `epub`, `markdown`, `docx` and
`typst`. Each compiles to its own cached module, because which models
participate is fixed at compile time.

The channel changes the answer. In the packaged `teipublisher.odd`, the same
`teiHeader` element resolves differently:

| Channel | Behaviour | Model |
| --- | --- | --- |
| `web` | `metadata` (suppressed) | `tei-teiHeader8` |
| `typst` | `pass_through` | `tei-teiHeader3` (`@output="typst"`) |

So the web view stops at the header, while the typst view descends into it and
records `title` and `author` under typst-only models. Diffing two channels is a
quick way to see what a channel actually changes:

```bash
uv run opm transform doc.xml -t json               -o web.json
uv run opm transform doc.xml -t json --channel typst -o typst.json
```

`--channel` follows the same fallback rules as the channel itself: `json-print`
and `json-epub` also accept `@output="web"` models, exactly as `print` and
`epub` do, while `json-typst` and `json-markdown` do not.

### The `models` table

A record names the model that won, but not what that model *was*. The
`models` table resolves the key:

```json
"models": {
  "tei-div11": {
    "element": "div",
    "behaviour": "section",
    "predicate": "@type='section'",
    "desc": "Sections of the document body"
  }
}
```

`source` appears when the model was inherited from an extended ODD rather than
written in the one being compiled, and names that file:

```json
"tei-hi3": {
  "element": "hi",
  "behaviour": "inline",
  "source": "teipublisher.odd",
  "predicate": "@rend='italic'"
}
```

Its absence means the model is local. Because a local `elementSpec` replaces the
inherited one wholesale, every model of an element you redeclare is local; the
flag tells you whether a decision you dislike can be changed here at all, or has
to be overridden by redeclaring the element.

`predicate`, `desc`, `output` and `source` appear nowhere in the record tree, so
the table is not derivable from the records. Neither are the models that **did
not** fire — and those are the more valuable half, because "why did my model
not win?" is answered by reading the predicate of the one that beat it:

```bash
# every model competing for `hi`, in ODD order — the first match wins
python -c "
import json
d = json.load(open('out.json'))
for key, m in d['models'].items():
    if m['element'] == 'hi':
        print(key, m['behaviour'], m.get('predicate', '(no predicate)'))
"
```

The table is pruned to elements the document actually contains. A model for an
element that never appears can explain nothing about this document, and on a
large ODD those are most of the entries — for `examples/tei-test.xml` against
the packaged ODD, 239 models prune to 138. Pruning is keyed on the source tree,
not on the emitted records, so a subtree the ODD suppresses (`teiHeader`, say)
keeps its models: that is precisely what you are reading when you ask why
nothing came out of it.

Models that survive pruning but never fired are the coverage report: elements
the document uses, models the ODD declares for them, and no match.

For building a search index from this data, see
[Search indexing](search-indexing.md).

## Adding a new format

Subclass [`ProcessingModelFunctions`](../api/output-functions.md) and implement
its behaviour methods. Because the generated transform code is format-agnostic,
the same compiled module works with any implementation you provide. Modes that
extend HTML (like `print`) typically subclass `HtmlOutputFunctions` and override
only the behaviours that differ.
