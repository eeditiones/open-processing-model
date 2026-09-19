# odd_schema

Load an ODD and compile it by following `schemaSpec/@source` (schema specs and
processing models). A TEI-targeting ODD (`schemaSpec/@ns` absent or the TEI
namespace) is merged onto cached `p5subset.xml` (`TEI/@version` selects a Vault
release). JATS / DocBook set another `@ns` and skip that base. `--tei` /
`use_tei` documents TEI alone; it is not shipped in the wheel.

::: opm.odd_schema
