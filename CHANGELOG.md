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

- `opm odd document` — static HTML documentation site from an ODD (element /
  class / macro / datatype reference pages, A–Z catalogs, processing models,
  optional Guidelines chapters). Follows `schemaSpec/@source` and writes to
  `odd/<schemaSpec ident>` unless `-o` is given. `--guidelines` documents TEI
  alone, chapters included; a spec's Guidelines pointers then link to the
  chapter page in the site rather than to tei-c.org.
- `SpecIndex` and `compile_schema` — Python API for the ODD spec graph
  (contained by, may contain, members, used by, attribute inheritance) and a
  small odd2odd merge.
- `tp:highlight($source, $language)` — Pygments HTML for a code listing,
  called from ODD `content` params (`opm.runtime.common_xpath_functions`).
- `chunking.file_pattern` — name chunk HTML files from `{xml_id}` / `{ident}`
  instead of `001.html`. `opm odd document` uses `{xml_id}.html` so reference
  pages stay at `ref-{ident}.html`.
- `tp:contained_by` / `tp:may_contain` / `tp:members` / `tp:used_by` (and
  catalog helpers) in `opm.runtime.spec_xpath_functions`, used by `tagdocs.odd`
  to render documentation pages through `opm chunk`.

### Changed

- `opm coverage` is now `opm odd coverage`. The old command remains as a hidden
  alias.
- DocBook `programlisting` / `synopsis` (and tagdocs `egXML`) call
  `tp:highlight` on `output="opm-web"` / `opm-print`. tei-publisher-lib still
  uses `pb-code-highlight`.

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
