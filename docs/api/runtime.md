# Runtime

The tree-walking engine that drives a transform: `apply()` / `apply_children()`
route each element through the generated `_dispatch` router, evaluate XPath, and
cache compiled expressions. `xpath_extensions` loads user-defined `tp:*`
functions — see the [XPath extensions guide](../guide/xpath-extensions.md).

## Processing-model runtime

::: opm.runtime.pm_runtime

## XPath extensions

::: opm.runtime.xpath_extensions

## Built-in XPath helper functions

::: opm.runtime.common_xpath_functions
