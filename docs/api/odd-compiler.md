# odd_compiler

Compile an ODD file into a transform module. `compile_odd()` is the entry point;
`CodeGenerator` / `PythonGenerator` are the code-emission backend and `load_odd()`
parses the ODD XML into a `ParsedOdd`.

::: opm.odd_compiler

## Parsed ODD representation

::: opm.odd_compiler.parse_odd.ParsedOdd
