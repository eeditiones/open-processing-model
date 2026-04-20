"""Sample XPath extension module for tests (public callables → ``tp:`` functions)."""

from __future__ import annotations

import re
from datetime import datetime

import lxml.etree as ET
from tei_publisher_py.xpath_extensions import expect_element

_MONTH_NAMES = {
    '01': 'January',
    '02': 'February',
    '03': 'March',
    '04': 'April',
    '05': 'May',
    '06': 'June',
    '07': 'July',
    '08': 'August',
    '09': 'September',
    '10': 'October',
    '11': 'November',
    '12': 'December',
}


def greet(who: str) -> str:
    return f'Hello {who}'


def date_popover(node: ET._Element) -> ET._Element:
    """Return a ``<span>`` with a popover-style title for a TEI ``<date when="">`` element."""
    node = expect_element(node, arg_name='date_popover()')

    when = (node.get('when') or '').strip()
    text = ''.join(node.itertext()).strip() or when or 'date'
    formatted = _format_when_for_popover(when) if when else text

    span = ET.Element('span')
    span.set('class', 'tp-date-popover')
    span.set('title', formatted)
    span.set('data-when', when)
    span.text = text
    return span


def _format_when_for_popover(when: str) -> str:
    if re.fullmatch(r'\d{4}', when):
        return when

    if re.fullmatch(r'\d{4}-\d{2}', when):
        year, month = when.split('-', 1)
        month_name = _MONTH_NAMES.get(month, month)
        return f'{month_name} {year}'

    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', when):
        try:
            dt = datetime.strptime(when, '%Y-%m-%d')
        except ValueError:
            return when
        return f'{dt.day} {_MONTH_NAMES[dt.strftime("%m")]} {dt.year}'

    return when
