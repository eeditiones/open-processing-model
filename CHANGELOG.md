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
- Chunk page templates receive `document`, the source file's name, and
  `documents`, the names of every document in the run, so they can link only
  to pages that exist. The Serafin example uses it
  for its previous/next letter toolbar, ported from the Astro edition.

### Changed

- The runtime passes a typed `RenderContext` to every output function instead
  of a plain dict, and evaluates XPath through an `XPathEnvironment` built once
  per document.
- `fn:id()` answers from an index built once per document and run instead of
  walking the whole document on every call, which dominated runs on
  register-heavy editions. Results are unchanged. `tp:lookup()`, an opm-only
  workaround no ODD used, is gone.
- What each output mode does — which ODD models take part, which output
  functions render them, which template wraps the result, whether web
  components may load, how `--preview` shows it — is defined once, in
  `opm.output_modes`. Compiled modules declare `OUTPUT_MODE` instead of
  `transform_output_channels()` and no longer hard-code their output functions.
- An unknown `-t` value is an error; it used to render HTML from the generic
  models only.
- `opm transform` runs through `transform_file()`, so the command and the
  Python API can no longer drift apart. `project_xpath_env()` builds the XPath
  environment from `opm.toml` for transform, chunk, index and coverage alike.
  `run_transform()` and `transform_node()` take that environment as `xpath_env`
  instead of separate `xpath_*` arguments, and `ChunkProcessor` takes it the
  same way.

### Fixed

- `-t json --channel <channel>` and `opm coverage --channel` use the ODD from
  `[transform.json]`, as plain `-t json` does, instead of falling back to
  `[transform] odd`.
- `transform_file()` now behaves like `opm transform`: it applies
  `[transform.parameters]`, selects EPUB chapters with the `[transform.epub]`
  overrides, and picks the DOCX style template the same way (the `template`
  argument, then `[transform.docx] template`, then the packaged default).

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
