# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for egXML XML syntax highlighting."""

from __future__ import annotations

from lxml import etree

from opm.xml_highlight import highlight_code, highlight_markup, highlight_xml


def test_highlight_xml_tags_attrs_and_text() -> None:
    html = highlight_xml('<div type="chapter" n="38"><p>Hi</p></div>')
    assert 'class="nt"' in html  # Name.Tag
    assert 'class="na"' in html  # Name.Attribute
    assert 'class="s"' in html   # String (attr value)
    assert '&lt;' in html
    assert 'chapter' in html
    assert 'Hi' in html


def test_highlight_xml_comment_and_empty_element() -> None:
    html = highlight_xml('<!-- note --><pb n="1"/>')
    assert 'class="cm"' in html  # Comment
    assert 'note' in html
    assert 'pb' in html


def test_highlight_xml_escapes_script_payload() -> None:
    html = highlight_xml('<a title="<script>">x</a>')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_highlight_code_json_keywords() -> None:
    html = highlight_code('{"ok": true}', 'json')
    assert html is not None
    assert 'class="nt"' in html or 'class="s2"' in html
    assert 'true' in html


def test_highlight_code_unknown_language_is_none() -> None:
    assert highlight_code('select 1', 'not-a-lexer') is None


def test_highlight_markup_wraps_spans() -> None:
    wrap = highlight_markup('<pb n="1"/>', 'xml')
    assert wrap is not None
    assert wrap.tag == 'span'
    assert wrap.get('class') == 'highlight'
    html = etree.tostring(wrap, encoding='unicode')
    assert 'class="nt"' in html
    assert 'pb' in html
