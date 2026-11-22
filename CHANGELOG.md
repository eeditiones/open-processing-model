<!--
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Design tokens in `opm-layout.css` (`--opm-surface`, `--opm-font-display`, `--opm-color-accent-soft`, `--opm-radius`, `--opm-shadow`, …) with a default "rubric" palette and an opt-in dark scheme (`theme.color_scheme = "auto"` or `"dark"`)
- Collection index redesigned: masthead with `site_name`, `description` and counts, a filter box, list/grid views and a length bar per document; its words are under `theme.index`
- `theme.index.hero` (`image`, `position`, `text`) and `--opm-masthead-image` / `-position` / `-overlay` / `-min-height` / `-color*`: a picture behind the index masthead with a scrim for light or dark text
- More design tokens: `--opm-display-weight`, `--opm-display-tracking`, `--opm-font-mono`, `--opm-menubar-background`, `--opm-menubar-color`, `--opm-menubar-link-color`, `--opm-menubar-link-hover`, `--opm-breadcrumb-separator`, `--opm-drawer-padding`
- The menubar logo and `<title>` fall back to the document's `title` fragment, so themes need not override them
- `theme.layout.logo_title = false` shows `context.logo` alone, for a wordmark that spells the name; the name becomes its alt text

### Changed

- Theme stylesheets are named `opm-theme-<name>.css`: `opm-theme-chapbook.css`, `opm-theme-handbook.css`, `opm-theme-journal.css`, which `opm init` copies beside the template of the same name. The monograph and Escher examples' design is the theme `opm-theme-paper.css` (formerly their `chapbook.css`)
- The chapbook template writes `opm-reader-*` classes and `<body class="opm-reader">` instead of `chap-*` and `chapbook`, so any reader theme (chapbook, paper) can style it; chapbook's own custom properties are `--chapbook-*`
- The packaged layout styles more of the page chrome itself: muted menu links, the current breadcrumb, the drawer's header bar, the skip link, a translucent menubar; sticky sidebars stop below the menubar by default
- `handbook`, `chapbook` and `journal` designs rebuilt on the design tokens instead of their own `--hb-*`, `--chap-*` and `--jr-*` copies of them, so their colours, fonts and dark mode also apply to the collection index. Their web fonts load from the stylesheet instead of the template, and they no longer override the logo and `<title>` (journal keeps its journal line as logo, now linking to the index). The chapbook logo shows `site_name` when set, as the index does
- The monograph and Escher design ("Der Römerbrief") hands its palette to the tokens and switches to dark through `theme.color_scheme` instead of its own `data-theme`; the docbook, monograph and Escher examples set `color_scheme = "auto"`
- The Serafin example uses the packaged collection index (its parchment as the masthead picture) instead of its own, and its wordmark through `context.logo` instead of a logo override; `letter.css` is built on the design tokens
- Shakespeare's facsimile column moved to its own `facsimile.css`, so its `chapbook.css` is the scaffold's again; the jats example's `journal.*` are the scaffold's

### Fixed

- Breadcrumbs no longer inherit the toolbar's wide gap between items, and wrap even where an ODD stylesheet sets them `nowrap`
- Focus rings in a coloured menubar take its text colour
- The journal line in the journal masthead shows in the accent colour again

## [0.10.0] - 2026-10-29

Besides numerous bug fixes, this release supports generating documentation from existing ODDs, either as a static website, markdown, ePub or PDF. It also adds two more examples, showcasing a nicely designed monograph as well as another correspondence edition with a switch between diplomatic and edited text. HTML templates and styling have been refactored accordingly.

### Added

- `[transform] footnote_order` / `--footnote-order` for `web` and `markdown`
- `opm odd document` — generate static documentation from an ODD
- `chunking.file_pattern` — name chunk files using `{xml_id}` / `{ident}`
- `chunking.document_name` — change each document's output directory via XPath expression
- `escher` example — diplomatic/edited letters with facsimile hover
- `monograph` example – using a chapter of Karl Barth's "Der Römerbrief"

### Fixed

- Empty stand-off notes no longer emit a footnote labelled `[]`
- `tp:serialize_egxml` keeps intentional line breaks in mixed content
- A `file_pattern` with no `{…}` fields is used as the literal file name
- Stripping XML comments outside `egXML` no longer drops following text
- Global-fragment `doc` links use the first page's real file under `file_pattern`

### Changed

- `opm init --vocabulary docbook` scaffolds `handbook` instead of `chapbook`
- preserve `@n` on notes; HTML exposes `data-n`
- `opm coverage` is now `opm odd coverage` (old name kept as a hidden alias)
- DocBook `programlisting` / `synopsis` and tagdocs `egXML` use `tp:highlight`

## [0.9.0] - 2026-09-14

First public release. Feature-complete and in use; the 0.x version
signals that the CLI and `opm.toml` surface may still change before 1.0.

### Added

- `opm init` — scaffold a project, empty for a vocabulary (`--vocabulary`) or
  from one of the bundled example projects (`--example`, `--list-examples`).
- `opm transform` — transform a single XML document through an ODD processing
  model to HTML, Markdown, DOCX, EPUB, JSON, or print output.
- `opm chunk` — split a document by an XPath selector, transform each chunk and
  write the chunk files plus a manifest.
- `opm index`, `opm coverage`, and `opm serve`.
- ODDs compile on demand into the per-user cache, keyed by ODD content,
  inheritance chain, CSS, mode, and package version; stock ODDs ship with the
  package.
- `opm.toml` project configuration for templates, CSS, XPath extensions,
  chunking rules, and Python path additions.

[Unreleased]: https://github.com/eeditiones/open-processing-model/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/eeditiones/open-processing-model/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/eeditiones/open-processing-model/releases/tag/v0.9.0
