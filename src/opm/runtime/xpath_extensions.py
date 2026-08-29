"""Load Python callables as XPath 3.1 extension functions (``tp:`` prefix)."""

from __future__ import annotations

import importlib
import inspect
import os
from typing import Any, Callable, cast

from elementpath.exceptions import ElementPathValueError
from elementpath.xpath_nodes import XPathNode
from elementpath.xpath31.xpath31_parser import XPath31Parser
import lxml.etree as ET

# Stable namespace for ``tp:yourFunction()`` in XPath expressions.
TEI_PUBLISHER_XPATH_EXT_PREFIX = 'tp'
TEI_PUBLISHER_XPATH_EXT_NS = 'https://opm.e-editiones.org/ns/xpath-extensions'


def extension_namespace_map() -> dict[str, str]:
    return {TEI_PUBLISHER_XPATH_EXT_PREFIX: TEI_PUBLISHER_XPATH_EXT_NS}


def expect_element(value: Any, *, arg_name: str = 'argument') -> ET._Element:
    """Unwrap an XPath item and require an lxml element.

    Extension functions receive XPath values; node items can arrive as
    :class:`~elementpath.xpath_nodes.XPathNode` wrappers.
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
    """Like :func:`expect_string` but intended for human-facing text."""
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

    Skips classes and non-routine callables so ``tp:`` functions map to plain functions/methods.
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
        if inspect.ismodule(obj):
            continue
        out[name] = obj
    return out


def build_extension_parser(
    default_element_ns: str,
    callables: dict[str, Callable[..., Any]],
    namespaces: dict[str, str] | None = None,
    base_uri: str | None = None,
) -> XPath31Parser:
    """Create an :class:`~elementpath.xpath31.xpath31_parser.XPath31Parser` with ``tp:`` external functions."""
    ns = extension_namespace_map()
    if namespaces:
        ns = {**namespaces, **ns}  # ODD namespaces take precedence over tp: prefix
    kwargs: dict[str, Any] = {'namespaces': ns}
    if default_element_ns:
        kwargs['default_namespace'] = default_element_ns
    if base_uri:
        kwargs['base_uri'] = base_uri
    parser = XPath31Parser(**kwargs)
    for name, fn in sorted(callables.items()):
        try:
            parser.external_function(
                fn,
                name=name,
                prefix=TEI_PUBLISHER_XPATH_EXT_PREFIX,
                sequence_types=(),
            )
        except ElementPathValueError as e:
            raise ElementPathValueError(
                f'XPath extension {name!r} could not be registered: {e}',
            ) from e
    return parser
