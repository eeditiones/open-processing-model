# ODD documentation

`opm odd document` builds a static HTML site from an **ODD**: reference pages
for each element, class, macro and datatype. You can also use it to generate
the TEI Guidelines themselves.

Print, PDF and Markdown channels are planned; HTML is the first output.

## Output

By default the site is written to `odd/<schemaSpec ident>` (the ODD's
`schemaSpec/@ident`). Pass `-o` to put it somewhere else.

## Use

```bash
# An ODD (schema specs, processing models, or both). TEI-targeting ODDs
# download the TEI schema into the user cache (~2 MB compressed); it is not
# shipped in the wheel.
opm odd document my.odd --force --preview

# TEI itself, no customization
opm odd document -o tei-ref --force --preview
```

ODDs which are real TEI customizations will always be merged with the full TEI ODD before being
processed. `opm` in this case uses a pinned TEI release, specified in the `tei-version` file
of this repository.

If your ODD contains prose, i.e. documentation chapters, it will be
extracted and displayed first.

Chapters and their subdivisions are numbered as in the published TEI
Guidelines: arabic in the body (`1`, `1.2`, `1.2.1`), lowercase roman with a
trailing dot in the front matter (`iv.`, `iv.1.`), and lettered in the back
matter (`Appendix A`, `Appendix A.1`). The index at each level is the
division's position among its siblings, so a title page carries no number, and
neither do the pages `opm` adds itself. The A–Z catalogs are appendices, in the
order they appear in the sidebar.

One can use ODD to process non-TEI documents: `opm` currently supports
Docbook and JATS out of the box. Obviously calling `opm odd document` on any of those ODDs will 
result in a flat structure as the schema is not expressed in the ODD: consequently the _contained by_ 
and _may contain_ sections will be empty.

## How does it work?

ODD is a complex format, containing a lot of cross-references between different parts of the specification. 
`opm odd document` therefore explodes the ODD before rendering: it resolves class memberships, attribute lists, references etc.
and outputs them as expanded lists. The resulting document can then be processed as a sequential text like any _normal_ TEI document.

If you would like to read the exploded ODD, e.g. to customize the presentation, use the `opm odd prepare` command:

```bash
opm odd prepare my.odd
```

By default this writes a file, `schema.xml`, into the current directory, containing the exploded ODD. Pass parameter `-o` to select
a different output location.

## Customizing the output

Everything `opm odd document` builds with can be copied into a project and
edited there:

```bash
opm init my-docs --example odd
cd my-docs
opm odd document my-odd.odd --force --preview
```

Omitting `my-odd.odd` generates the full TEI P5 guidelines in its latest version.
`opm` caches the full guidelines ODD anyway, because it needs it as a base.
In a clone of the repository, `examples/odd` is that project: change into it
and the same commands work there.

The project holds the processing ODD (`odd/tagdocs.odd`), the two chunking
runs in `opm.toml` — the text, then one reference page per spec — the page
template and the site's stylesheet and scripts (`templates/`), and the sidebar
list (`templates/nav.xml`). `[document]` in `opm.toml` says what to document, the TEI Guidelines
unless it names a `source`; SOURCE on the command line still wins.

## Generating a PDF

Inside a documentation project, you can also combine `prepare` with `transform` to generate a PDF (using `typst` output mode):

```bash
opm odd prepare -o schema.xml
opm transform schema.xml -t typst -o docs.pdf   # --preview opens it, -o docs.typ keeps the source
```

The text comes first, in document order, then the reference part: each
catalog appendix lists its elements, classes or macros in full, in A–Z order.
`-p part=reference` prints only the reference part, `-p part=text` only the
text:

```bash
opm transform schema.xml -t typst -p part=reference -o reference.pdf # just the reference pages
opm transform schema.xml -t typst --xpath 'id("HD")' -o teiHeader.pdf # just one chapter
```

## Generating markdown

The same approach also works to output markdown:

```bash
opm odd prepare -o schema.xml
opm transform schema.xml -t markdown -o docs.md # or --preview
opm transform schema.xml -t markdown --preview -p part=reference # just the reference pages
opm transform schema.xml -t markdown --xpath 'id("HD")' -o teiHeader.md # just one chapter
```

## JSON for a static site generator

Inside a documentation project, the same runs produce JSON:

```bash
opm odd prepare -o schema.xml          # the tree `odd document` chunks
opm chunk schema.xml --format json     # both runs, links between them resolved
```

## Example: the TEI Guidelines

The [TEI Guidelines](../guidelines/index.html) published alongside this
documentation are the unedited output of

```bash
opm odd document
```

`scripts/build_guidelines_docs.sh` runs it into `docs/guidelines/`, from where
the documentation build copies it verbatim. The directory is generated, not
tracked: run the script once if you want the subsite in a local `zensical
serve`.
