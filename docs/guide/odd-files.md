# ODD files

An **ODD** (One Document Does it all) file is a TEI XML document which includes
*processing model* instructions. `opm` compiles an ODD on demand into a Python
transform module. The compiled module will automatically be cached for further use.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd).
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

> **Note**: if you are using an editor based on Visual Studio Code (Cursor, Antigravity, Windsurf, Kiro …), check the marketplace for an extension called [ODDity](https://open-vsx.org/extension/e-editiones/oddity) – it provides a graphical environment for editing ODDs.

The library packages three stock ODDs:

- `teipublisher.odd` (+ `tp.css`) — main TEI Publisher model, and the fallback
  when `--odd` is omitted
- `docbook.odd` (+ `docbook.css`) — DocBook v5 model (`opm init --vocabulary docbook`)
- `jats.odd` (+ `jats.css`) — JATS journal article model (`opm init --vocabulary jats`)

`opm init` writes a short `odd/custom.odd`. For TEI projects, it inherits the packaged `teipublisher.odd`,
or otherwise copies `docbook.odd` / `jats.odd`. To also include a copy of the base `teipublisher.odd`, pass `--copy-base-odd`.

For example customisations, see the
projects under `examples/`, each of which ships its own ODD (for instance
`examples/shakespeare/odd/shakespeare.odd`).

OPM supports ODD chaining, a technique of ordering individual ODD documents in such a way that it is possible for one document to re-use (and potentially modify) declarations and definitions from another ODD. A base ODD can be defined in the  `schemaSpec/@source` attribute or with the flag `source="<odd file>"`. For TEI edition projects, we recommend always having the `teipublisher.odd` as the base of your custom ODD. It includes default renditions for the most common TEI elements.

## Compiling on demand

Pass an ODD to `opm transform` / `opm chunk` (or set `odd = "…"` in the configuration).
The first run compiles it into the user cache (and prints the path on stderr);
later runs reuse the cache until the ODD (or its inherited sources / CSS)
changes.

```bash
opm transform examples/tei-test.xml --preview
opm transform examples/tei-test.xml -t docx -o out.docx
```

## Reusing ODDs between TEI Publisher and `opm`

The shipped ODDs are shared between TEI Publisher and opm to make it easy to switch
between implementations. However, TEI Publisher runs within a database and has the
full power of XQuery at its disposal. Consequently, not every expression that works in
TEI Publisher will work in `opm`, which is limited to XPath 3.1.

To cope with this, two mechanisms are implemented:

1. `<model>` which target `opm` can have an `@output` attribute value prefixed with `opm-`
(e.g. `output="opm-web"`). TEI Publisher will simply skip over those. If you put the prefixed model
before the unprefixed one, `opm` will use it while TEI Publisher ignores it and selects the next
matching model instead. DocBook listings do this: `tp:highlight` (Pygments) on `opm-web` /
`opm-print`, then `pb-code-highlight` for tei-publisher-lib.
2. `opm`'s compiler tests each XPath expression and recognises the ones it cannot execute. If such
an expression occurs inside a predicate, it will evaluate to `false` and the processor consequently skips it.
Parameter expressions will return the context node instead of failing. The client prints a count of
ignored expressions to the console. To get a full report for an ODD, see [`opm odd coverage`](coverage.md#expressions-opm-cannot-run). 

## Supported extensions

`opm` implements the same extensions to the TEI processing model as TEI Publisher.

### `$parameters`

External parameters are passed to the ODD in a `$parameters` map. Values come from `[transform.parameters]` in the `opm.toml` configuration file, 
the command line passed as `-p key=value`, and per-fragment `parameters` in [chunking](chunking.md#fragments).

### `$parameters?root`

The special parameter, `$parameters?root`, always contains a reference to the root node being processed. This is mainly relevant in `chunk` mode:
it splits the document into fragments, and each fragment becomes a document of its own. The link to the source document therefore gets lost. Use `$parameters?root`
to get it back.

`root($parameters?root)` always points to the document node. `teipublisher.odd`
 uses that, for example, to reach the `teiHeader` from a `div` or page:

```xpath
root($parameters?root)//teiHeader/fileDesc/titleStmt
```

### `$get()` and `tp:source-node()`

While `$parameters?root` returns the root node, the special function pointer `$get($n)` in TEI
Publisher gives you the source node corresponding to its argument. `opm` implements the same for backwards compatibility, e.g. to be used in:

```xml
<param name="order" value="count($get(.)/preceding::pb) + 1"/>
```

Inside `opm`, `$get()` is an alias for the function `tp:source-node($n)`, which you can use alternatively.

### `<pb:template>`

A model in TEI Publisher may provide a custom markup template in a [`<pb:template>`](https://teipublisher.org/doc/documentation.xml?id=pb-template#pb-template). 
Without it, producing more complex output for a single element
would not be possible. Markup templates also help with plain-text markup languages like LaTeX or typst.

`opm` processes `<pb:template>` in the same way as TEI Publisher does.

## XPath errors at run time

An expression that is valid XPath can still fail on a particular document, for example,
`xs:date(date)` on a date written as "circa 1850", say. As before, such a
predicate counts as false and a param as empty. `opm transform`, `opm chunk`,
`opm index` and `opm odd coverage` list these failures at the end of the run, each
expression once, with the error, how often it failed and where it first did:

```
opm: warning: 1 XPath expression failed at run time and was treated as false or empty:
  xs:date(date) lt xs:date('1900-01-01')
    FORG0001: Invalid datetime string 'circa' for Date
    3×, first at <date> data/letter.xml:41
```

Pass `--strict` to `opm transform`, `opm chunk` or `opm index` to make that an
error (exit status 1), for example in CI. Expressions the compiler already
skipped do not count.

Errors that mean the project configuration is missing something are shown as a
single note naming the setting instead, and never fail a run: an undeclared
namespace prefix (`[transform.namespaces]`), an unset variable
(`[transform.variables]`), a `tp:` function that no configured module provides
(`[transform] xpath_extensions`), or an unknown collection
(`[[transform.collections]]`).