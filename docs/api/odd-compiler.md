# odd_compiler

Compile an ODD file into a transform module. `compile_odd()` is the low-level
entry point used by the on-demand cache; `CodeGenerator` / `PythonGenerator` are
the code-emission backend and `load_odd()` parses the ODD XML into a
`ParsedOdd`.

For day-to-day use prefer [`opm.odd_cache.ensure_compiled_module`](#odd-cache),
which writes into the platform user cache and skips recompilation when inputs
are unchanged.

::: opm.odd_compiler

## Parsed ODD representation

::: opm.odd_compiler.parse_odd.ParsedOdd

## Odd cache

::: opm.odd_cache
