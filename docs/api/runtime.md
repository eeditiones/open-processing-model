# Runtime

The tree-walking engine that drives a transform: `apply()` / `apply_children()`
route each element through the generated `_dispatch` router. Every output
function receives the run's `RenderContext` as `config`; XPath is evaluated by
the context's `XPathEnvironment`, which is built once per document and caches
the parsed node trees. `xpath_extensions` loads user-defined `tp:*` functions —
see the [XPath extensions guide](../guide/xpath-extensions.md).

To drive a compiled module yourself, build one environment per document and
pass it to each transform:

```python
from opm.runtime import XPathEnvironment
from opm.transform import run_transform

env = XPathEnvironment(base_uri=path.resolve().as_uri(), extensions=['my.ext'])
html = run_transform(mod, root, xpath_env=env)
```

## Render context

::: opm.runtime.context

## XPath environment

::: opm.runtime.xpath_env

## XPath errors

An expression that fails at run time counts as false or empty. Wrap a run in
`collect_xpath_errors()` to see which ones failed.

::: opm.runtime.xpath_diagnostics

## Processing-model runtime

::: opm.runtime.pm_runtime

## XPath extensions

::: opm.runtime.xpath_extensions

## Built-in XPath helper functions

::: opm.runtime.common_xpath_functions
