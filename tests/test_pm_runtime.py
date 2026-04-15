"""Tests for pm_runtime helpers."""

from __future__ import annotations

import pytest
from lxml import etree

from tei_publisher_py.pm_runtime import (
    inject_cached_footnotes,
    resolve_context_element,
    serialize,
    xpath_select_nodes,
    xpath_test,
)

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def test_inject_cached_footnotes_appends_to_body_end() -> None:
    html = etree.Element('html')
    body = etree.SubElement(html, 'body')
    p = etree.SubElement(body, 'p')
    p.text = 'Text'
    dl = etree.Element('dl')
    dl.set('class', 'footnote')
    dl.set('id', 'fn_x')
    config = {'footnotes': [dl]}

    out = inject_cached_footnotes([html], config)
    assert out[0] is html
    assert p.find('dl') is None
    assert body[-1] is dl
    assert dl.getparent() is body
    assert config['footnotes'] == []


def test_inject_cached_footnotes_preserves_order() -> None:
    html = etree.Element('html')
    body = etree.SubElement(html, 'body')
    etree.SubElement(body, 'section')
    dl1 = etree.Element('dl')
    dl1.set('class', 'footnote')
    dl1.set('id', 'fn_1')
    dl2 = etree.Element('dl')
    dl2.set('class', 'footnote')
    dl2.set('id', 'fn_2')
    config = {'footnotes': [dl1, dl2]}

    inject_cached_footnotes([html], config)
    assert [c.get('id') for c in body] == [None, 'fn_1', 'fn_2']


def test_inject_cached_footnotes_noop_when_empty() -> None:
    html = etree.Element('html')
    body = etree.SubElement(html, 'body')
    inject_cached_footnotes([html], {'footnotes': []})
    assert len(body) == 0


def test_xpath_select_nodes_unwraps_singleton_count() -> None:
    """``count(...)`` is one atomic; :func:`xpath_content` must see an ``int``, not ``[int]``."""
    xml = f'''<TEI xmlns="{TEI_NS}"><text><body><div><div><head>t</head></div></div></body></text></TEI>'''
    root = etree.fromstring(xml.encode())
    head = root.find(f'.//{{{TEI_NS}}}head')
    assert head is not None
    n = xpath_select_nodes(head, 'count(ancestor::div)', {})
    assert n == 2
    assert isinstance(n, int)


def test_resolve_context_element_selects_single_node() -> None:
    xml = f'''<TEI xmlns="{TEI_NS}"><text><body><p>x</p><p>y</p></body></text></TEI>'''
    root = etree.fromstring(xml.encode())
    body = root.find(f'.//{{{TEI_NS}}}body')
    assert body is not None
    assert resolve_context_element(root, '//body', None) is body


def test_resolve_context_element_requires_unique_element() -> None:
    xml = f'''<TEI xmlns="{TEI_NS}"><text><body><p>a</p><p>b</p></body></text></TEI>'''
    root = etree.fromstring(xml.encode())
    with pytest.raises(ValueError, match='exactly one'):
        resolve_context_element(root, '//p', None)


def test_xpath_test_parent_axis_matches_namespaced_tei_elements() -> None:
    """Unprefixed steps like ``parent::div`` must resolve to the TEI namespace (not no namespace)."""
    xml = f'''<TEI xmlns="{TEI_NS}"><text><body><div><head>t</head></div></body></text></TEI>'''
    root = etree.fromstring(xml.encode())
    head = root.find(f'.//{{{TEI_NS}}}head')
    assert head is not None
    assert xpath_test(head, 'parent::div', {}) is True
    assert xpath_test(head, 'parent::figure', {}) is False


def test_serialize_after_inject() -> None:
    html = etree.Element('html')
    body = etree.SubElement(html, 'body')
    p = etree.SubElement(body, 'p')
    p.text = 'x'
    dl = etree.Element('dl')
    dl.set('class', 'footnote')
    inject_cached_footnotes([html], {'footnotes': [dl]})
    s = serialize([html])
    assert 'footnote' in s
    assert s.index('<p') < s.index('dl')
