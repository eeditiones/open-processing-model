# ODD files

An **ODD** (One Document Does it all) file is a TEI XML document which includes
*processing model* instructions. `opm` compiles an ODD on demand into a Python
transform module. The compiled module will automatically be cached for further use.

To learn more about ODD, it is best to read the [TEI Publisher documentation](https://teipublisher.org/doc/documentation.xml?id=odd#odd).
It also includes a small tutorial in the [Gentle Introduction](https://teipublisher.org/doc/quickstart.xml?id=pm-tutorial#pm-tutorial) document.

The library packages three stock models:

- `teipublisher.odd` (+ `tp.css`) — main TEI Publisher model, and the fallback
  when `--odd` is omitted
- `docbook.odd` (+ `docbook.css`) — DocBook v5 model (`opm init --vocabulary docbook`)
- `jats.odd` (+ `jats.css`) — JATS journal article model (`opm init --vocabulary jats`)

`opm init` writes a short `odd/custom.odd` that inherits packaged `teipublisher`,
or copies `docbook.odd` / `jats.odd` into the project. For worked customisations, see the
projects under `examples/`, each of which ships its own ODD (for instance
`examples/shakespeare/odd/shakespeare.odd`). `examples/jats` is a good model for
extending a copied stock ODD: it widens the static TOC and adds journal
front-matter apparatus to `jats.odd`, each change marked with a `<desc>`.

`schemaSpec/@source` is resolved next to the child ODD first, then as a packaged
stock ODD — so `source="teipublisher.odd"` works after a pip install without
copying the parent file. Pass `--copy-base-odd` to snapshot `teipublisher.odd`
into the project.

## Compiling on demand

Pass an ODD to `opm transform` / `opm chunk` (or set `odd = "…"` in config).
The first run compiles it into the user cache and prints the path on stderr;
later runs reuse the cache until the ODD (or its inherited sources / CSS)
changes.

```bash
opm transform examples/tei-test.xml --preview
opm transform examples/tei-test.xml -t docx -o out.docx
```

From Python, use [`opm.odd_cache.ensure_compiled_module`](../api/odd-compiler.md)
or the lower-level [`opm.odd_compiler.compile_odd`](../api/odd-compiler.md).

### Expressions opm cannot run

ODDs are often shared with TEI Publisher, whose eXist runtime evaluates XQuery
and has functions of its own. An expression that uses them —
`util:document-name(.)`, `try { … } catch * { … }`, an inline
`<ref type="previous"/>` — fails in opm for every document. The compiler
recognises these and keeps the behaviour a failing evaluation always had: a
predicate counts as false, so a later model is used, and a param falls back to
the context node or to an empty value. The first compile prints one line saying
how many there are; [`opm coverage`](coverage.md#expressions-opm-cannot-run)
lists each one with its reason and ODD line.

To give opm its own version of such a model, add one that only opm reads: an
`@output` with the `opm-` prefix (`output="opm-web"`) is ignored by
tei-publisher-lib.

Only XPath the compiler cannot judge alone is left to run time. Namespace
prefixes the ODD does not declare, `$prefix:name` variables and `tp:` functions
come from `opm.toml`, which a cached module knows nothing about.

## XPath errors at run time

An expression that is valid XPath can still fail on a particular document:
`xs:date(@when)` on a date written as "circa 1850", say. As before, such a
predicate counts as false and a param as empty. `opm transform`, `opm chunk`,
`opm index` and `opm coverage` list these failures at the end of the run, each
expression once, with the error, how often it failed and where it first did:

```
opm: warning: 1 XPath expression failed at run time and was treated as false or empty:
  xs:date(@when) lt xs:date('1900-01-01')
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

From Python, wrap the transform in `opm.runtime.collect_xpath_errors()`:

```python
from opm.runtime import collect_xpath_errors

with collect_xpath_errors() as log:
    html = run_transform(mod, root)
for failure in log.ordered_failures():
    print(failure.expression, failure.code, failure.count)
```

## `$parameters`

ODD predicates and `param/@value` expressions see a `$parameters` map (XPath 3.1
lookup: `$parameters?mode`). Values come from `[transform.parameters]` in
`opm.toml`, CLI `-p key=value`, and per-fragment `parameters` in
[chunking](chunking.md#fragments).

### `$parameters?root`

Same convention as [tei-publisher-lib](https://github.com/eeditiones/tei-publisher-lib):
`$parameters?root` is a **node**, the currently viewed element in the original
document — not a string id.

| Command | Bound to |
| --- | --- |
| `opm transform` | Document element |
| `opm chunk` | The original node this chunk was copied from |

`root($parameters?root)` is therefore the document node. Stock TEI Publisher
models use that to reach the header from a `div` or page:

```xpath
root($parameters?root)//teiHeader/fileDesc/titleStmt
```

Some chunk selectors emit a **copy** (DocBook fill intros, TEI `pb` pages). On
that copy, `ancestor::*` is empty. `$parameters?root` still points at the
original, so ancestor titles and `id()` lookups keep working:

```xml
<param name="content"
    value="($parameters?root/ancestor::article/info/title,
            $parameters?root/ancestor::section/title,
            title)"/>
```

That path is ordinary XPath 3.1: `$parameters?root` is a postfix lookup, which
is a `StepExpr`, so `/` may follow it. Stock ODDs also wrap the node in a
function (`root($parameters?root)//teiHeader/…`) when they need the document
node rather than the viewed element.

opm’s XPath engine (elementpath) currently rejects `/` immediately after `?`.
Parenthesize the lookup until that is fixed: `($parameters?root)/ancestor::section`.

Do not set a string `root` in `[transform.parameters]` if you want this node
binding. An explicit string `root` is left as a string, matching a user-supplied
parameter of that name.
