# ODD documentation

While OPM obviously focuses on the processing model parts of the ODD, the specification was initially created for a different purpose: to formally describe a TEI customization, i.e.
the elements a project uses, which
attributes they carry, what values are allowed. It will often also include a few chapters of
prose explaining the encoding practice (see this [example](https://github.com/eeditiones/open-processing-model/blob/main/examples/odd/data/tei_psalmy.odd)). The TEI guidelines themselves are essentially one huge ODD.

For the people who encode texts, this
information is only useful if they can read it comfortably. `opm odd document`
turns an ODD into readable documentation, just like the reference pages of the
TEI Guidelines: one page for every element, class, macro and datatype, together
with any chapters the ODD contains.

The result is a small website by default. You can also produce a single PDF,
Markdown or EPUB file from the same ODD, for example to print it or to send it
to the members of your project.

## Generating documentation

To document your own customization, pass the ODD file to `opm odd document`:

```bash
opm odd document my.odd --preview
```

`opm` reads the ODD, builds the site and, because of `--preview`, opens it in
your browser. The site is written into a folder named after your
customization: `odd/` followed by the `@ident` of the ODD's `schemaSpec`. Use
`-o` to choose another folder. If the folder already exists, `opm` asks before
replacing it; add `--force` to replace it without asking.

Without an ODD, `opm` produces the full TEI guidelines:

```bash
opm odd document -o tei-ref --preview
```

!!! note "Where does the TEI schema come from?"
    Most ODDs only describe the changes they make to TEI: they remove some
    elements, restrict others, add a few attributes. To show the complete
    picture, `opm` combines your ODD with the full TEI schema. It downloads
    that schema (about 2 MB) the first time it needs it and keeps a copy for
    later. `opm` always uses the same TEI release (currently 4.12.0), so your
    documentation does not change unexpectedly when a new TEI version comes
    out.

## What the documentation contains

If your ODD contains prose, such as chapters describing your encoding
guidelines, these chapters come first. They are numbered the way the TEI
Guidelines number theirs: chapters in the main part get arabic numbers (`1`,
`1.2`, `1.2.1`), front matter gets lowercase roman numerals (`iv.`, `iv.1.`),
and the back matter gets letters (`Appendix A`, `Appendix A.1`). A title page
has no number, and neither do the pages `opm` adds itself.

After the chapters follows the reference part. There is one page for every
element, class, macro and datatype, listing its attributes, what it may
contain, where it may appear, and examples. Alphabetical lists of all
elements, classes and macros appear as appendices, in the same order as in the
sidebar of the site.

ODD is not limited to TEI: `opm` also ships ODDs for DocBook and JATS. You can
document those as well, but their ODDs do not describe a schema, only how to
display the documents. The pages will therefore stay rather empty: the
sections telling you what an element may contain and where it may appear have
nothing to show.

## A PDF, Markdown or EPUB file

To get a single file instead of a website, add `-t` followed by the kind of
file you want:

```bash
opm odd document my.odd -t typst      # a PDF
opm odd document my.odd -t markdown   # a Markdown file
opm odd document my.odd -t epub       # an e-book
```

The file is named after your customization, just like the folder of the site,
and is written to the current folder. Use `-o` to give it another name.
`--preview` opens the result right away.

PDFs are typeset with [Typst](https://typst.app), which needs to be installed
on your computer. If you would rather look at, or edit, what `opm` hands to
Typst, give the output a name ending in `.typ`, for example `-o my.typ`.

### Only part of the documentation

Sometimes you need only the reference pages, or a single chapter. This takes
two steps. First, ask `opm` to prepare the documentation and save it in a
file:

```bash
opm odd prepare my.odd -o schema.xml
```

Then transform the prepared file, choosing what to include:

```bash
opm transform schema.xml -t typst -p part=reference -o reference.pdf
opm transform schema.xml -t typst -p part=text -o chapters.pdf
opm transform schema.xml -t typst --xpath 'id("HD")' -o teiHeader.pdf
```

`part=reference` keeps only the reference pages, `part=text` only the
chapters. `--xpath 'id("HD")'` selects a single chapter by its `xml:id`, here
the chapter with the identifier `HD`. The same works with `-t markdown`.

## Changing the look of the documentation

Everything `opm` uses to build the documentation can be copied into a project
of your own and changed there. Create such a project with:

```bash
opm init my-docs --example odd
cd my-docs
opm odd document my.odd --preview
```

Inside the project, `opm odd document` uses the project's files rather than
the ones built into `opm`. The most important ones are:

- `odd/tagdocs.odd`, the ODD whose processing models decide how each part of
  the documentation is displayed;
- `templates/`, which holds the page template of the website, its stylesheets
  and scripts, and the template for the PDF (`tagdocs.typ.j2`);
- `templates/nav.xml`, the links shown in the sidebar;
- `opm.toml`, the settings: which ODD to document, the language of the
  documentation, and how the site is divided into pages.

If you always document the same ODD, name it in `opm.toml` under
`[document]`, with `source = "my.odd"`, and simply run `opm odd document`. An
ODD given on the command line still takes precedence.

## How it works

ODD is a dense format. A single element specification refers to classes,
which refer to other classes, which define attributes, and so on. Reading the
raw ODD, you would have to follow all these references yourself. Before it
displays anything, `opm odd document` therefore resolves them: it works out
the attributes each element inherits from its classes, which elements it may
contain and where it may appear, and writes all of this out in full. The
result is an ordinary TEI document that can be displayed from beginning to
end, like any other text.

This prepared document is also what `opm odd prepare` saves. Looking at it is
helpful if you want to change how the documentation is displayed, because it
shows exactly what `odd/tagdocs.odd` receives.

The prepared document can also feed other publishing tools. Inside a
documentation project, the following writes every page as a JSON file, which
static site generators such as Eleventy can read:

```bash
opm odd prepare -o schema.xml
opm chunk schema.xml --format json
```

## Example: the TEI Guidelines

The [TEI Guidelines](../guidelines/index.html) published alongside this
documentation were created with nothing more than

```bash
opm odd document
```

!!! note "For contributors"
    `scripts/build_guidelines_docs.sh` writes the Guidelines into
    `docs/guidelines/`, from where the documentation build copies them. The
    folder is not part of the repository: run the script once if you want to
    see the Guidelines in a local `zensical serve`.
