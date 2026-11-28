# Extension modules

ODD predicates and parameters are XPath 3.1 expressions. You can extend them with
your own functions, written in Python. This is how you add logic that goes beyond plain XPath —
date formatting, outline numbering, project lookups, and so on. The same modules
can also define new behaviours, or change how a built-in one works.

Use them sparingly: whatever you can express in the ODD itself also runs in TEI
Publisher, while Python code only runs in `opm`.

## Writing an extension module

An extension module is an ordinary Python module. Every **public** callable (a
name that does not start with `_`) is registered as `tp:<name>`. You can call it
as spelled in Python or with hyphens instead of underscores — `gap_dots` is
available as `tp:gap_dots(…)` and as `tp:gap-dots(…)`. Names imported into the
module are registered too, so alias helpers you only use internally with a
leading underscore to keep them out of the `tp:` namespace.

```python
# extensions/my_functions.py
from opm.runtime.xpath_extensions import expect_string as _expect_string


def shout(value):
    """Available in ODD XPath as tp:shout(...)."""
    return _expect_string(value, arg_name='shout(value)').upper()
```

In an ODD model predicate or parameter:

```xml
<param name="label" value="tp:shout(@type)"/>
```

The Serafin example project contains one:
`examples/serafin/extensions/serafin_functions.py` defines `gap_dots`, and
`examples/serafin/odd/serafin.odd` calls it as `tp:gap_dots(@quantity)` to spell
a lacuna of known extent in Leiden dots — `[....]` for four lost characters.

## Argument coercion helpers

XPath passes arguments as nodes, node lists, typed values, or strings. Use the
helpers from [`opm.runtime.xpath_extensions`](../api/runtime.md#xpath-extensions)
to normalize them:

- `expect_element(value)` — unwrap a single lxml element (raises otherwise)
- `expect_string(value)` — coerce to a string
- `expect_text(value)` — like `expect_string`, for human-facing text (strips by default)

## Built-in examples

[`opm.runtime.common_xpath_functions`](../api/runtime.md#built-in-xpath-helper-functions)
ships reusable functions you can register directly or copy:

- `heading_number(div)` — dotted outline number such as `1.2.3` for a TEI `div`
- `roman_fn(n)` — alphabetic apparatus labels
- `highlight(source, language='xml')` — Pygments HTML for a code listing
  (`tp:highlight(string(.), @language)`); used by the DocBook example and tagdocs

## Registering extensions

Register each module in `opm.toml`, with one `[[transform.extensions]]` table
per module:

```toml
[project]
pythonpath = ["."]            # project root on sys.path

[transform]
odd = "odd/my-customisation.odd"

[[transform.extensions]]
module = "extensions.my_functions"
```

Without a prefix, functions in the module are registered under the `tp:` prefix by default.

An `[[transform.extensions]]` table closes the `[transform]` table in TOML:
any plain `[transform]` key written after it would belong to the extension
instead. Put the tables after the last `[transform]` key, before the next
section such as `[transform.web]`.

See [Configuration](configuration.md) for the full schema.

## Using your own prefix

ODDs written for TEI Publisher often call functions from the app's own XQuery
module, for example `ext-html:output-entity(.)`. To run such an ODD unchanged,
write the functions in Python and register the module under the same prefix:

```toml
[[transform.extensions]]
module = "extensions.ext_html"
prefix = "ext-html"
```

Without `prefix`, a module's functions use `tp:`. Several modules may share
a prefix. If the ODD or `[transform.namespaces]` binds the prefix to a namespace,
`opm` uses it; otherwise any namespace will do, and you can set one with
`namespace = "…"` if you need a particular one.

Port each XQuery function you need to a Python function of the same name:

```python
# extensions/ext_html.py
from opm.runtime.xpath_extensions import expect_string


def bible_passage_citation(target):
    """ext-html:bible-passage-citation(@target)"""
    book, _, locus = expect_string(target).partition(' ')
    return f'{book}. {locus}'
```

## Custom behaviours

A TEI Publisher app can also define behaviours in its extension module, which
the ODD then uses like the built-in ones: `<model behaviour="footnote">`. In
`opm`, mark such a function with `@behaviour`:

```python
# extensions/ext_html.py
from opm.runtime.extensions import behaviour

_GROUPS = {'original': '1', 'textcritical': '2', 'digital': '3'}


@behaviour
def footnote(pmf, config, node, cls, content, place=None, label=None):
    """Render like note, but tag the footnote reference with its group."""
    result = pmf.builtin.note(config, node, cls, content, place, label)
    for el in result:
        if hasattr(el, 'set'):
            el.set('data-fn-group', _GROUPS.get(node.get('type'), '4'))
    return result
```

A behaviour receives the same arguments as the built-in ones, with the output
functions (`pmf`) first:

- `config` — the run's context, passed on to any behaviour you call
- `node` — the TEI element being processed
- `cls` — the CSS classes of the model
- `content` — the model's `content` parameter (by default the element itself)
- further keyword arguments — the model's other `<param>`s, by name. Your
  function receives only those it lists, so `place` and `label` above come
  from `<param name="place" …/>` and `<param name="label" …/>`.

It returns a list of output nodes. The easiest way to produce them is to call a
built-in behaviour through `pmf.builtin`, as above, and adjust its result. The
output depends on the format: HTML elements for web output, text for Markdown,
and so on. To limit a module's behaviours to some formats, list them:

```toml
[[transform.extensions]]
module = "extensions.ext_html"
prefix = "ext-html"
output = ["web"]
```

The XPath functions of the module stay available everywhere. In the other
formats the ODD's `behaviour="footnote"` then renders the note's content
without any behaviour, which is also what happens to a behaviour no module
defines.

The function name is the behaviour name, with `-` written as `_`. Give the name
explicitly when that does not fit: `@behaviour("next-part")`. A behaviour named
like a built-in one, such as `note`, replaces it for the whole project;
`pmf.builtin.note(…)` still reaches the original.

## Caching note

Compiled XPath expressions and `$parameters` maps are cached by
`(expression, namespace, extension fingerprint)`. The fingerprint includes each
extension module's source mtime, so editing an extension invalidates the cache
automatically.
