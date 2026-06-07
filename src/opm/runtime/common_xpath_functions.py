"""Common XPath extension functions shared across projects."""

from __future__ import annotations

import re
from typing import Any
from datetime import date, datetime

import lxml.etree as ET
from babel.dates import format_date as babel_format_date
from elementpath.xpath_nodes import XPathNode
from opm.runtime.xpath_extensions import expect_element, expect_string

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


def format_date(when: Any, locale: Any = 'en') -> str:
    """Format a TEI-style xs:date value for display in a popover/title."""
    when = expect_string(when, arg_name='format_date(when)')
    locale = expect_string(locale, arg_name='format_date(locale)')

    if re.fullmatch(r'\d{4}', when):
        return when

    if re.fullmatch(r'\d{4}-\d{2}', when):
        year_str, month_str = when.split('-', 1)
        try:
            parsed = date(int(year_str), int(month_str), 1)
        except ValueError:
            return when
        return babel_format_date(parsed, format='MMMM y', locale=locale)

    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', when):
        try:
            parsed = datetime.strptime(when, '%Y-%m-%d').date()
        except ValueError:
            return when
        return babel_format_date(parsed, format='d MMMM y', locale=locale)

    return when


def _is_tei_div(node: ET._Element | None) -> bool:
    if node is None or not isinstance(node.tag, str):
        return False
    qn = ET.QName(node)
    return qn.namespace == TEI_NS and qn.localname == 'div'


def heading_number(div: Any) -> str:
    """Port of ``pmf:heading-number`` from ``ext-common.xql`` (TEI ``div`` outline numbering).

    Returns a dotted index such as ``1.2.3``: at each level, the 1-based index among
    preceding ``tei:div`` siblings, joined from outer ancestor ``div`` down to *div*.
    """
    if isinstance(div, (list, tuple)):
        if len(div) != 1:
            raise ValueError('heading_number() expects a single node')
        div = div[0]
    node = expect_element(div, arg_name='heading_number()')

    parts: list[str] = []
    cur: ET._Element = node
    while True:
        n = 1
        for sib in cur.itersiblings(preceding=True):
            if _is_tei_div(sib):
                n += 1
        parts.append(str(n))
        parent = cur.getparent()
        if not _is_tei_div(parent):
            break
        cur = parent
    parts.reverse()
    return '.'.join(parts)


# Alphabet for apparatus labels (a-z, excluding j) - matches ec:roman-fn
_APP_CHARS = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'k', 'l', 'm',
              'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z']


def _to_app_label(n: int) -> str:
    """Convert 1-based index to apparatus label (cycles through a-z, no j).

    Matches ec:roman-fn from ext-common.xql: $chars[($n mod 25) + 1]
    """
    if n <= 0:
        return str(n)
    return _APP_CHARS[(n - 1) % 25]

def roman_fn(n: Any) -> str:
    """XPath-accessible version of ec:roman-fn.

    Takes an integer (1-based count) and returns a letter (a-z, no j),
    cycling through the alphabet using mod 25 arithmetic.

    Example: 1 -> 'a', 25 -> 'z', 26 -> 'a', etc.
    """
    if isinstance(n, (list, tuple)):
        if len(n) != 1:
            raise ValueError('roman_fn() expects a single integer')
        n = n[0]
    try:
        num = int(n)
    except (TypeError, ValueError):
        return str(n)
    return _to_app_label(num)


# ── tp:id() — fast xml:id lookup ───────────────────────────────────────────────
#
# elementpath's built-in id() scans every node in the document tree (O(N)),
# because it was designed for DTD-typed ID attributes rather than xml:id.
# This extension builds a {xml:id → element} dict once per document root and
# caches it, giving O(1) lookups on every subsequent call.

_xml_id_index_cache: dict[int, dict[str, ET._Element]] = {}
_object_id = id  # preserve built-in before our `id` function shadows it


def _xml_id_index(doc_root: ET._Element) -> dict[str, ET._Element]:
    """Return (cached) ``{xml:id value → element}`` dict for *doc_root*."""
    key = _object_id(doc_root)
    idx = _xml_id_index_cache.get(key)
    if idx is None:
        idx = {
            el.get(XML_ID): el
            for el in doc_root.iter()
            if el.get(XML_ID) is not None
        }
        _xml_id_index_cache[key] = idx
    return idx


def lookup(idref: Any, context_node: Any = None) -> list:
    """Fast ``tp:lookup(idref, context_node)`` — O(1) xml:id lookup via a cached index.

    Drop-in replacement for XPath ``id()`` in ODD expressions::

        id($target, root(.))           →  tp:lookup($target, root(.))
        id(substring-after(@ref,'#'))  →  tp:lookup(substring-after(@ref,'#'), root(.))

    The second argument must resolve to any node in the target document so the
    function can locate the document root.  Passing ``root(.)`` is idiomatic.
    """
    id_str = str(idref).lstrip('#') if idref is not None else ''
    if not id_str:
        return []

    node = context_node
    if isinstance(node, XPathNode):
        node = node.value
    # EtreeDocumentNode.value is an _ElementTree; EtreeElementNode.value is _Element
    if isinstance(node, ET._ElementTree):
        node = node.getroot()
    if not isinstance(node, ET._Element):
        return []

    doc_root = node.getroottree().getroot()
    idx = _xml_id_index(doc_root)
    el = idx.get(id_str)
    if el is None:
        return []

    # Return the node wrapper from the *same* cached elementpath tree so that
    # subsequent path steps (e.g. /node(), /bibl) work correctly.
    from opm.runtime.pm_runtime import _xpath_root_wrapped
    doc_wrapped = _xpath_root_wrapped(doc_root)
    wrapped_el = doc_wrapped.elements.get(el)
    return [wrapped_el] if wrapped_el is not None else []


def clear_xml_id_index_cache() -> None:
    """Invalidate the xml:id index (e.g. after the document changes)."""
    _xml_id_index_cache.clear()

