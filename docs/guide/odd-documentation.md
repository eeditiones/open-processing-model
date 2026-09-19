# ODD documentation

`opm odd document` builds a static HTML site from an **ODD**: reference pages
for each element, class, macro and datatype, with Contained by / May contain /
Members computed from the class and content-model graph, and processing models
listed on each `elementSpec`. Nested TEI in `desc`, `gloss` and `remarks` is
rendered through the packaged `tagdocs.odd` processing model. The same ODD
builds the Guidelines table of contents (`$parameters?mode='toc'`), the site
sidebar (`mode='nav'`), empty `ptr` labels, and `specDesc` lookup against
`$parameters?root` (the compiled schema).

Internally the site is an `opm chunk` run. `compile_schema` merges the ODD,
a short prepare step stamps `xml:id="ref-{ident}"` on specs and injects catalog
stubs, and the packaged [`resources/document/opm.toml`](../../src/opm/resources/document/opm.toml)
splits the tree with `file_pattern = "{xml_id}.html"`. The spec graph stays in
[`SpecIndex`][opm.spec_index.SpecIndex] and is called from tagdocs as `tp:contained_by`,
`tp:may_contain`, `tp:members`, `tp:used_by` and related helpers.

This is the same job the [TEI Stylesheets](https://github.com/TEIC/Stylesheets)
`odd2html` / tagdocs pipeline does, implemented as a processing-model transform
and aimed at a static site. An ODD may declare a schema, processing models, or
both; `schemaSpec/@source` is followed in either case.

Print, PDF and Markdown channels are planned; HTML is the first output.

## Inputs

By default the site is written to `odd/<schemaSpec ident>` (the ODD's
`schemaSpec/@ident`). Pass `-o` to put it somewhere else.

```bash
# An ODD (schema specs, processing models, or both). TEI-targeting ODDs
# download the TEI schema into the user cache (~2 MB compressed); it is not
# shipped in the wheel.
opm odd document my.odd --force --preview

# Already-compiled specs (TEI p5subset, a Guidelines p5.xml, or a Specs/ directory)
opm odd document path/to/p5subset.xml -o tei-ref --force
opm odd document path/to/p5.xml -o guidelines --force   # chapters + reference
opm odd document path/to/TEI/P5/Source/Specs -o tei-ref --force

# TEI itself, no customization
opm odd document --tei -o tei-ref --force --preview
```

`--source` points at a local schema (p5subset or another compiled ODD) when you
do not want the download. `--offline` refuses to fetch. `--lang` selects
`xml:lang` on gloss/desc/remarks (default `en`).

Chapter prose from the input is always kept, so a Guidelines `p5.xml` brings
its chapters with it. `--tei` publishes the TEI Guidelines chapters (AB, CO,
…) as well, because the downloaded TEI schema carries the prose alongside the
specs — one file, one request.

A customization documents itself: merging onto TEI does not pull TEI's 39
chapters into your site. To read those, document TEI separately with `--tei`.

A Guidelines `p5.xml` (prose chapters *and* embedded specs) also writes one HTML
page per top-level `div` (`AB.html`, `CO.html`, …) and rewrites internal
`ptr` / fragment links between chapters. Each prose chapter has previous/next
links to the neighbouring chapter (front, body, then back).

## Inheritance

Compilation walks `schemaSpec/@source` parent-first, the same chain
`opm transform` uses. A project ODD that sources `teipublisher.odd` therefore
documents teipublisher's models plus local overlays. `mode="change"` keeps the
parent's content model and attributes and replaces processing models when the
child declares any; `mode="add"` on an ident that already exists is treated the
same way.

Most TEI ODDs never name a schema release. If `schemaSpec/@ns` is absent or is
the TEI namespace, `opm odd document` merges the ODD onto the cached TEI schema
so `moduleRef` and contained-by / may-contain stay complete — including Roma
customizations that carry `@module` on local specs but no `@source`. JATS
(`ns=""`) and DocBook set another namespace and do not pull the TEI schema.

`--tei` documents TEI alone, or forces a TEI base when the heuristic would not.

opm ships one TEI snapshot, tracking the latest release, cached at
`tei/p5all.xml` under the user cache. An ODD pinning an older `TEI/@version`
is compiled against that snapshot and warns, since a customization written for
an earlier TEI may reference specs the current release no longer has. To
compile against an exact release, pass `--source` with a `p5subset.xml` for it
from the [Vault](https://tei-c.org/Vault/P5/).

## What the site contains

| Page | Contents |
| --- | --- |
| `index.html` | Opening `titlePage` / lead paragraph (if the ODD has one), Front Matter / Text Body / Back Matter chapter lists, and catalog links |
| `ref-{ident}.html` | One page per element, class, macro, datatype |
| `REF-ELEMENTS.html` | A–Z element index |
| `REF-CLASSES-MODEL.html` / `REF-CLASSES-ATTS.html` | Model and attribute classes |
| `REF-ATTS.html` | Attribute name → defining class or element |
| `REF-MACROS.html` | Macros and datatypes |
| `idents.json` | Ident list for the header search box |
| `document.css` / `fonts.css` / `fonts/` | Stylesheet and the self-hosted webfonts it imports |
| `search.js` / `theme.js` | Header search, and the light / dark toggle |

Element pages follow the woven-ODD layout: module, inherited attributes
(nested att-classes, locally overridden names struck through), member of,
contained by, may contain, processing models, notes, examples, Schematron,
content model. Each is a section of its own; the "on this page" rail is filled
in the browser from those headings.

## Appearance

The site carries the TEI Guidelines design system. Prose is set in Source Serif
4, chrome in Work Sans, and anything literally XML in Fira Code; the three are
self-hosted under `fonts/`, so a published site makes no third-party requests.
Inline conventions follow one rule — literal XML is monospace, a place in the
document is sans, a concept stays in the serif — and amber marks only what is
clickable, which is why element references are amber and attribute references
are not.

Colours and metrics are CSS custom properties on `:root` in `document.css`
(`--doc-paper`, `--doc-ink`, `--doc-amber`, `--doc-rule`, `--doc-serif`,
`--doc-mono`, …), redefined under `:root[data-theme="dark"]`. To restyle a
generated site, override those rather than the rules beneath them. The header
toggle writes `data-theme` on `<html>` and remembers the choice; with nothing
stored, `prefers-color-scheme` decides.

The header's version line comes from `editionStmt/edition` in the source's
`teiHeader`, and the footer line from the first `availability/licence`; both are
omitted when the document has neither.

## Python API

```python
from opm.document_site import build_document_site
from opm.odd_schema import compile_schema
from opm.spec_index import SpecIndex

compiled = compile_schema('my.odd')
index = SpecIndex.from_tree(compiled.tree)
p = index.element('p')
p.contained_by  # parents, grouped later with p.grouped(...)
p.may_contain
p.models        # behaviour, predicate, @output, params, template

site = build_document_site(compiled, f'odd/{compiled.ident}')
```

[`compile_schema`][opm.odd_schema.compile_schema] is a small odd2odd: `moduleRef`
subset, then `mode` of `add` / `change` / `delete` / `replace` on specs,
including processing models. [`SpecIndex`][opm.spec_index.SpecIndex] precomputes
the inverse relations the Stylesheets emit from `memberOf` and content models.
