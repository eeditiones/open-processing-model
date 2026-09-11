# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Common XPath extension functions shared across projects."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any
from datetime import date, datetime

import lxml.etree as ET
from babel.dates import format_date as babel_format_date
from elementpath.tree_builders import get_node_tree
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


# ── tp:request(uri) — HTTP GET with XML-or-string response ───────────────────────

_REQUEST_TIMEOUT_SECS = 30


def _is_xml_content_type(content_type: str) -> bool:
    """True when *content_type* indicates an XML payload."""
    ct = content_type.split(';', 1)[0].strip().lower()
    return ct in ('application/xml', 'text/xml') or ct.endswith('+xml')


def _wrap_fetched_element(el: ET._Element):
    """Wrap a parsed lxml element for further XPath steps (e.g. ``/child``)."""
    wrapped = get_node_tree(el.getroottree())
    node = wrapped.elements.get(el)
    if node is None:
        raise ValueError('request() failed to wrap fetched XML document')
    return node


def request(uri: Any) -> Any:
    """``tp:request(uri)`` — HTTP GET to *uri*; XML responses become element nodes.

    Inspects the response ``Content-Type``: XML media types (``application/xml``,
    ``text/xml``, or ``*/*+xml``) are parsed and returned as an elementpath node
    so path expressions such as ``tp:request($uri)/entry`` work.  All other types
    are returned as a decoded string.

    When the surrounding document uses a default element namespace (e.g. TEI),
    unprefixed child steps on the fetched tree resolve in that namespace; for
    namespace-less API XML use ``*[local-name()='entry']`` instead of ``/entry``.
    """
    uri = expect_string(uri, arg_name='request(uri)')
    if not uri:
        raise ValueError('request(uri) expects a non-empty URI')

    http_req = urllib.request.Request(
        uri,
        method='GET',
        headers={'User-Agent': 'opm/1.0 tp:request'},
    )
    try:
        with urllib.request.urlopen(http_req, timeout=_REQUEST_TIMEOUT_SECS) as resp:
            body = resp.read()
            content_type = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset() or 'utf-8'
    except urllib.error.URLError as e:
        raise ValueError(f'request({uri!r}) failed: {e}') from e

    if _is_xml_content_type(content_type):
        if not body.strip():
            # eXist REST returns 200 + application/xml with an empty body when
            # _xpath matches nothing (_wrap=no); treat as an empty result.
            return ''
        try:
            el = ET.fromstring(body)
        except ET.XMLSyntaxError as e:
            raise ValueError(f'request({uri!r}) returned invalid XML: {e}') from e
        return _wrap_fetched_element(el)

    return body.decode(charset, errors='replace')

