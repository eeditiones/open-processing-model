# XPath extensions

ODD predicates and parameters are XPath 3.1 expressions. You can extend them with
your own functions, exposed in the `tp:` namespace. This is how you add logic
that goes beyond plain XPath — date formatting, outline numbering, project
lookups, and so on.

## Writing an extension module

An extension module is an ordinary Python module. Every **public** callable (a
name that does not start with `_`) is registered as `tp:<name>`, spelled exactly
as in Python — `gap_dots` is called as `tp:gap_dots(…)`. Names imported into the
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

A worked example ships with the Serafin project:
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

- `format_date(when, locale='en')` — format a TEI `xs:date` for display
- `heading_number(div)` — dotted outline number such as `1.2.3` for a TEI `div`
- `roman_fn(n)` — alphabetic apparatus labels
- `highlight(source, language='xml')` — Pygments HTML for a code listing
  (`tp:highlight(string(.), @language)`); used by the DocBook example and tagdocs

## Registering extensions

Per transform on the command line (repeatable):

```bash
opm transform examples/tei-test.xml \
  --xpath-extensions extensions.my_functions
```

Or for every command, in `opm.toml`:

```toml
[project]
pythonpath = ["."]            # project root on sys.path

[transform]
xpath_extensions = ["extensions.my_functions"]
```

`pythonpath` entries are added to `sys.path` as given (resolved relative to the
config file), so `["."]` plus the `extensions/__init__.py` that `opm init`
writes is what makes the dotted `extensions.my_functions` importable.

See [Configuration](configuration.md) for the full schema.

## Caching note

Compiled XPath expressions and `$parameters` maps are cached by
`(expression, namespace, extension fingerprint)`. The fingerprint includes each
extension module's source mtime, so editing an extension invalidates the cache
automatically.
