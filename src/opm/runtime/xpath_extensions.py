# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Load Python callables as XPath 3.1 extension functions (``tp:`` or a project prefix)."""

from __future__ import annotations

import importlib
import inspect
import os
from typing import Any, Callable, cast

from elementpath.exceptions import ElementPathValueError
from elementpath.xpath_nodes import XPathNode
import lxml.etree as ET

from .extensions import is_behaviour
from .xpath_parser import OpmXPathParser

# Stable namespace for ``tp:yourFunction()`` in XPath expressions.
TEI_PUBLISHER_XPATH_EXT_PREFIX = 'tp'
TEI_PUBLISHER_XPATH_EXT_NS = 'https://opm.e-editiones.org/ns/xpath-extensions'


def extension_namespace_map() -> dict[str, str]:
    return {TEI_PUBLISHER_XPATH_EXT_PREFIX: TEI_PUBLISHER_XPATH_EXT_NS}


def default_extension_namespace(prefix: str) -> str:
    """Namespace of a project prefix no ODD or project declaration binds."""
    return f'urn:opm:ext:{prefix}'


#: Attribute a ``tp:`` function carries to declare its XPath signature.
_SEQUENCE_TYPES_ATTR = 'xpath_sequence_types'


def sequence_types(*types: str) -> Callable[[Any], Any]:
    """Declare the XPath argument and return types of a ``tp:`` function.

    Registration otherwise lets elementpath infer ``item()?`` for every
    argument, which is right for the functions that take one node or one
    string. A function that takes a node *set* has to say so, or elementpath
    rejects the call with ``XPTY0004`` before the function ever runs. The last
    entry is the return type, as elementpath expects.
    """
    def decorate(fn: Any) -> Any:
        setattr(fn, _SEQUENCE_TYPES_ATTR, types)
        return fn
    return decorate


def expect_element(value: Any, *, arg_name: str = 'argument') -> ET._Element:
    """Unwrap an XPath item and require an lxml element.

    Extension functions receive XPath values; node items can arrive as
    `XPathNode` wrappers.
    """
    if isinstance(value, XPathNode):
        value = value.value
    if not isinstance(value, ET._Element):
        raise ValueError(f'{arg_name} expects an element node')
    return cast(ET._Element, value)


def _unwrap_xpath_singleton(value: Any) -> Any:
    """Unwrap common XPath containers and node wrappers."""
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError('expected a single XPath item')
        value = value[0]
    if isinstance(value, XPathNode):
        return value.value
    return value


def expect_string(value: Any, *, arg_name: str = 'argument') -> str:
    """Normalize an XPath argument to a string.

    Accepts atomics, single-item sequences, XPathNode wrappers, and elements.
    Elements are converted from their string value (concatenated descendant text).
    """
    value = _unwrap_xpath_singleton(value)
    if isinstance(value, ET._Element):
        return ''.join(value.itertext())
    if value is None:
        raise ValueError(f'{arg_name} expects a string-compatible value')
    return str(value)


def expect_text(value: Any, *, arg_name: str = 'argument', strip: bool = True) -> str:
    """Like [`expect_string`][opm.runtime.xpath_extensions.expect_string] but intended for human-facing text."""
    text = expect_string(value, arg_name=arg_name)
    return text.strip() if strip else text


def fingerprint_for_module(module_dotted_path: str) -> str:
    """Cache key fragment: import path plus source mtime when available."""
    mod = importlib.import_module(module_dotted_path)
    path = getattr(mod, '__file__', None)
    if path:
        try:
            st = os.stat(path)
            return f'{module_dotted_path}\0{st.st_mtime_ns}'
        except OSError:
            pass
    return f'{module_dotted_path}\0'


def load_extension_callables(module_dotted_path: str) -> dict[str, Callable[..., Any]]:
    """Import *module_dotted_path* and collect public callables (name does not start with ``_``).

    Skips classes and non-routine callables so ``tp:`` functions map to plain functions/methods,
    and functions marked as behaviours (see [`opm.runtime.extensions`][opm.runtime.extensions]).
    A name with ``_`` is also registered with ``-`` (``output_entity`` → ``output-entity``),
    the spelling XQuery modules use.
    """
    mod = importlib.import_module(module_dotted_path)
    out: dict[str, Callable[..., Any]] = {}
    for name in dir(mod):
        if name.startswith('_'):
            continue
        obj = getattr(mod, name)
        if inspect.isclass(obj):
            continue
        if not (inspect.isroutine(obj) or callable(obj)):
            continue
        # Unbound methods etc. are routines; avoid modules
        if inspect.ismodule(obj) or is_behaviour(obj):
            continue
        out[name] = obj
        dashed = name.replace('_', '-')
        if dashed != name:
            out.setdefault(dashed, obj)
    return out


def build_extension_parser(
    default_element_ns: str,
    callables: dict[str, Callable[..., Any]],
    namespaces: dict[str, str] | None = None,
    base_uri: str | None = None,
    *,
    prefixed: dict[str, tuple[str | None, dict[str, Callable[..., Any]]]] | None = None,
) -> OpmXPathParser:
    """Create an `OpmXPathParser` with ``tp:`` external functions.

    *prefixed* adds functions under project prefixes: prefix →
    ``(namespace, {name: callable})``. A ``None`` namespace keeps the binding
    *namespaces* gives the prefix, else
    [`default_extension_namespace`][opm.runtime.xpath_extensions.default_extension_namespace].
    """
    ns = dict(namespaces) if namespaces else {}
    ns.update(extension_namespace_map())  # tp: always means opm's extension namespace
    groups: dict[str, dict[str, Callable[..., Any]]] = {TEI_PUBLISHER_XPATH_EXT_PREFIX: dict(callables)}
    for prefix, (uri, fns) in (prefixed or {}).items():
        if prefix == TEI_PUBLISHER_XPATH_EXT_PREFIX:
            groups[prefix].update(fns)
            continue
        if uri:
            ns[prefix] = uri
        else:
            ns.setdefault(prefix, default_extension_namespace(prefix))
        groups.setdefault(prefix, {}).update(fns)
    kwargs: dict[str, Any] = {'namespaces': ns}
    if default_element_ns:
        kwargs['default_namespace'] = default_element_ns
    if base_uri:
        kwargs['base_uri'] = base_uri
    parser = OpmXPathParser(**kwargs)
    for prefix, fns in groups.items():
        for name, fn in sorted(fns.items()):
            try:
                parser.external_function(
                    fn,
                    name=name,
                    prefix=prefix,
                    sequence_types=getattr(fn, _SEQUENCE_TYPES_ATTR, ()),
                )
            except ElementPathValueError as e:
                if name.replace('-', '_') in fns and '-' in name:
                    continue  # only the dashed alias clashes; the Python name stands
                raise ElementPathValueError(
                    f'XPath extension {prefix}:{name} could not be registered: {e}',
                ) from e
    return parser
