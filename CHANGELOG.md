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

- XPath errors are no longer silent. The compiler recognises ODD expressions
  opm can never evaluate (eXist functions such as `util:document-name`,
  XQuery-only syntax), compiles them to the result a failing evaluation always
  gave, and says how many it skipped on the first compile; `opm coverage` lists
  them. Errors raised at run time are summarised at the end of `opm transform`,
  `opm chunk`, `opm index` and `opm coverage`, once per expression with a count
  and source location; missing configuration is named in a note.
- `--strict` on `opm transform`, `opm chunk` and `opm index` exits with an
  error when an XPath expression fails at run time.
- `opm.runtime.collect_xpath_errors()` collects the same information from Python.

### Fixed

- A `param` that reads project configuration (`$global:…`, `collection()`) and
  also calls a `tp:` extension function is now evaluated. The compile-time check
  did not know the extension and fell back to the context node.

## [0.9.0] - 2026-09-09

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
