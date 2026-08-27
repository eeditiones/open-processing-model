# License

Open Processing Model is free software, copyright © 2026 e-editiones, licensed under the
**GNU Affero General Public License, version 3 or later** (AGPL-3.0-or-later).

The AGPL is the strongest of the common copyleft licences: it reaches not only software
you distribute, but software you *operate* — a web service built on `opm` owes its source
to the people using it. That is deliberate. It keeps scholarly tooling open even as it
moves onto the web, which is where editions increasingly live.

If that obligation does not fit your situation, e-editiones offers institutional members
the same software under LGPL-based terms; see [Member licence](#member-licence) below.

## What the licence reaches

The question is almost always the same: *does using `opm` make my project AGPL?* It
depends on how you use it, and in Python the line is unusually clear.

| How you use `opm` | Does the AGPL reach your code? |
| --- | --- |
| `import opm` in your own program | **Yes.** In-process use creates a combined work. Your program falls under the AGPL when you distribute it or expose it over a network. |
| Running `opm transform …` as a subprocess | **No.** A command-line boundary — arguments in, files out — is arm's length. Your program stays separate and keeps whatever licence you choose. |
| Running an unmodified `opm` internally, never exposed to anyone else | **No obligation arises.** The AGPL is triggered by conveying the software or offering it to users over a network, not by private use. |
| Hosting a service that calls `opm` in-process | **Yes — this is what §13 is for.** Your users are entitled to the Corresponding Source of the service. |
| The HTML, DOCX, Typst or Markdown that `opm` produces | **No.** Transformation output is your content. The licence does not reach it, and e-editiones asserts no rights in it. |
| Your TEI sources, ODDs you wrote, your templates and CSS | **No.** These are your work. |

If you want to keep an application closed and still call `opm` from it, the subprocess
route is a genuine and supported option — `opm` is designed as a command-line tool first.

## Files `opm init` writes into your project

`opm init` copies stock ODDs, CSS and Jinja templates into your working directory as a
starting point. These are yours to edit and to license as you see fit; scaffolding a
project does not place your edition under the AGPL.

## Generated transform modules

Compiling an ODD produces a Python module in your user cache, which imports
`opm.runtime` at execution time. e-editiones' position is that these generated modules
are output of the compiler and part of your project — running them does not place your
project under the AGPL. The AGPL continues to govern `opm` itself, including the runtime
they call into.

## XPath extension modules

Python extension modules you register through `opm.toml` are loaded into the same
interpreter. e-editiones treats them the same way as generated modules: they are your
work, and you may license them however you wish.

## Member licence

Members of e-editiones in good standing may use `opm` under the terms of the **GNU Lesser
General Public License, version 3 or later**, as an alternative to the AGPL. In practice
this waives the two obligations that matter most to institutions:

- your application built on `opm` may remain proprietary, and
- a hosted service built on `opm` owes its users nothing under §13.

What stays: improvements to `opm` itself are still released, attribution is preserved,
and your users keep the ability to substitute their own build of `opm` — which in Python
means little more than depending on the PyPI package instead of vendoring a patched copy.

Full terms are in
[LICENSE-MEMBER-GRANT.md](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE-MEMBER-GRANT.md).
Uses beyond that — private forks, vendoring, removing attribution — need a commercial
licence: write to <info@e-editiones.org>.

## Contributing

Contributions are released under the AGPL and require a one-click contributor license
agreement, adapted from the [Harmony Agreements](https://www.harmonyagreements.org/). You
keep your copyright; e-editiones gets the right to relicense, which is what makes the
member and commercial licences possible, and is bound in return to keep publishing your
work under the AGPL. See
[CONTRIBUTING.md](https://github.com/eeditiones/tei-publisher-py/blob/main/CONTRIBUTING.md).

## Dependencies

All runtime dependencies are permissively licensed and impose no copyleft of their own:
lxml and Babel (BSD-3-Clause), Jinja2 (BSD), elementpath, Typer, Rich, python-docx and
platformdirs (MIT).

---

*This page explains e-editiones' intent in plain language and is not legal advice. Where
it and [LICENSE](https://github.com/eeditiones/tei-publisher-py/blob/main/LICENSE)
disagree, the licence text governs.*
