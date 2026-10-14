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

- `[transform] footnote_order` / `--footnote-order` — reorder (or drop) footnotes
  for `web` and `markdown`. Ships `labelled_first` and `by_place`; see the
  [Footnotes](docs/guide/footnotes.md) guide.
- `opm odd document` — static HTML documentation site from an ODD (reference
  pages, catalogs, optional Guidelines chapters).
- `SpecIndex` / `compile_schema` — Python API for the ODD spec graph and a
  small odd2odd merge.
- `tp:highlight($source, $language)` — Pygments HTML for code listings from
  ODD `content` params.
- `chunking.file_pattern` — name chunk files from `{xml_id}` / `{ident}`
  instead of `001.html`.
- Spec XPath helpers (`tp:contained_by`, `tp:may_contain`, …) for
  `tagdocs.odd` documentation pages.

### Fixed

- Empty stand-off notes no longer emit a footnote labelled `[]`.

### Changed

- Notes with their own TEI `@n` no longer consume the running counter, so
  lettered and numbered series count independently. HTML notes also expose
  `data-n` for styling, as `print` already did.
- Lemma-range notes (`<anchor type="note"/>` … `<note target="…">`) display as
  `a-` / `-a` in the text and `a-a` in the footnote list.
- `opm coverage` is now `opm odd coverage` (old name kept as a hidden alias).
- DocBook `programlisting` / `synopsis` (and tagdocs `egXML`) use
  `tp:highlight` on `opm-web` / `opm-print`.

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
