# Licensing

Open Processing Model (`opm`) is licensed to the public under the GNU Affero General Public
License, version 3 or later. The licence text is in [LICENSE](LICENSE), reproduced verbatim
and unmodified.

Two further instruments, both granted by e-editiones, sit in this file:

- **[Part A — Additional Permissions](#part-a--additional-permissions)**, granted under
  section 7 of the AGPL to everyone who receives `opm`.
- **[Part B — Member Licence Grant](#part-b--member-licence-grant)**, offering `opm` under
  the LGPL to members of e-editiones as an alternative to the AGPL.

Neither modifies the AGPL itself. Both are versioned and dated separately below, because
they change on different schedules: Part A is meant to be stable, since recipients rely on
it, while Part B follows the terms of membership. Cite them as *Part A §2*, *Part B §4*.

---

## Part A — Additional Permissions

**Version 1.0, 7 September 2026. DRAFT — not reviewed by counsel.**

This Part grants additional permissions under section 7 of the GNU Affero General Public
License, version 3, in respect of Open Processing Model (`opm`), copyright © 2026
e-editiones and contributors.

These permissions are granted in addition to the rights granted by the AGPL and do not
limit them. As section 7 provides, a recipient may remove these permissions from a copy
they convey; e-editiones cannot withdraw them from copies already conveyed.

### Definitions

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
and their stylesheets, which §4 below excludes from the CC0 dedication and leaves under
CC BY 4.0.

### 1. Independent invocation

You have permission to convey a work that invokes `opm` only as a separate process — by
executing the `opm` command with arguments and consuming its output — without that work
being required to be licensed under the AGPL, and without the obligations of sections 5,
6 and 13 of the AGPL applying to it.

This permission does not extend to a work that loads `opm` into its own process, whether
by import, embedding, or any other in-process mechanism, except as provided in §2 and §3.

### 2. Generated Modules

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

### 3. Extension Modules

You have permission to convey and execute Extension Modules under terms of Your choosing,
notwithstanding that they are loaded into the same interpreter as `opm`, and their use
does not cause Your work to be required to be licensed under the AGPL.

This permission does not apply to an Extension Module into which substantial portions of
`opm`'s own source have been incorporated.

### 4. Scaffolding Files

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
stylesheets and the example ODDs derived from them, is maintained upstream in TEI
Publisher. They are licensed **CC-BY-4.0**, copyright 2017–2026 e-editiones and individual
contributors, and build on TEI Consortium material that is itself CC BY 3.0 /
BSD-2-Clause, as each states in its own `teiHeader/publicationStmt/availability`.

Their exclusion from the CC0 dedication above is deliberate rather than an accident of
ownership. These models are the work of many hands over many years and rest on material
whose own licences require attribution, so no dedication to the public domain could
describe them accurately. What CC BY asks in return is that attribution: keep the
copyright and licence statement in the `teiHeader`, and credit e-editiones and its
contributors — and the TEI Consortium for the TEI material underneath — where You
redistribute an ODD or a modified version of it.

This reaches further than the files themselves. An ODD that names one of them in
`schemaSpec/@source` inherits its processing models, so a Generated Module compiled from
such an ODD incorporates CC BY-licensed material — including the `custom.odd` that
`opm init` writes by default. CC BY carries no copyleft, so this places no licensing
condition on Your own work: the permission in §2 above applies as written, and attribution
is the whole of what these models ask.

*The source documents.* The texts under `examples/*/data/` carry their own provenance and
rights, described in each example's README and in
[LICENSES/LicenseRef-SourceDocuments.txt](LICENSES/LicenseRef-SourceDocuments.txt).

[REUSE.toml](REUSE.toml) records all of this in machine-readable form, including for files
whose format cannot carry a header.

### 5. What these permissions do not cover

The AGPL applies in full, without exception, to:

- modified versions of `opm` itself, whether conveyed or offered to users over a network;
- works that incorporate `opm`'s source, in whole or in part, including vendored copies;
- works that load `opm` in-process other than through a Generated Module or an Extension
  Module as defined above.

Removing or altering the copyright notices and licence information in `opm` requires a
separate written agreement with e-editiones: `info@e-editiones.org`.

### 6. General

These permissions apply to the release of `opm` they are published with and to every later
release unless that release says otherwise. If any permission here is held unenforceable,
the remaining permissions stand and the AGPL applies unmodified to the part affected.
Nothing here grants rights in the names or logos of e-editiones, TEI Publisher or Open
Processing Model.

Members of e-editiones may instead rely on Part B below, which offers `opm` under the LGPL
and covers the in-process and vendoring cases these permissions leave under the AGPL. Both
are available; You may rely on whichever suits a given copy.

---

## Part B — Member Licence Grant

**Version 1.0, 7 September 2026. DRAFT — not reviewed by counsel.**

`opm` is licensed to the public under AGPL-3.0-or-later, with the additional permissions in
Part A above. This Part sets out an alternative licence available to members of
e-editiones.

### 1. The grant

e-editiones grants to each member in good standing a licence to use, modify and convey
`opm` under the terms of the GNU Lesser General Public License, version 3 or later
(LGPL-3.0-or-later), as an alternative to the AGPL.

The grant is automatic on becoming a member. No application, signature or key is required.
On request, e-editiones will issue a written confirmation naming the member and the
covered releases, for members whose institutions require one for their records.

### 2. Which releases are covered

The grant covers every release of `opm` published during the member's membership.

For those releases the licence is perpetual and irrevocable: it survives the end of
membership, and the member and its downstream recipients keep their LGPL rights in them
indefinitely.

Releases published after membership ends are not covered and are available under the AGPL
like any other public release.

### 3. What this changes in practice

Under the LGPL, in contrast to the AGPL:

- an application that uses `opm` as a library may remain proprietary; and
- a hosted service built on `opm` owes its users nothing corresponding to AGPL section 13.

### 4. What still applies

The LGPL's own obligations remain in force. In particular, under section 4:

- modifications to `opm` itself must be made available under the LGPL when conveyed;
- recipients of your application must be able to substitute their own build of `opm`. In
  Python this is satisfied by depending on the published package rather than vendoring a
  patched copy — and, where you do ship a modified `opm`, by providing its source. Where
  the substitution cannot happen at install time at all — a vendored copy, a frozen binary,
  an image the user cannot alter — section 4d0 applies instead, and your application must
  be shipped in a form that permits relinking against a modified `opm`;
- copyright and licence notices must be preserved.

### 5. Onward distribution

This grant is a genuine LGPL licence. A member may therefore convey copies received under
it to third parties under the LGPL, including publicly, and those recipients acquire LGPL
rights directly. e-editiones accepts this consequence knowingly.

Membership is worth having for currency, support, participation in the roadmap and
assurance about future releases — not for exclusivity, which no LGPL grant could provide.

### 6. What requires a separate agreement

- Removing or altering copyright notices and licence information.
- Conveying `opm`, or a work containing it, on terms that do not satisfy the LGPL.

Write to `info@e-editiones.org`.

### 7. Relationship to the public licence

This grant does not modify, replace or restrict the AGPL licence under which `opm` is
published, nor the additional permissions in Part A. A member may rely on either licence,
and may rely on different licences for different projects.

*Plain-language summary; the LGPL-3.0 text governs the terms it grants. This Part is
governed by the laws of Switzerland.*

---

```
e-editiones
c/o Stadtarchiv der Ortsbürgergemeinde St.Gallen
Notkerstrasse 22
CH-9000 St. Gallen
Switzerland

info@e-editiones.org
UID CHE-474.398.996
```
