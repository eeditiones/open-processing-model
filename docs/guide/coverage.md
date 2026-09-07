# ODD coverage

`opm coverage` runs your documents through the ODD and reports on the ODD, not
on the documents: what you wrote that never runs, and what your sources contain
that you never handled.

```bash
opm coverage examples/tei-test.xml
opm coverage data/                    # a corpus, subdirectories included
opm coverage                          # no path: defaults to ./data
opm coverage --json > coverage.json   # the full report, nothing elided
```

It is the [`json` output mode](output-formats.md#json) rolled up across a corpus
and read back against the ODD source. Whole documents are transformed;
`[chunking]` is ignored, since a chunk selector need not cover the document and
coverage is a question about the ODD.

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

Each section below it is printed only when it has findings, and cut off after 20
rows — `--all` lists them all, `--json` gives everything with the descriptions
and hit counts as well.

### Local vs inherited

An ODD that extends another (`<schemaSpec source="teipublisher.odd">`) inherits
most of its models. Those are not yours to fix: a local `elementSpec` replaces
the inherited one **wholesale**, so the only way to change an inherited decision
is to redeclare the whole element. Coverage therefore counts inherited models
separately and never lists them as findings. The split comes from the `source`
field of the [`models` table](output-formats.md#the-models-table).

### Unused local models

Models you declared, for elements the corpus actually contains, that never won.
Usually one of three things: the predicate is wrong, an earlier model matched
first (read the [`models` table](output-formats.md#the-models-table) for the one
that beat it), or the model only applies in a `$parameters` mode this run did
not use — pass `-p mode=breadcrumb` to check those.

Models for elements the corpus does not contain are *not* listed here; they say
nothing about the model. They appear once, as an unexercised spec.

### Unreachable models

Static, document-independent findings: models that can never fire whatever you
feed them. The compiler turns a spec's models into an `if`/`elif` chain in ODD
order, with the first model that has **no** `@predicate` as the `else`. So:

- if the very first model has no `@predicate`, every model after it is dead —
  it always wins and the compiler never emits the rest;
- a second unconditional model is dead too, since the first one is already the
  fallback.

`<modelSequence>` is exempt: its children all contribute, none replaces another.

### Models that emit nothing

A model with neither `@behaviour` nor `pb:template` compiles to a bare recursion
into the children. It is legal, it just produces no output of its own — and no
record, so coverage cannot say whether it ran. Listed separately for that reason.

### Elements with no model

Elements that reached no model at all: nothing in the ODD declares them, so
their text surfaces inside whatever ancestor did match. These are the records
`-t json` marks with `"behaviour": null`.

### Elements dropped

The finding no other view shows. The element *has* a spec, so it has a dispatch
case, but every predicate was false — the compiler falls through to processing
the children and emits nothing for the element itself. Nothing marks that in the
output; it simply is not there.

Only the outermost element of a dropped subtree is reported. Falling through
still recurses, so one unhandled `<contrib-group>` would otherwise drag every
name, affiliation and email under it into the list.

Content the ODD deliberately drops is excluded: `omit`, `index` and `metadata`
subtrees, and the branch of a `<choice>` that `alternate` did not pick.

### Element specs never exercised

Local `elementSpec`s whose element never appears anywhere in the corpus. Either
the corpus does not represent your material, or the spec is left over. Specs
that declare no model at all (attribute-only ODD changes) are named on a
separate line — they are not coverage failures.

## Choosing a channel

Coverage reports on one output channel, because that is what decides which
`@output`-tagged models participate:

```bash
opm coverage data/ --channel typst
```

The channels are the same as for [`-t json`](output-formats.md#choosing-which-channel-to-inspect):
`web` (the default), `print`, `epub`, `markdown`, `docx`, `typst`.

## Parameters

Many models are gated on `$parameters?mode`. A plain run reports the default
reading view, so models for `toc`, `breadcrumb` or `metadata` modes show up as
unused. Check those views with the same `--param` flag `opm transform` takes:

```bash
opm coverage data/ -p mode=toc
```

## The JSON report

`--json` prints one object: `summary`, every model with its `hits`, `source`
and `unreachable` verdict, the `unmatched` and `dropped` tables with an example
location each, `behaviours`, `elements_seen`, `unused_specs` and
`attribute_only_specs`.

For the record shape the report is built from, see
[Output formats](output-formats.md#json).
