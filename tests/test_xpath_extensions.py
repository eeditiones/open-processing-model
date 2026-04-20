"""Tests for XPath ``tp:`` extension functions from Python modules."""

from __future__ import annotations

from lxml import etree
import pytest

from tei_publisher_py.pm_runtime import resolve_context_element, xpath_select_nodes, xpath_test
from tei_publisher_py.xpath_extensions import expect_string, expect_text


def test_tp_function_in_xpath_select() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(f'<div xmlns="{TEI}"><p>a</p></div>')
    p = root[0]
    r = xpath_select_nodes(
        p,
        'tp:greet("world")',
        xpath_extensions='tests.extensions_sample',
    )
    assert r == 'Hello world'


def test_tp_function_boolean_predicate() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(f'<div xmlns="{TEI}"><p/></div>')
    p = root[0]
    ok = xpath_test(
        p,
        'starts-with(tp:greet(.), "Hello")',
        xpath_extensions='tests.extensions_sample',
    )
    assert ok is True


def test_resolve_context_element_with_tp_in_xpath() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><body><p>ok</p></body></text></TEI>',
    )
    el = resolve_context_element(
        root,
        '//body/p[tp:greet(string(.)) = "Hello ok"]',
        xpath_extensions='tests.extensions_sample',
    )
    assert el.text == 'ok'


def test_tp_date_popover_accepts_element_and_formats_when() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><body>'
        '<date when="2024">2024</date>'
        '<date when="2024-02">Feb 2024</date>'
        '<date when="2024-02-29">29 Feb 2024</date>'
        '</body></text></TEI>',
    )
    body = root[0][0]
    result = xpath_select_nodes(
        body,
        'for $d in date return tp:date_popover($d)',
        xpath_extensions='tests.extensions_sample',
    )

    assert isinstance(result, list)
    assert len(result) == 3
    assert [el.tag for el in result] == ['span', 'span', 'span']
    assert result[0].get('title') == '2024'
    assert result[1].get('title') == 'February 2024'
    assert result[2].get('title') == '29 February 2024'


def test_expect_string_and_text_helpers() -> None:
    el = etree.fromstring('<x> a <b> b </b> </x>')
    assert expect_string(el) == ' a  b  '
    assert expect_text(el) == 'a  b'
    assert expect_string([42]) == '42'
    assert expect_text('  hi  ') == 'hi'

    with pytest.raises(ValueError, match='single XPath item'):
        expect_string([1, 2])
