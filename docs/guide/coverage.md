# ODD coverage

`opm coverage` is a useful debugging tool. It runs your documents through the ODD and reports on the ODD, not on the documents: the processing models that never run, and what elements the sources contain that were never handled.

```bash
opm coverage examples/tei-test.xml
opm coverage data/                    # a corpus, subdirectories included
opm coverage                          # no path: defaults to ./data
opm coverage --json > coverage.json   # the full report, nothing elided
```

It is the [`json` output mode](output-formats.md#json) rolled up across a corpus
and read back against the ODD source. Whole documents are transformed; and
`[chunking]` is ignored because its scope will be inappropriate for a document-based ODD coverage report.

## What it reports

```
ODD coverage — odd/shakespeare.odd (channel: web)
1 document, 5353 records, 1147 suppressed

Summary
                       total
Local models           48     fired 20 (41%)  unused 28
Inherited models       206    fired 13
Elements in documents  91     no model 2      dropped 0
```

Each section is printed only when it has findings, and cut off after 20
rows — `--all` lists them all, `--json` gives everything with the descriptions
and hit counts as well.

### Custom ODD and Base ODD

A custom ODD is usually chained, that is, is an ODD that extends another (e.g. `<schemaSpec source="teipublisher.odd">`) and thus, it will inherit from the base ODD any model that it does not explicitly override. A custom `elementSpec` (with `@mode` `change` or `replace`) effectively replaces **all** the processing models of the base ODD, thus the only way to change an inherited decision
is to redeclare the whole element. Coverage therefore counts inherited models
separately and never lists them as findings. The split comes from the `source`
field of the [`models` table](output-formats.md#the-models-table).

### Unused custom models

There are models you declared, for elements the corpus actually contains, that were never fired.
Usually due to one of three things: the predicate is wrong, an earlier model matched
first (read the [`models` table](output-formats.md#the-models-table) for the one
that beat it), or the model only applies in a `$parameters` mode this run did
not use — pass `-p mode=<value>` to check those.

Models for elements the corpus does not contain are *not* listed here. They appear once, as an unexercised spec.
<!--
### Unreachable models

Static, document-independent findings: models that can never fire whatever you
feed them. The compiler turns a spec's models into an `if`/`elif` chain in ODD
order, with the first model that has **no** `@predicate` as the `else`. So:

- if the very first model has no `@predicate`, every model after it is dead —
  it always wins and the compiler never emits the rest;
- a second unconditional model is dead too, since the first one is already the
  fallback.

`<modelSequence>` is exempt: its children all contribute, none replaces another.
-->
### Expressions OPM cannot run

There could be predicates and params that use what only TEI Publisher's eXist-DB 
runtime has, such as `util:document-name()` or XQuery's `try`/`catch`. The
compiler skips them — a predicate counts as false, a param falls back — and
this table lists each with the reason and its line in the ODD. See
[ODD files](odd-files.md#reusing-odds-between-tei-publisher-and-opm).

Errors raised while the documents were transformed are listed after the report,
as for `opm transform`: a predicate that fails counts as false, which can make
its model look unused.

### Models that emit nothing

A model with neither `@behaviour` nor `pb:template` compiles to a bare recursion
into the children. It is legal, it just produces no output of its own — and no
record, so coverage cannot say whether it ran. Listed separately for that reason.

### Elements with no model

Source elements that aren’t processed by any model: nothing in the ODD declares them, so
their text surfaces inside whatever ancestor did match. These are the records that
`-t json` marks with `"behaviour": null`.

### Elements dropped

The element *has* a spec, so it has a dispatch
case, but every predicate was false — the compiler falls through to processing
the children and emits nothing for the element itself. Nothing marks that in the
output; it simply is not there.

Only the outermost element of a dropped subtree is reported.
<!-- Falling through
still recurses, so one unhandled `<contrib-group>` would otherwise drag every
name, affiliation and email under it into the list.-->

Content the ODD deliberately drops is excluded: that is, `omit` behaviour, `index` and `metadata`
subtrees, and the branch of a `<choice>` that `alternate` did not pick.

### Element specs never exercised

A custom `elementSpec` whose element never appears anywhere in the corpus. Specs
that declare no model at all are named on a
separate line — they are not coverage failures.

## Choosing a channel

Coverage reports on one output channel, because that is what decides which
`@output`-tagged models participate:

```bash
opm coverage data/ --channel typst
```

The channels are the same as for [`-t json`](output-formats.md#choosing-which-channel-to-inspect):
`web` (the default), `print`, `epub`, `markdown`, `docx`, and `typst`.

## Parameters

Many models are gated on `$parameters?mode`. A plain run reports the default
reading view, so models for common user-specified modes like `toc`, `breadcrumb` or `metadata` show up as
unused. Check those views with the same `--param` flag `opm transform` takes:

```bash
opm coverage data/ -p mode=toc
```

## The JSON report

`--json` prints one object: `summary`, every model with its `hits`, `source`
and `unreachable` verdict, the `unmatched` and `dropped` tables with an example
location each, `behaviours`, `elements_seen`, `unused_specs`,
`attribute_only_specs` and `unsupported`, the expressions OPM cannot run.

For the record shape the report is built from, see
[Output formats](output-formats.md#json).
