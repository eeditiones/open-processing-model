<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0
-->

# [[ $heading ]]

[% if $intro %][[ $intro ]]

[% endif %]This is an [Open Processing Model](https://opm.e-editiones.org/) (`opm`) project.
XML ([[ upper-case($vocabulary) ]]) is transformed via ODD processing models configured in `opm.toml`.

Documentation for agents: <https://opm.e-editiones.org/llms.txt> (index, with a Markdown
version of each page) and <https://opm.e-editiones.org/llms-full.txt> (all of it in one file).
Read these before guessing at `opm` options or writing XSLT; `opm --help` and
`opm <command> --help` list the options of the installed version.

## Commands

```bash
opm transform [[ $sample ]] --preview          # one document, HTML in the browser
opm transform [[ $sample ]] -t markdown --preview
opm transform [[ $sample ]] -t typst -o output.typ   # or -t docx -o output.docx
opm chunk [[ $sample ]] --force --preview      # the site: every chunking run, then the pages
opm chunk --run <name>                         # rebuild one run after a full build, keep the rest
opm chunk --run <name> --page index.html       # … and the pages whose path starts with index.html
opm serve
```

ODDs compile on demand into the user cache: `opm transform` and `opm chunk` are the
whole build, with no separate compile step or pipeline to add. Defaults (ODD path,
templates, chunking) come from `opm.toml`; CLI flags override them. To try a change
without touching the site, copy the output folder and pass it with `-o` to `opm chunk --run`.

## Layout

| Path | Role |
| --- | --- |
| `opm.toml` | Project config (ODD, templates, CSS, chunking, XPath extensions) |
| `[[ $odd_path ]]` | Processing model (edit this to change rendering) |
| `templates/` | HTML / Typst / DOCX templates, and the stylesheets they use |
| `extensions/` | Project-local Python XPath extensions (`[project] pythonpath`) |
| `[[ $sample ]]` | Sample document; a chunking run with an `input` reads its own documents |

opm's own templates (the page layout the HTML templates extend, its defaults and
stylesheet) are not copied into the project: `opm templates list` lists them,
`opm templates show <name>` prints one.

## Customizing output

1. Prefer editing `[[ $odd_path ]]` (element behaviours, CSS in the ODD `tagsDecl`).
2. Adjust HTML/chunk chrome in `templates/[[ $html_template ]].html.tpl` — the template `opm.toml` sets — and its design in the stylesheet listed under `[transform.web] assets`.[% if $extra_templates %] The other templates copied beside it (`chapbook`, `journal`, `handbook`) are alternatives to switch to, not partials to include.[% else %] `opm init --templates` copies the alternative templates (`chapbook`, `journal`, `handbook`) if you want to switch to one; they are whole page templates, not partials to include.[% endif %]
3. Before writing CSS or overriding a block of the page layout, read `opm templates show opm/layout.html.tpl --header`: it lists the blocks a template fills and the `[context]` settings (site name, logo, menu, columns, toolbar); their defaults are in `opm templates show opm/defaults.toml`. Many layout changes are a setting, not CSS. `opm templates list` shows every template and which copy is used.
4. Prefer plain XPath in the ODD: it also runs in TEI Publisher. Only when that is not enough, add Python helpers under `extensions/` and register each module in a `[% raw %][[transform.extensions]][% endraw %]` table of `opm.toml` (functions become `tp:` XPath functions; `prefix` and `@behaviour` are described in the Extension modules guide).
5. Keep relative paths in `opm.toml` relative to that file's directory.

## Patterns agents should respect

- In ODD XPath, unprefixed names resolve against the document's default namespace. Template XPath does not: declare a prefix under `templating.namespaces` in the template's frontmatter, or write `*:title`.
- `doc()` and `collection()`, in the ODD and in templates, only see the files listed under `[transform] documents` or `[% raw %][[transform.collections]][% endraw %]` in `opm.toml`.
- Runtime parameters (`-p key=value`) are available in ODD XPath as `$parameters`.
- Templates use the jinks syntax of TEI Publisher, with XPath expressions: `[% raw %][[ $context?title ]][% endraw %]`, `[% raw %][% if … %][% endraw %]`, `[% raw %][% for $x in … %][% endraw %]`, `[% raw %][% template name %][% endraw %]` filling a `[% raw %][% block name %][% endraw %]` of the layout named under `templating.extends` in the frontmatter, `[% raw %][% include "file.html.tpl" %][% endraw %]` for a shared piece.
- A chunk page's template sees `$context?document` (the document's name, `[chunking] document_name`), `$context?site_root` (the way back to the output root, for links), `$context?fragments?<name>` (the run's fragments) and `$context?chunk?prev` / `next`. Only `[% raw %][[pages]][% endraw %]` templates get `$context?site_documents`, the documents built with their first pages.
- Chunking is one `[chunking]` table, or several `[% raw %][[chunking]][% endraw %]` runs writing into one output folder, each with its own `input`, `document_name`, `odd`, `template` and fragments. `[% raw %][[pages]][% endraw %]` add pages without a document of their own; one at `index.html` replaces the generated collection index.
- `opm init` never overwrites `CLAUDE.md` or `AGENTS.md`: when the project grows (new runs, ODDs, collections), update them by hand.
