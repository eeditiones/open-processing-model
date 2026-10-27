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

[Unreleased]: https://github.com/eeditiones/open-processing-model/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/eeditiones/open-processing-model/releases/tag/v0.9.0
