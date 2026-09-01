# License

Open Processing Model is free software, copyright © 2026 e-editiones, licensed under the
**GNU Affero General Public License, version 3 or later** (AGPL-3.0-or-later), with
additional permissions granted under section 7 of that licence.

The AGPL is the strongest of the common copyleft licences: it reaches not only software
you distribute, but software you *operate* — a web service built on `opm` owes its source
to the people using it. That is deliberate. It keeps scholarly tooling open even as it
moves onto the web, which is where editions increasingly live.

If that obligation does not fit your situation, e-editiones offers institutional members
the same software under the **LGPL**; see [Member licence](#member-licence) below.

Two documents sit alongside the licence text, and both are binding:

- [LICENSE-EXCEPTIONS.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-EXCEPTIONS.md)
  — additional permissions for everyone, covering independent invocation, generated
  transform modules, XPath extension modules, and a CC0 release of the files `opm init`
  writes.
- [LICENSE-MEMBER-GRANT.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-MEMBER-GRANT.md)
  — the LGPL grant for members.

Both are currently drafts and say so; they are being reviewed by counsel before release.

## What the licence reaches

The question is almost always the same: *does using `opm` make my project AGPL?* It
depends on how you use it, and every line below is backed either by the AGPL itself or by
a numbered permission in `LICENSE-EXCEPTIONS.md`.

| How you use `opm` | Does the AGPL reach your code? |
| --- | --- |
| `import opm` in your own program | **Yes.** In-process use creates a combined work. Your program falls under the AGPL when you distribute it or expose it over a network, except in the two cases below. |
| Running `opm transform …` as a subprocess | **No.** A command-line boundary — arguments in, files out — is arm's length, and permission 1 grants this in writing. |
| Running an unmodified `opm` internally, never exposed to anyone else | **No obligation arises.** The AGPL is triggered by conveying the software or offering it to users over a network, not by private use. |
| Hosting a service that calls `opm` in-process | **Yes — this is what §13 is for.** Your users are entitled to the Corresponding Source of the service. |
| Executing a transform module compiled from your ODD | **No.** Permission 2 releases generated modules, and the runtime combination they form with `opm.runtime`, for you to license as you wish. |
| Python XPath extension modules you register in `opm.toml` | **No.** Permission 3 covers them, even though they load in-process. |
| Templates, CSS and configuration `opm init` writes into your project | **No.** Permission 4 releases them under CC0. |
| The stock ODDs `opm init` copies, and modules compiled from them | **Not the AGPL — the GPL.** They come from TEI Publisher and are GPL-3.0-or-later; see below. |
| Vendoring a copy of `opm` into your own tree | **Yes.** Incorporating `opm`'s source is the case the permissions explicitly do not cover. |
| The HTML, DOCX, Typst or Markdown that `opm` produces | **No.** Transformation output is your content. The licence does not reach it, and e-editiones asserts no rights in it. |
| Your TEI sources, ODDs you wrote, your templates and CSS | **No.** These are your work. |

If you want to keep an application closed and still call `opm` from it, the subprocess
route is a genuine and supported option — `opm` is designed as a command-line tool first.

## Generated transform modules

Compiling an ODD produces a Python module in your user cache, which imports `opm.runtime`
when it executes. e-editiones' position is that such a module is the compiled expression
of your ODD rather than a derivative of `opm`, and permission 2 grants in writing what
follows from that: you may convey and execute generated modules under any terms you like,
and driving one through `opm`'s ordinary compile-and-load interface does not place your
program under the AGPL.

The limit is incorporation. Copy substantial parts of `opm`'s own source into a generated
module and the permission stops applying; the AGPL governs `opm` as it always did.

## XPath extension modules

Python extension modules you register through `opm.toml` are loaded into the same
interpreter, but `opm` calls them rather than the other way round. Permission 3 treats
them as your work: license them however you wish. The same limit applies — `opm` source
code copied into them stays AGPL wherever it lands.

## Files `opm init` writes into your project

`opm init` copies templates, stylesheets, configuration and a sample document into your
working directory as a starting point. Those are released under CC0 1.0 and carry an
<!-- REUSE-IgnoreStart -->`SPDX-License-Identifier: CC0-1.0`<!-- REUSE-IgnoreEnd --> header where the file format allows one. Edit them,
ship them, relicense them, drop the attribution — none of it is our business, and copying
them has no effect on the licensing of your project.

**The stock ODDs are different, and this is the one place where `opm`'s licensing is not
simply e-editiones' to decide.** All three processing models `opm` ships —
`teipublisher.odd`, `docbook.odd`, `jats.odd` — and their stylesheets come from TEI
Publisher. They are GPL-3.0-or-later, copyright eXistSolutions GmbH; each says so in its
own `teiHeader`, which is where a TEI file's licence belongs and where `opm` leaves it.
e-editiones does not hold those rights and cannot release them under CC0, under the LGPL
to members, or under a commercial licence.

That reaches past the files. ODD inheritance means an ODD naming one of them in
`schemaSpec/@source` pulls in its processing models — including the `custom.odd` that
`opm init` writes for you by default — so a transform module compiled from it incorporates
GPL-licensed material. Permission 2 is e-editiones' to give and it gives it, but it cannot
waive someone else's copyright.

For an edition published as free software, which is the usual case, this changes nothing:
the GPL and the AGPL are compatible and the obligations are ones you were meeting anyway.
It matters if you were counting on compiling a proprietary transform module — for that you
would need an ODD written independently of the TEI Publisher models, since all three
stock vocabularies carry the GPL.

The scholarly source documents under `examples/*/data/` are a third category again: they
have their own provenance, and each example's README says where its texts come from.

## Member licence

Members of e-editiones in good standing may use `opm` under the **GNU Lesser General
Public License, version 3 or later** as an alternative to the AGPL. The grant is automatic
on becoming a member and covers every release published during the membership; for those
releases it is perpetual and survives the membership ending. In practice it lifts the two
obligations that matter most to institutions:

- your application built on `opm` may remain proprietary, and
- a hosted service built on `opm` owes its users nothing under §13.

The LGPL's own conditions still apply, and they are not nothing: modifications to `opm`
itself are made available under the LGPL when you convey them, copyright and licence
notices are preserved, and your recipients must be able to substitute their own build of
`opm`. In Python the last one is usually free — depend on the published package instead of
vendoring a patched copy. If you vendor or freeze a copy anyway, §4d0 asks you to ship
your application in a form that permits relinking against a modified `opm`.

**The grant passes on, by design.** This is a genuine LGPL licence, so a member may convey
copies onward to third parties under the LGPL, including publicly, and those recipients
acquire LGPL rights directly. e-editiones accepts that consequence knowingly. Membership
is worth having for currency, support, participation in the roadmap and assurance about
future releases — not for exclusivity, which no LGPL grant could provide.

Full terms are in
[LICENSE-MEMBER-GRANT.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-MEMBER-GRANT.md).
Two things need a separate agreement: removing or altering copyright and licence notices,
and conveying `opm` on terms that do not satisfy the LGPL. Write to
<info@e-editiones.org>.

## Contributing

Contributions are released under the AGPL and require a one-click contributor license
agreement, adapted from the [Harmony Agreements](https://www.harmonyagreements.org/)
(Harmony CLA 1.0, section 2.3 **Option Five** — outbound licensing under any licence,
coupled with Harmony's standing condition that we keep publishing your contribution under
the licence in force on the day you submitted it, which is the AGPL). You keep your
copyright; e-editiones gets the right to relicense, which is what makes the member grant,
the additional permissions and the commercial licences possible, and is bound in return to
keep publishing your work under the AGPL. See
[CONTRIBUTING.md](https://github.com/eeditiones/tei-publisher-py/blob/main/CONTRIBUTING.md).

## Dependencies

All runtime dependencies are permissively licensed and impose no copyleft of their own:
lxml and Babel (BSD-3-Clause), Jinja2 (BSD), elementpath, Typer, Rich, python-docx and
platformdirs (MIT).

---

*This page explains e-editiones' intent in plain language and is not legal advice. Where
it and the licence documents
([LICENSE](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE),
[LICENSE-EXCEPTIONS.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-EXCEPTIONS.md),
[LICENSE-MEMBER-GRANT.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-MEMBER-GRANT.md))
disagree, the licence documents govern.*
