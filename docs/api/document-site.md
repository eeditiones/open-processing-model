# document_site

Build a static HTML documentation site from a compiled ODD or Guidelines
document.

::: opm.document_site

## Expanding the tree

Before rendering, everything a page shows that depends on the schema as a
whole is written into the prepared tree as plain TEI: the relations of each
spec, the A–Z catalogs, the table of contents, heading numbers, chapter
navigation and link targets. `opm odd prepare` writes that tree out.

::: opm.odd_expand

## `tp:` function

The one spec-specific function `tagdocs.odd` still calls; it formats the node
being rendered.

::: opm.runtime.spec_xpath_functions
