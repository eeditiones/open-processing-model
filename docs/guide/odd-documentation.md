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
opm odd document --tei -o tei-ref --force --preview
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