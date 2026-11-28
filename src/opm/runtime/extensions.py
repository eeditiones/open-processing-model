# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Project extension modules: XPath functions under a prefix, and custom behaviours.

A TEI Publisher app ships extension modules such as ``ext-html.xql``: the ODD
calls their functions under a prefix (``ext-html:output-entity(.)``) and uses
their functions as behaviours by bare name (``behaviour="footnote"``). opm
does the same with a Python module registered in ``opm.toml``:

```toml
[[transform.extensions]]
module = "extensions.ext_html"
prefix = "ext-html"
output = ["web"]        # optional: the output types its behaviours apply to
```

Public functions of the module become XPath functions under the prefix, both
under their Python name and with ``_`` spelled ``-``. Functions marked with
[`behaviour`][opm.runtime.extensions.behaviour] become behaviours instead. A
behaviour takes the output-functions instance first, then the arguments the
built-in behaviours take::

    @behaviour
    def footnote(pmf, config, node, cls, content, place=None, label=None):
        return pmf.builtin.note(config, node, cls, content, place, label)

A behaviour named like a built-in one (``note``) replaces it;
``pmf.builtin`` still reaches the stock implementation.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Any, Callable

#: Prefix of extension modules without one (also every ``[transform] xpath_extensions`` entry).
DEFAULT_PREFIX = 'tp'

#: Attribute marking a function as a behaviour; its value is the method name.
BEHAVIOUR_ATTR = '__opm_behaviour__'

_CAMEL_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')
_NCNAME_RE = re.compile(r'^[A-Za-z_][\w.-]*$')


@dataclass(frozen=True, slots=True)
class ExtensionModule:
    """One extension module from ``opm.toml``.

    Args:
        module: Dotted import path.
        prefix: XPath prefix its functions are called with.
        namespace: Namespace URI bound to *prefix*; ``None`` uses the ODD's or
            the project's binding of the prefix, else ``urn:opm:ext:<prefix>``.
        outputs: Output types its behaviours apply to; empty means all.
    """

    module: str
    prefix: str = DEFAULT_PREFIX
    namespace: str | None = None
    outputs: tuple[str, ...] = ()

    def applies_to(self, output: str) -> bool:
        """Whether this module's behaviours take part in *output*."""
        return not self.outputs or output in self.outputs


def valid_prefix(prefix: str) -> bool:
    """Whether *prefix* can be used as an XPath namespace prefix."""
    return bool(_NCNAME_RE.match(prefix)) and ':' not in prefix


def as_extension_module(value: Any) -> ExtensionModule:
    """*value* as an [`ExtensionModule`][opm.runtime.extensions.ExtensionModule]; a string is a ``tp:`` module."""
    if isinstance(value, ExtensionModule):
        return value
    return ExtensionModule(module=str(value).strip())


def method_name(behaviour: str) -> str:
    """Python method name for an ODD behaviour name.

    ``pass-through`` → ``pass_through``, ``listItem`` → ``list_item``,
    ``break`` → ``break_``: the rule that also yields every built-in in
    [`BEHAVIOUR_METHOD`][opm.odd_compiler.behaviour_map.BEHAVIOUR_METHOD].
    """
    name = _CAMEL_RE.sub('_', behaviour).replace('-', '_').replace('.', '_').lower()
    if keyword.iskeyword(name) or not name.isidentifier():
        name = f'{name}_'
    return name


def behaviour(arg: Callable | str | None = None) -> Any:
    """Mark a function of an extension module as a behaviour.

    Use it bare (``@behaviour``), named after the function, or with the ODD
    name when that is not a Python name (``@behaviour("next-part")``).
    """
    def mark(fn: Callable, name: str | None) -> Callable:
        setattr(fn, BEHAVIOUR_ATTR, method_name(name or fn.__name__))
        return fn

    if callable(arg):
        return mark(arg, None)
    return lambda fn: mark(fn, arg)


# The decorator must not become an XPath function of every module importing it.
setattr(behaviour, BEHAVIOUR_ATTR, None)


def is_behaviour(obj: Any) -> bool:
    """Whether *obj* is a behaviour (or the decorator), not an XPath function."""
    return hasattr(obj, BEHAVIOUR_ATTR)


def load_behaviours(module_path: str) -> dict[str, Callable]:
    """The behaviours *module_path* defines, by method name."""
    mod = import_module(module_path)
    out: dict[str, Callable] = {}
    for name in dir(mod):
        obj = getattr(mod, name)
        method = getattr(obj, BEHAVIOUR_ATTR, None) if callable(obj) else None
        if method:
            out[method] = obj
    return out


@lru_cache(maxsize=64)
def _extended_class(base: type, modules: tuple[str, ...], fingerprint: str) -> type:
    _ = fingerprint  # part of the cache key only: a changed module rebuilds the class
    methods: dict[str, Callable] = {}
    for module_path in modules:
        methods.update(load_behaviours(module_path))
    if not methods:
        return base
    cls = type(base.__name__, (base,), dict(methods))
    cls._opm_extended = cls  # type: ignore[attr-defined]
    cls.__module__ = base.__module__
    cls.__qualname__ = f'{base.__qualname__}+extensions'
    return cls


def extended_output_functions(base: type, extensions, output: str) -> type:
    """*base* with the behaviours of *extensions* that apply to *output* added.

    Returns *base* itself when no extension module defines a behaviour for
    *output*. Later modules win over earlier ones, and all over the built-ins.
    """
    from .xpath_extensions import fingerprint_for_module  # noqa: PLC0415

    modules = tuple(
        ext.module for ext in map(as_extension_module, extensions or ())
        if ext.module and ext.applies_to(output)
    )
    if not modules:
        return base
    fp = '\x1f'.join(fingerprint_for_module(m) for m in modules)
    return _extended_class(base, modules, fp)


def clear_cache() -> None:
    """Forget extended classes (e.g. between tests)."""
    _extended_class.cache_clear()
