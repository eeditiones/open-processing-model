# Additional Permissions

**DRAFT — not reviewed by counsel.**

This file grants additional permissions under section 7 of the GNU Affero General Public
License, version 3, in respect of Open Processing Model (`opm`), copyright © 2026
e-editiones and contributors.

These permissions are granted in addition to the rights granted by the AGPL and do not
limit them. As section 7 provides, a recipient may remove these permissions from a copy
they convey; e-editiones cannot withdraw them from copies already conveyed.

## Definitions

**"opm"** means the software licensed under the AGPL in this repository, including
`opm.runtime`.

**"Generated Module"** means a file produced by `opm`'s compiler from an ODD or other
input supplied by You — the Python transform module emitted by
`opm.odd_compiler.codegen`, the Typst module emitted by `opm.odd_compiler.typst_generator`,
the CSS emitted from an ODD's `<tagsDecl>`, and any bytecode or cache entry mechanically
derived from one of them. A Generated Module is the compiled expression of Your input,
together with the module preamble, dispatch scaffolding, handler skeletons and comparable
boilerplate that the compiler copies from its own source into its output. The Python
module imports `opm.runtime` at execution time.

**"Extension Module"** means Python code that You author and register through `opm.toml`
for use as an XPath extension, or load through `[project] pythonpath` for the same
purpose.

**"Scaffolding Files"** means the templates, stylesheets, configuration and sample
documents written into a working directory by `opm init`, other than the processing models
and their stylesheets identified in section 4, which are not e-editiones' to release.

## 1. Independent invocation

You have permission to convey a work that invokes `opm` only as a separate process — by
executing the `opm` command with arguments and consuming its output — without that work
being required to be licensed under the AGPL, and without the obligations of sections 5,
6 and 13 of the AGPL applying to it.

This permission does not extend to a work that loads `opm` into its own process, whether
by import, embedding, or any other in-process mechanism, except as provided in sections 2
and 3.

## 2. Generated Modules

e-editiones' position is that a Generated Module is not a derivative work of `opm`: it is
the compiled expression of input You supplied, and the compiler's own contribution to it
is boilerplate emitted mechanically into every such module.

For the avoidance of doubt, and whatever the status of that boilerplate, You have
permission to convey and execute Generated Modules under terms of Your choosing,
notwithstanding that they import `opm.runtime` at execution time and that they contain
fragments the compiler copied from its own source; and the resulting runtime combination
does not cause Your work to be required to be licensed under the AGPL. This permission
extends to the loading and execution of a Generated Module through `opm`'s ordinary
compile-and-load interface.

This permission does not apply to a Generated Module into which substantial portions of
`opm`'s own source have been incorporated, beyond the boilerplate the compiler emits.

## 3. Extension Modules

You have permission to convey and execute Extension Modules under terms of Your choosing,
notwithstanding that they are loaded into the same interpreter as `opm`, and their use
does not cause Your work to be required to be licensed under the AGPL.

This permission does not apply to an Extension Module into which substantial portions of
`opm`'s own source have been incorporated.

## 4. Scaffolding Files

Scaffolding Files are additionally released by e-editiones under CC0-1.0. You may use,
modify and license them without restriction and without attribution. Each carries an SPDX
header to that effect, and copying them into Your project has no effect on the licensing
of Your project.

In the `opm` source distribution these are: everything under
`src/opm/resources/scaffold/`; `src/opm/resources/templates/`, including
`default.docx`; and the templates, stylesheets, configuration, extension stubs and helper
scripts of the example projects under `examples/`.

**Two exclusions, both material.**

*The stock processing models.* Every ODD `opm` ships — `teipublisher.odd`,
`docbook.odd` and `jats.odd` under `src/opm/resources/odd/` — together with their
stylesheets and the example ODDs derived from them, comes from TEI Publisher. They are
licensed **CC-BY-4.0**, copyright eXistSolutions GmbH, as each states in its own
`teiHeader/publicationStmt/availability`. e-editiones does not hold those rights and
cannot dedicate them to the public domain; nothing in this document or in
[LICENSE-MEMBER-GRANT.md](LICENSE-MEMBER-GRANT.md) purports to. What CC BY asks in return
is attribution: keep the copyright and licence statement in the `teiHeader`, and credit
eXistSolutions GmbH where You redistribute the ODD or a modified version of it.

This reaches further than the files themselves. An ODD that names one of them in
`schemaSpec/@source` inherits its processing models, so a Generated Module compiled from
such an ODD incorporates CC BY-licensed material — including the `custom.odd` that
`opm init` writes by default. CC BY carries no copyleft, so this places no licensing
condition on Your own work: the permission in section 2 above is e-editiones' to give and
it gives it, and the attribution CC BY asks for is all that eXistSolutions' copyright
adds.

*The source documents.* The texts under `examples/*/data/` carry their own provenance and
rights, described in each example's README and in
[LICENSES/LicenseRef-SourceDocuments.txt](LICENSES/LicenseRef-SourceDocuments.txt).

[REUSE.toml](REUSE.toml) records all of this in machine-readable form, including for files
whose format cannot carry a header.

## 5. What these permissions do not cover

The AGPL applies in full, without exception, to:

- modified versions of `opm` itself, whether conveyed or offered to users over a network;
- works that incorporate `opm`'s source, in whole or in part, including vendored copies;
- works that load `opm` in-process other than through a Generated Module or an Extension
  Module as defined above.

Removing or altering the copyright notices and licence information in `opm` requires a
separate written agreement with e-editiones: `info@e-editiones.org`.

## 6. General

These permissions apply to the release of `opm` they are published with and to every later
release unless that release says otherwise. If any permission here is held unenforceable,
the remaining permissions stand and the AGPL applies unmodified to the part affected.
Nothing here grants rights in the names or logos of e-editiones, TEI Publisher or Open
Processing Model.

Members of e-editiones may instead rely on
[LICENSE-MEMBER-GRANT.md](LICENSE-MEMBER-GRANT.md), which offers `opm` under the LGPL and
covers the in-process and vendoring cases these permissions leave under the AGPL. Both are
available; You may rely on whichever suits a given copy.
