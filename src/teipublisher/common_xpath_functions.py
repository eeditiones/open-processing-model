"""Common XPath extension functions shared across projects."""

from __future__ import annotations

import re
from typing import Any
from datetime import date, datetime

from babel.dates import format_date as babel_format_date
from teipublisher.xpath_extensions import expect_string


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
