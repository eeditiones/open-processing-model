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
opm odd document --guidelines -o tei-ref --force --preview
```

One can use ODD to process non-TEI documents: `opm` currently supports
Docbook and JATS out of the box. Obviously calling `opm odd document` on any of those ODDs will 
result in a flat structure as the schema is not expressed in the ODD: consequently the _contained by_ 
and _may contain_ sections will be empty.

ODDs which are real TEI customizations will always be merged with the full TEI ODD before being
processed. `opm` in this case uses the latest TEI release. If the ODD to be document does reference
a different version (`@version` tag on the `TEI` root element), a warning will be printed.

If your ODD contains prose, i.e. documentation chapters, it will be
extracted and displayed first.

Chapters and their subdivisions are numbered as in the published TEI
Guidelines: arabic in the body (`1`, `1.2`, `1.2.1`), lowercase roman with a
trailing dot in the front matter (`iv.`, `iv.1.`), and lettered in the back
matter (`Appendix A`, `Appendix A.1`). The index at each level is the
division's position among its siblings, so a title page carries no number, and
neither do the pages `opm` adds itself. The A–Z catalogs are appendices, in the
order they appear in the sidebar.

## Example: the TEI Guidelines

The [TEI Guidelines](../guidelines/index.html) published alongside this
documentation are the unedited output of

```bash
opm odd document --guidelines
```

`scripts/build_guidelines_docs.sh` runs it into `docs/guidelines/`, from where
the documentation build copies it verbatim. The directory is generated, not
tracked: run the script once if you want the subsite in a local `zensical
serve`.
