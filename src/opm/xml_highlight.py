# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Syntax highlighting for documentation listings via Pygments."""

from __future__ import annotations

import re
from functools import lru_cache

from lxml import etree
from lxml import html as lxml_html
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(nowrap=True)
# Pygments wraps each run of whitespace in ``<span class="w">``; unwrap so
# example text stays contiguous and the HTML stays smaller.
_W_SPAN_RE = re.compile(r'<span class="w">(\s*)</span>')
_MISSING = object()
_LEXERS: dict[str, object] = {}


def _lexer(language: str):
    key = language.strip().lower()
    if not key:
        return None
    cached = _LEXERS.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    try:
        lexer = get_lexer_by_name(key, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = None
    _LEXERS[key] = lexer
    return lexer


@lru_cache(maxsize=256)
def highlight_code(source: str, language: str) -> str | None:
    """Return Pygments HTML for *source*, or ``None`` if *language* is unknown."""
    if not source:
        return ''
    lexer = _lexer(language)
    if lexer is None:
        return None
    return _W_SPAN_RE.sub(r'\1', highlight(source, lexer, _FORMATTER))


def highlight_xml(source: str) -> str:
    """Return Pygments HTML for XML *source* (inner ``<span>`` markup only)."""
    return highlight_code(source, 'xml') or ''


def highlight_markup(source: str, language: str) -> etree._Element | None:
    """Wrap Pygments spans in ``<span class="highlight">``, or ``None``.

    The wrapper is finished HTML, so ``behaviour="code"`` can insert it without
    escaping. Unknown languages return ``None`` (caller keeps the source text).
    """
    html = highlight_code(source, language)
    if not html:
        return None
    try:
        inner = lxml_html.fragment_fromstring(f'<div>{html}</div>')
    except etree.ParserError:
        return None
    wrap = etree.Element('span')
    wrap.set('class', 'highlight')
    wrap.text = inner.text
    for child in list(inner):
        wrap.append(child)
    return wrap
