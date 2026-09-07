# Contributing to Open Processing Model

Contributions are welcome — bug reports, ODD processing models, output functions,
documentation fixes.

## Licence

Open Processing Model is licensed under the **GNU Affero General Public License, version
3 or later** ([LICENSE](LICENSE)), with additional permissions granted under section 7 of
that licence ([LICENSING.md, Part A](LICENSING.md#part-a--additional-permissions)).
Contributions are released under the same terms.

Two parts of the tree are not AGPL: the packaged scaffolding that `opm init` writes into
a user's project, and the example projects, are dedicated to the public domain under CC0
1.0 — see §4 of [LICENSING.md, Part A](LICENSING.md#part-a--additional-permissions) and
[REUSE.toml](REUSE.toml). If your contribution touches those paths, it is contributed
under CC0 rather than the AGPL, and new files there need the CC0 header shown below.

## Contributor License Agreement

Before your first pull request can be merged, you need to sign a CLA. It takes a click.

You keep the copyright in your contribution. What you grant e-editiones is the right to
relicense it — which is what allows the society to offer `opm` to members under
[the LGPL](LICENSING.md#part-b--member-licence-grant), to grant the
[additional permissions](LICENSING.md#part-a--additional-permissions) everyone benefits
from, and to sell commercial licences that fund the project's maintenance. In exchange,
e-editiones is contractually bound to keep publishing your contribution under the AGPL. It
cannot take the code proprietary and leave the community behind; that promise is written
into section 2.3 of the agreement itself.

The text is adapted from the [Harmony Agreements](https://www.harmonyagreements.org/),
the standard templates for exactly this arrangement — nothing in it was invented for this
project. Harmony offers five alternatives for the outbound-licence clause in section 2.3;
this project uses **Option Five**, which lets e-editiones license contributions under any
licence *on condition* that it also keeps licensing them under the terms in force on the
day you submitted — the AGPL. The narrower options (an enumerated list of licences, or
any OSI-approved licence) would rule out the commercial licences that pay for
maintenance, so Option Five is a deliberate choice, and its reciprocal condition is what
keeps it honest.

**Which one to sign:**

- [CLA.md](.github/CLA.md) — you own the copyright in your work personally.
- [CLA-ENTITY.md](.github/CLA-ENTITY.md) — your employer, university, institute, or funder
  owns it. This is common for funded research positions; if you are contributing as part
  of your job, this is probably the one you need.

**How to sign:**

1. Open your pull request as normal.
2. The CLA Assistant bot comments with a link, and the CLA status check goes red.
3. Read the agreement and click to sign. This happens once and covers all your future
   contributions.
4. The check turns green and review proceeds.

For the entity agreement, an authorised signatory needs to sign the document and email it
to `info@e-editiones.org` for countersignature before the PR can be merged. Start that
early — institutional signatures take longer than code review.

**Third-party material.** If your contribution includes code you did not write — a
snippet from another project, generated output, an ODD you adapted — say so in the pull
request before submitting, or ask first at `info@e-editiones.org`. We need to check its
licence is compatible.

## Development

The project uses [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync

uv run opm transform demo/tei-test.xml --preview
uv run opm transform demo/tei-test.xml -c teipublisher.toml -t web --preview
uv run opm chunk demo/tei-test.xml -c teipublisher.toml -o chunks/ --force
uv run opm serve -d chunks/
```

Tests:

```bash
uv sync --group dev
uv run --group dev pytest                             # all tests
uv run --group dev pytest tests/test_odd_compiler.py  # single file
```

Documentation:

```bash
uv sync --group docs
uv run python scripts/gen_cli_docs.py   # refresh the CLI reference from the Typer app
uv run --group docs zensical serve      # http://127.0.0.1:8000
```

See [CLAUDE.md](CLAUDE.md) for an overview of the pipeline and source layout.

## Source file headers

Every new Python file under `src/opm/` starts with:

<!-- REUSE-IgnoreStart -->
```python
# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
```
<!-- REUSE-IgnoreEnd -->

above the module docstring. Tests and scripts do not need it.

Files under `src/opm/resources/scaffold/` and `examples/` are public-domain scaffolding
instead, and carry the CC0 header in whatever comment syntax the format uses:

<!-- REUSE-IgnoreStart -->
```
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
```
<!-- REUSE-IgnoreEnd -->

The processing models under `src/opm/resources/odd/` are neither: they are CC BY 4.0 and
carry their own statement, in the `teiHeader` for an ODD and in an SPDX header for a
stylesheet. Leave those in place.

Keep [REUSE.toml](REUSE.toml) in step when you add a path that cannot carry a header
(binaries, JSON) or a new subdirectory under `examples/`. The documents under
`examples/*/data/` are excluded on purpose — they are source texts with their own
provenance.
