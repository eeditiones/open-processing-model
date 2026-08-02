# XPath extensions

ODD predicates and parameters are XPath 3.1 expressions. You can extend them with
your own functions, exposed in the `tp:` namespace. This is how you add logic
that goes beyond plain XPath — date formatting, outline numbering, project
lookups, and so on.

## Writing an extension module

An extension module is an ordinary Python module. Every **public** callable (a
name that does not start with `_`) is registered as `tp:<name>`. Underscores in
the Python name become hyphens in XPath, matching XPath naming conventions.

```python
# extensions/my_functions.py
from opm.runtime.xpath_extensions import expect_string


def shout(value):
    """Available in ODD XPath as tp:shout(...)."""
    return expect_string(value, arg_name='shout(value)').upper()
```

In an ODD model predicate or parameter:

```xml
<param name="label" value="tp:shout(@type)"/>
```

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

## Registering extensions

Per transform on the command line (repeatable):

```bash
uv run opm transform demo/tei-test.xml -d odd/teipublisher.odd \
  --xpath-extensions extensions.my_functions
```

Or for every command, in `opm.toml`:

```toml
[project]
pythonpath = ["extensions"]   # make local modules importable

[transform]
xpath_extensions = ["extensions.my_functions"]
```

See [Configuration](configuration.md) for the full schema.

## Caching note

Compiled XPath expressions and `$parameters` maps are cached by
`(expression, namespace, extension fingerprint)`. The fingerprint includes each
extension module's source mtime, so editing an extension invalidates the cache
automatically.
