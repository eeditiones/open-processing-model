"""Tests for XPath ``tp:`` extension functions from Python modules."""

from __future__ import annotations

from email.message import Message
from unittest.mock import patch

from lxml import etree
import pytest

from opm.runtime.common_xpath_functions import request
from opm.runtime.pm_runtime import resolve_context_element, xpath_select_nodes, xpath_test
from opm.runtime.xpath_extensions import expect_string, expect_text


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


def test_heading_number_matches_ext_common_heading_number() -> None:
    """``tp:heading_number`` matches ``pmf:heading-number`` from ``ext-common.xql``."""
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><body>'
        '<div xml:id="d1"><div xml:id="d1a"/><div xml:id="d1b"/></div>'
        '<div xml:id="d2"><div xml:id="d2a"/></div>'
        '</body></text></TEI>',
    )
    body = root[0][0]
    result = xpath_select_nodes(
        body,
        'for $d in div/div return tp:heading_number($d)',
        xpath_extensions='opm.runtime.common_xpath_functions',
    )
    assert result == ['1.1', '1.2', '2.1']


class _MockHttpResponse:
    def __init__(self, body: bytes, content_type: str, *, charset: str = 'utf-8') -> None:
        self._body = body
        headers = Message()
        headers['Content-Type'] = f'{content_type}; charset={charset}'
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_tp_request_empty_xml_body_returns_empty_string() -> None:
    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(b'', 'application/xml'),
    ):
        assert request('https://example.com/api') == ''


def test_tp_request_returns_string_for_non_xml() -> None:
    body = b'{"ok": true}'
    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/json'),
    ):
        assert request('https://example.com/api') == '{"ok": true}'


def test_tp_request_parses_xml_and_supports_path_steps() -> None:
    body = b'<api><item id="42"><name>alpha</name></item></api>'
    root = etree.fromstring('<p/>')

    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/xml'),
    ):
        assert xpath_select_nodes(
            root,
            'tp:request("https://example.com/api")/item/name/text()',
            xpath_extensions='opm.runtime.common_xpath_functions',
        ) == 'alpha'

        assert xpath_select_nodes(
            root,
            'tp:request("https://example.com/api")/item/@id',
            xpath_extensions='opm.runtime.common_xpath_functions',
        ) == '42'


def test_tp_request_path_steps_with_tei_default_namespace() -> None:
    """Unprefixed child steps use the TEI default namespace; use local-name() for foreign XML."""
    TEI = 'http://www.tei-c.org/ns/1.0'
    body = b'<api><item id="42"><name>alpha</name></item></api>'
    root = etree.fromstring(f'<p xmlns="{TEI}"/>')

    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/xml'),
    ):
        assert xpath_select_nodes(
            root,
            'tp:request("https://example.com/api")/*[local-name()="item"]/*[local-name()="name"]/text()',
            xpath_extensions='opm.runtime.common_xpath_functions',
        ) == 'alpha'


def test_tp_request_accepts_xml_suffix_content_types() -> None:
    body = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>News</title></feed>'
    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/atom+xml'),
    ):
        wrapped = request('https://example.com/feed')
    assert wrapped is not None
    assert wrapped.value.tag == '{http://www.w3.org/2005/Atom}feed'  # type: ignore[union-attr]
