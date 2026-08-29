# Output functions

`ProcessingModelFunctions` is the abstract base every output format implements.
The generated transform module calls its methods (`paragraph`, `heading`,
`block`, `inline`, …) to emit output. Subclass it to add a new output format; see
the concrete implementations for HTML, Print, Markdown, Typst, and DOCX.

## Base class and helpers

::: opm.runtime.output_functions

## HTML

::: opm.runtime.html_output_functions.HtmlOutputFunctions

## Print (paged media)

::: opm.runtime.print_output_functions.PrintOutputFunctions

## Markdown

::: opm.runtime.markdown_output_functions.MarkdownOutputFunctions

## Typst

::: opm.runtime.typst_output_functions.TypstOutputFunctions

## DOCX

::: opm.runtime.docx_output_functions.DocxOutputFunctions
