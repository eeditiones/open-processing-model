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
from elementpath.xpath_nodes import XPathNode
from opm.runtime.xpath_extensions import expect_element, expect_string

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
_XMLNS_ATTR_RE = re.compile(r'\s+xmlns(?::\w+)?="[^"]*"')


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


# ── tp:normalize_egxml / tp:serialize_egxml — ODD example whitespace ─────────────


def normalize_egxml(text: Any) -> str:
    """``tp:normalize_egxml(.)`` — strip ODD embedding indent from example source.

    Dedents common leading whitespace and soft-wrapped continuation lines so
    ``eg`` / materialized ``egXML`` text matches the TEI stylesheets' display
    (nested source indent is an artefact of the ODD file, not the example).
    """
    raw = expect_string(text, arg_name='normalize_egxml()')
    return _normalize_egxml_source(raw)


def serialize_egxml(node: Any) -> str:
    """``tp:serialize_egxml(.)`` — egXML inner XML with normalized whitespace.

    Element children are serialized as XML (``with_tail`` handled for mixed
    content); a text-only node is passed through
    [`normalize_egxml`][opm.runtime.common_xpath_functions.normalize_egxml].
    xmlns declarations are stripped so example listings stay readable.
    """
    value: Any = node
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise ValueError('serialize_egxml() expects a single item')
        value = value[0]
    if isinstance(value, XPathNode):
        value = value.value
    if isinstance(value, ET._Element):
        if any(isinstance(child.tag, str) for child in value):
            return _serialize_egxml_body(value)
        return _normalize_egxml_source(''.join(value.itertext()))
    return _normalize_egxml_source(expect_string(value, arg_name='serialize_egxml()'))


def _normalize_egxml_source(text: str) -> str:
    """Dedent common leading whitespace from serialized example source."""
    if not text:
        return ''
    text = text.replace('\t', '    ')
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return ''
    # Shared pad across *all* nonempty lines. Pretty-printed XML starts at
    # column 0, so pad is 0 and structural indent is preserved. Plain ``eg``
    # text nested in an ODD shares a pad on every line and is fully dedented.
    pad = min(len(line) - len(line.lstrip(' ')) for line in nonempty)
    if pad:
        lines = [line[pad:] if len(line) >= pad else line for line in lines]
    return '\n'.join(lines).strip()


def _normalize_egxml_text_node(text: str) -> str:
    """Drop per-line indent from soft-wrapped text; keep the line breaks."""
    if '\n' not in text:
        return text
    lines = text.split('\n')
    out = [lines[0].rstrip()]
    for line in lines[1:]:
        out.append(line.strip())
    return '\n'.join(out)


def _normalize_egxml_tree_text(el: ET._Element) -> None:
    """Normalize soft-wraps; clear indent-only whitespace so pretty_print can indent."""
    if el.text is not None:
        if not el.text.strip():
            el.text = None
        else:
            el.text = _normalize_egxml_text_node(el.text)
    for child in el:
        _normalize_egxml_tree_text(child)
        if child.tail is not None:
            if not child.tail.strip():
                child.tail = None
            else:
                child.tail = _normalize_egxml_text_node(child.tail)


def _serialize_egxml_element(el: ET._Element) -> str:
    copy = ET.fromstring(ET.tostring(el, with_tail=False))
    ET.cleanup_namespaces(copy)
    _normalize_egxml_tree_text(copy)
    text = ET.tostring(copy, encoding='unicode', pretty_print=True)
    return _XMLNS_ATTR_RE.sub('', text).strip()


def _serialize_egxml_body(eg: ET._Element) -> str:
    parts: list[str] = []
    if eg.text and eg.text.strip():
        parts.append(_normalize_egxml_text_node(eg.text))
    for child in eg:
        if isinstance(child.tag, str):
            parts.append(_serialize_egxml_element(child))
        if child.tail and child.tail.strip():
            parts.append(_normalize_egxml_text_node(child.tail))
    return _normalize_egxml_source('\n'.join(parts))


# ── tp:highlight(source, language) — Pygments HTML for a listing ──────────────────


def highlight(source: Any, language: Any = 'xml') -> Any:
    """``tp:highlight($source, $language)`` — Pygments HTML spans for a listing.

    Call from an ODD ``content`` param, typically with ``behaviour="code"``::

        tp:highlight(string(.), (@language, 'xml')[1])

    Returns a ``<span class="highlight">`` of inner ``<span>`` tokens so the
    markup is inserted rather than escaped. Unknown *language* values (and
    empty source) return the source string unchanged.
    """
    raw = expect_string(source, arg_name='highlight(source)')
    if language is None or language == [] or language == ():
        lang = 'xml'
    else:
        lang = expect_string(language, arg_name='highlight(language)').strip() or 'xml'
    if not raw:
        return ''
    from opm.xml_highlight import highlight_markup

    marked = highlight_markup(raw, lang)
    return marked if marked is not None else raw


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

