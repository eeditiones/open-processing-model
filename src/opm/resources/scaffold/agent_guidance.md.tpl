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
opm transform [[ $sample ]] --preview
opm transform [[ $sample ]] -t markdown --preview
opm transform [[ $sample ]] -t typst -o output.typ
opm transform [[ $sample ]] -t docx -o output.docx
opm chunk [[ $sample ]] --force --preview
opm serve
```

ODDs compile on demand into the user cache — there is no separate compile step.
Defaults (ODD path, templates, chunking) come from `opm.toml`; CLI flags override them.

## Layout

| Path | Role |
| --- | --- |
| `opm.toml` | Project config (ODD, templates, CSS, chunking, XPath extensions) |
| `[[ $odd_path ]]` | Processing model (edit this to change rendering) |
| `templates/` | HTML / Typst / DOCX templates |
| `styles/` | Shared CSS |
| `extensions/` | Project-local Python XPath extensions (`[project] pythonpath`) |
| `[[ $sample ]]` | Source document |

## Customizing output

1. Prefer editing `[[ $odd_path ]]` (element behaviours, CSS in the ODD `tagsDecl`).
2. Adjust HTML/chunk chrome in `templates/[[ $html_template ]].html.tpl` — the template `opm.toml` sets — and its design in the stylesheet listed under `[transform.web] assets`.[% if $extra_templates %] The other templates copied beside it (`chapbook`, `journal`, `handbook`) are alternatives to switch to, not partials to include.[% else %] `opm init --templates` copies the alternative templates (`chapbook`, `journal`, `handbook`) if you want to switch to one; they are whole page templates, not partials to include.[% endif %]
3. Before writing CSS or overriding a block of the page layout, read `opm templates show opm/layout.html.tpl --header`: it lists the blocks a template fills and the `[context]` settings (site name, logo, menu, columns, toolbar); their defaults are in `opm templates show opm/defaults.toml`. Many layout changes are a setting, not CSS. `opm templates list` shows every template and which copy is used.
4. Add XPath helpers under `extensions/` and list modules in `[transform] xpath_extensions`.
5. Keep relative paths in `opm.toml` relative to that file's directory.

## Patterns agents should respect

- Unprefixed XPath names resolve against the document default namespace — no extra prefix bookkeeping.
- Runtime parameters (`-p key=value`) are available in ODD XPath as `$parameters`.
- Templates use the jinks syntax of TEI Publisher, with XPath expressions: `[% raw %][[ $context?title ]][% endraw %]`, `[% raw %][% if … %][% endraw %]`, `[% raw %][% for $x in … %][% endraw %]`, `[% raw %][% template name %][% endraw %]` filling a `[% raw %][% block name %][% endraw %]` of the layout named under `templating.extends` in the frontmatter.
- Chunking uses `[chunking]` in `opm.toml` (selector, depth, fragments such as title/breadcrumbs).
- Do not invent a separate compile or build pipeline; `opm transform` / `opm chunk` are enough.
- Do not overwrite `CLAUDE.md` or `AGENTS.md` if the user already customized them.
