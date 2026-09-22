"""Tests for XPath ``tp:`` extension functions from Python modules."""

from __future__ import annotations

from email.message import Message
from unittest.mock import patch

from lxml import etree
import pytest

from opm.config import load_project_config
from opm.runtime.common_xpath_functions import request
from opm.runtime.xpath_env import XPathEnvironment
from opm.runtime.xpath_extensions import expect_string, expect_text
from opm.transform import load_xpath_documents, transform_file

SAMPLE = 'tests.extensions_sample'
COMMON = 'opm.runtime.common_xpath_functions'


def test_tp_function_in_xpath_select() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(f'<div xmlns="{TEI}"><p>a</p></div>')
    p = root[0]
    r = XPathEnvironment(extensions=SAMPLE).select(p, 'tp:greet("world")')
    assert r == 'Hello world'


def test_tp_function_boolean_predicate() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(f'<div xmlns="{TEI}"><p/></div>')
    p = root[0]
    ok = XPathEnvironment(extensions=SAMPLE).test(p, 'starts-with(tp:greet(.), "Hello")')
    assert ok is True


def test_resolve_element_with_tp_in_xpath() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><body><p>ok</p></body></text></TEI>',
    )
    el = XPathEnvironment(extensions=SAMPLE).resolve_element(
        root, '//body/p[tp:greet(string(.)) = "Hello ok"]',
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
    result = XPathEnvironment(extensions=SAMPLE).select(
        body, 'for $d in date return tp:date_popover($d)',
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


def test_transform_documents_config_is_relative_to_config_file(tmp_path) -> None:
    (tmp_path / 'data').mkdir()
    config_path = tmp_path / 'opm.toml'
    config_path.write_text(
        '[transform]\n'
        'documents = ["data/lookup.xml"]\n',
        encoding='utf-8',
    )

    cfg = load_project_config(config_path)

    assert cfg.xpath_documents == (tmp_path / 'data' / 'lookup.xml',)


def test_doc_function_uses_configured_documents_and_input_base_uri(tmp_path) -> None:
    main_path = tmp_path / 'main.xml'
    lookup_path = tmp_path / 'lookup.xml'
    main_path.write_text('<root/>', encoding='utf-8')
    lookup_path.write_text('<lookup><label>found</label></lookup>', encoding='utf-8')

    root = etree.parse(str(main_path)).getroot()
    env = XPathEnvironment(
        base_uri=main_path.resolve().as_uri(),
        documents=load_xpath_documents([lookup_path]),
    )

    assert env.select(root, 'doc("lookup.xml")/lookup/label/string()') == 'found'
    assert env.select(root, 'doc-available("lookup.xml")') is True


def test_transform_file_passes_configured_documents_to_doc_function(tmp_path) -> None:
    main_path = tmp_path / 'main.xml'
    lookup_path = tmp_path / 'lookup.xml'
    module_path = tmp_path / 'doc_transform.py'
    config_path = tmp_path / 'opm.toml'
    main_path.write_text('<root/>', encoding='utf-8')
    lookup_path.write_text('<lookup><label>from doc</label></lookup>', encoding='utf-8')
    module_path.write_text(
        """OUTPUT_MODE = 'markdown'


def serialize(result):
    return ''.join(str(item) for item in result)


def transform(root, options=None, *, xpath_env=None):
    return [xpath_env.select(root, 'doc("lookup.xml")/lookup/label/string()')]
""",
        encoding='utf-8',
    )
    config_path.write_text(
        '[transform]\n'
        'documents = ["lookup.xml"]\n',
        encoding='utf-8',
    )

    assert transform_file(
        module_path,
        main_path,
        config=load_project_config(config_path),
    ) == 'from doc'


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
    result = XPathEnvironment(extensions=COMMON).select(
        body, 'for $d in div/div return tp:heading_number($d)',
    )
    assert result == ['1.1', '1.2', '2.1']


def test_tp_serialize_egxml_strips_odd_indent() -> None:
    EX = 'http://www.tei-c.org/ns/Examples'
    eg = etree.fromstring(
        f'<egXML xmlns="{EX}">\n'
        '        <pb n="474"/>\n'
        '        <p>alone\n'
        '          present.</p>\n'
        '      </egXML>'
    )
    body = XPathEnvironment(extensions=COMMON).select(eg, 'tp:serialize_egxml(.)')
    assert isinstance(body, str)
    assert body.startswith('<pb')
    assert '\n        <p' not in body
    assert 'alone\npresent.' in body


def test_tp_normalize_egxml_dedents_plain_text() -> None:
    TEI = 'http://www.tei-c.org/ns/1.0'
    eg = etree.fromstring(
        f'<eg xmlns="{TEI}">\n'
        '            CHAPTER 38\n'
        '            READER, I married him.\n'
        '        </eg>'
    )
    body = XPathEnvironment(extensions=COMMON).select(eg, 'tp:normalize_egxml(.)')
    assert body == 'CHAPTER 38\nREADER, I married him.'


def test_tp_highlight_returns_markup_node() -> None:
    el = etree.fromstring('<programlisting language="xml">&lt;pb n="1"/&gt;</programlisting>')
    result = XPathEnvironment(extensions=COMMON).select(
        el, "tp:highlight(string(.), (@language, 'xml')[1])",
    )
    assert isinstance(result, etree._Element)
    assert result.get('class') == 'highlight'
    html = etree.tostring(result, encoding='unicode')
    assert 'class="nt"' in html
    assert 'pb' in html


def test_tp_highlight_unknown_language_returns_source() -> None:
    el = etree.fromstring('<x>select 1</x>')
    result = XPathEnvironment(extensions=COMMON).select(
        el, "tp:highlight(string(.), 'not-a-lexer')",
    )
    assert result == 'select 1'


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
    env = XPathEnvironment(extensions=COMMON)

    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/xml'),
    ):
        assert env.select(
            root, 'tp:request("https://example.com/api")/item/name/text()',
        ) == 'alpha'
        assert env.select(root, 'tp:request("https://example.com/api")/item/@id') == '42'


def test_tp_request_path_steps_with_tei_default_namespace() -> None:
    """Unprefixed child steps use the TEI default namespace; use local-name() for foreign XML."""
    TEI = 'http://www.tei-c.org/ns/1.0'
    body = b'<api><item id="42"><name>alpha</name></item></api>'
    root = etree.fromstring(f'<p xmlns="{TEI}"/>')

    with patch(
        'opm.runtime.common_xpath_functions.urllib.request.urlopen',
        return_value=_MockHttpResponse(body, 'application/xml'),
    ):
        assert XPathEnvironment(extensions=COMMON).select(
            root,
            'tp:request("https://example.com/api")/*[local-name()="item"]/*[local-name()="name"]/text()',
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
