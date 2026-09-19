# Output formats

`opm` can transform XML to a number of output formats. The format is chosen (at **compile**
time) via the `--type` / `-t` parameter. This selects the ODD
`@output` channel and the specific [`ProcessingModelFunctions`](../api/output-functions.md) 
implementation used to generate that output.

| Mode | Output | Implementation |
| --- | --- | --- |
| `web` (default) | HTML5 | `HtmlOutputFunctions` |
| `print` | HTML for paged-media CSS | `PrintOutputFunctions` (extends HTML) |
| `epub` | EPUB 3 (`.epub` ZIP) | `EpubOutputFunctions` + packager |
| `markdown` | Markdown | `MarkdownOutputFunctions` |
| `docx` | Word `.docx` (binary) | `DocxOutputFunctions` |
| `typst` | Typst markup | `TypstOutputFunctions` |
| `json` | The processing model's decisions as data | `JsonOutputFunctions` |

`print`, `epub` and `json` extend `web`, which means they will also accept ODD models tagged `@output="web"`. Models without `@output` apply always.

Models may use an optional `opm-` prefix on `@output` (e.g. `opm-web`) for rules
that apply only when compiling with this Python implementation. tei-publisher-lib
ignores those models. Among models that match the compile mode, the usual ODD
rule applies: the first whose conditions apply wins.

```bash
opm transform examples/tei-test.xml -t web --preview
opm transform examples/tei-test.xml -t print --preview
opm transform examples/tei-test.xml -t epub -o book.epub
opm transform examples/tei-test.xml -t markdown --preview
opm transform examples/tei-test.xml -t docx -o out.docx
opm transform examples/tei-test.xml -t typst -o out.typ
opm transform examples/tei-test.xml -t json -o out.json
```

## Choosing an ODD at transform time

All commands above will use the default configured in the `opm.toml`. You can change
the ODD with parameter `--odd`/`-d`.

```bash
# Explicit ODD (compiled on demand)
opm transform examples/tei-test.xml --preview

# Looked up from config (see Configuration)
opm transform examples/tei-test.xml -t web --preview
opm transform examples/tei-test.xml -t print --preview
opm transform examples/tei-test.xml -t typst -o out.pdf
opm transform examples/tei-test.xml -t docx -o out.docx
```

## HTML (`web`)

Full-document output is wrapped in a Jinja2 template and can include
ODD-generated CSS, a user stylesheet, and optional [tei-publisher web components](https://unpkg.com/@teipublisher/pb-components@latest/dist/api.html). See [Templates & CSS](templates-and-css.md).

```bash
opm transform data/sample.xml \
  --preview --template templates/tufte.html.j2
```

## Print (paged media)

`print` emits HTML like `web`, but targets a print processor rather than a web browser. Therefore you would
use CSS Paged Media for the styling, which allows you to set page size, margins, footnotes etc. On the command
line, [PrinceXML](https://www.princexml.com/) works well for converting the resulting HTML to PDF.

```bash
opm transform examples/tei-test.xml -t print -o print.html
prince print.html -o print.pdf
```

`print` output mode wraps the generated content into an HTML template, which can be customized. For example,
the docbook example does that:

```bash
cd examples/docbook
opm transform data/doc/quickstart.xml -t print --preview
```

## EPUB

`epub` compiles with EPUB-oriented HTML behaviours (synthetic fragment ids,
`epub:type` pagebreaks, footnote asides) and packages the result as an EPUB 3
ZIP (mimetype, OPF, `nav.xhtml`, NCX, chapters, CSS, images). Chapters are
selected with the same `[chunking]` rules used by `opm chunk` (default:
TEI `tei_div_chunks` / DocBook `dbk_section_chunks` at depth 1).

`[transform.epub]` may override that selection with its own `xpath`, `selector`
or `depth`: the EPUB contents might be very different from the browser-based reading view. For example, `examples/serafin` chunks only the source text and fills the
translation into a second panel in the HTML preview, but not in the EPUB. A page-milestone
selector (`tei_pb_chunks`) is always replaced by divisions, since a EPUB readers repaginate anyway.

```bash
opm transform examples/tei-test.xml -t epub -o book.epub
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

Rules a project wants in *every* view belong in the ODD stylesheet.
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
manifest, since an EPUB OPF entry without a file makes the package invalid.

## Markdown

```bash
opm transform examples/tei-test.xml -t markdown --preview
```

`--preview` renders the Markdown in the terminal with [Rich](https://rich.readthedocs.io/).

## DOCX

DOCX is binary, so the `-o` flag is required to write the file (it cannot be previewed). A custom Word
`.docx` can be supplied as a **style template** via the CLI `--template` flag or in the configuration file under
`[transform.docx] template`. Its paragraph and character styles are reused in
the output. If none is given, the packaged `default.docx` is used. Missing built-in styles (`Hyperlink`,
`footnote text`, `footnote reference`) are injected automatically.

```bash
opm transform examples/tei-test.xml -t docx -o report.docx
```

## Typst

Typst output uses a `.typ.j2` Jinja2 template configured under `[transform.typst]`.
Project templates include `templates/book.typ.j2` (TEI) and
`templates/docbook.typ.j2` (DocBook UI classes)<!--; both use ilm-->. The packaged
fallback is `default_document.typ.j2`.

```bash
opm transform examples/tei-test.xml -t typst -o out.typ
```

The resulting `.typ` file you can then process with

```bash
typst compile out.typ --open
```

### PDF

With the [`typst`](https://typst.app/open-source/) command on your `PATH`,
`opm` can run `typst compile` for you. Name a `.pdf` output file, or preview:

```bash
opm transform examples/tei-test.xml -t typst -o out.pdf
opm transform examples/tei-test.xml -t typst --preview   # Typst opens the PDF
```

Image paths in the output are taken from the XML as they are and resolve
against the document's directory; Typst refuses a path that leaves it (`../`).
From Python, `transform_file()` returns the Typst source; pass it to
`opm.typst_compile.compile_pdf()` for the PDF.

Refer to the [Typst documentation](https://typst.app/docs/) for more information about running the command.

## JSON

The flag `-t json` does not render the document. It records **what the processing model
did to it**: which behaviour ran for each element, which model was fired, where the
element came from, and what text it contributed.

```bash
opm transform examples/tei-test.xml -t json -o out.json
```

!!! note "Not the same as `opm chunk --format json`"

    `opm chunk --format json` wraps rendered **HTML** in a JSON envelope for
    static site generators. `-t json` emits structured **data** about the
    transformation itself. They serve different consumers.

Every element that reaches a behaviour produces a record — inline and
`pass_through` ones included, and this output is very useful for debugging.

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

`xpath` names its elements (`/TEI/text[1]/body[1]/div[2]`) because opm resolves unprefixed names against the document's default namespace.
document:

```bash
opm transform doc.xml -x '/TEI/text[1]/body[1]/div[2]' --preview
```

Elements outside that default namespace — e.g. MathML inside TEI — keep the
positional form for those steps (`…/formula[1]/*[1]/*[1]`), since an unprefixed
step would not match them.

`line` and `col` point at the `<` of the start tag, 1-based, so a record can be
opened directly:

```bash
opm transform doc.xml -t json -o out.json
# then, for any record:  $EDITOR +84 doc.xml   /   code -g doc.xml:84:7
```

There are two things that this output format makes visible that no other output can:

**Suppressed content.** `omit`, `index` and `metadata` produce no output, so a
renderer cannot distinguish "the ODD dropped this" from "it was never in the
source". Here they leave a record marked `"suppressed": true`.

**Unmatched elements.** An element with no matching model never reaches a
behaviour at all — its text just surfaces in some ancestor. In JSON it appears
with `"behaviour": null`, so everything an ODD does not cover is findable:

```bash
opm odd coverage doc.xml     # counts them, with a file:line for each
```

[`opm odd coverage`](coverage.md) rolls these records up across a corpus: unmatched
elements, models that never fired, models that can never fire, and elements
whose spec exists but whose predicates were all false.

### Choosing which channel to inspect

`-t json` on its own records the **web** channel's decisions. That is the wrong
answer when the ODD you are debugging targets another one — typst and docx
models in particular are the hardest to eyeball, since there is no browser to
open. `--channel` picks the channel whose models participate:

```bash
opm transform doc.xml -t json --channel typst -o typst-decisions.json
opm transform doc.xml -t json --channel docx  -o docx-decisions.json
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
opm transform doc.xml -t json               -o web.json
opm transform doc.xml -t json --channel typst -o typst.json
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
inherited one, every model of an element you redeclare is local; the
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
the document uses, models the ODD declares for them, and no match. That reading
is what [`opm odd coverage`](coverage.md) automates, across a whole corpus and with
the local/inherited split applied.

For building a search index from this data, see
[Search indexing](search-indexing.md).

## Adding a new format

Subclass [`ProcessingModelFunctions`](../api/output-functions.md) and implement
its behaviour methods. Because the generated transform code is format-agnostic,
the same compiled module works with any implementation you provide. Modes that
extend HTML (like `print`) typically subclass `HtmlOutputFunctions` and override
only the behaviours that differ.
