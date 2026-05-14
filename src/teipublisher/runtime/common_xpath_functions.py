"""Common XPath extension functions shared across projects."""

from __future__ import annotations

import re
from typing import Any
from datetime import date, datetime

import lxml.etree as ET
from babel.dates import format_date as babel_format_date
from teipublisher.runtime.xpath_extensions import expect_element, expect_string

TEI_NS = 'http://www.tei-c.org/ns/1.0'


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


XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


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


