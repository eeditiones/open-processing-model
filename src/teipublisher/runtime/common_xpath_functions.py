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
