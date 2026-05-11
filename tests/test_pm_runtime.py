"""Tests for pm_runtime helpers."""

from __future__ import annotations

import pytest
from lxml import etree

from teipublisher.runtime.output_functions import normalize
from teipublisher.runtime.pm_runtime import (
    apply_template_param_value,
    inject_cached_footnotes,
    resolve_context_element,
    serialize,
    xpath_select_nodes,
    xpath_test,
)

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def test_apply_template_param_value_expands_context_element_to_children() -> None:
    """When XPath (or ``.``) yields the node being processed, recurse on children."""
    xml = (
        f'<TEI xmlns="{TEI_NS}"><seg xml:id="s1">a<hi>b</hi></seg></TEI>'.encode()
    )
    root = etree.fromstring(xml)
    seg = root[0]

    def dispatch(config, node, params):
        if etree.QName(node).localname == 'hi':
            em = etree.Element('em')
            em.text = ''.join(node.itertext()) or 'b'
            return [em]
        return [etree.Element('span')]

    config = {'dispatch': dispatch, 'parameters': {}}

    out = apply_template_param_value(config, seg, seg)
    assert out[0] == 'a'
    assert etree.QName(out[1]).localname == 'em'

    hi = seg.find(f'{{{TEI_NS}}}hi')
    assert hi is not None
    out2 = apply_template_param_value(config, seg, hi)
    assert len(out2) == 1
    assert etree.QName(out2[0]).localname == 'em'


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


def test_apply_markdown_finish_regexes_matches_pmf_finish() -> None:
    from teipublisher.runtime.markdown_output_functions import apply_markdown_finish_regexes

    assert apply_markdown_finish_regexes('a\n\n\n\nb') == 'a\n\nb'
    assert apply_markdown_finish_regexes('_  word  _') == '_word_'
    assert apply_markdown_finish_regexes('**  bold  **') == '**bold**'


def test_normalize_markdown_xml_text_collapses_pretty_print() -> None:
    from teipublisher.runtime.markdown_output_functions import normalize_markdown_xml_text

    assert normalize_markdown_xml_text('hello\n              world') == 'hello world'
    assert normalize_markdown_xml_text('\n        ') == ''
    assert normalize_markdown_xml_text('a  \n  b') == 'a b'
    assert normalize_markdown_xml_text(' ') == ' '


def test_markdown_output_finish_serializes_then_cleans() -> None:
    from teipublisher.runtime.markdown_output_functions import MarkdownOutputFunctions

    pmf = MarkdownOutputFunctions()
    out = pmf.finish({}, ['x', '**  y  **', 'z'])
    assert out == ['x**y**z']


def test_tag_and_ns_on_comment_do_not_use_qname_on_factory_tag() -> None:
    """Comments use a non-string ``.tag``; :func:`tag` / :func:`ns` must not call ``QName``."""
    from lxml import etree

    from teipublisher.runtime.pm_runtime import ns, tag

    c = etree.Comment('note')
    assert tag(c) == 'comment'
    assert ns(c) == ''


def test_normalize_stringifies_xpath_numeric_atoms() -> None:
    """``xpath_content`` can be a bare ``int``/``float``; :func:`normalize` must not ``list()`` them."""
    assert normalize(3.5) == ['3.5']
    assert normalize(0) == ['0']
    assert normalize(0.0) == ['0.0']


def test_xpath_select_nodes_unwraps_singleton_count() -> None:
    """``count(...)`` is one atomic; :func:`xpath_content` must see an ``int``, not ``[int]``."""
    xml = f'''<TEI xmlns="{TEI_NS}"><text><body><div><div><head>t</head></div></div></body></text></TEI>'''
    root = etree.fromstring(xml.encode())
    head = root.find(f'.//{{{TEI_NS}}}head')
    assert head is not None
    n = xpath_select_nodes(head, 'count(ancestor::div)', {})
    assert n == 2
    assert isinstance(n, int)


def test_xpath_select_nodes_returns_lxml_elements_not_wrappers() -> None:
    """Element steps must yield lxml nodes so :func:`apply_children` can dispatch (e.g. ``alternate``)."""
    xml = (
        f'<TEI xmlns="{TEI_NS}"><text><body><p>'
        f'<choice><abbr>XML</abbr><expan>Extensible</expan></choice>'
        f'</p></body></text></TEI>'
    )
    root = etree.fromstring(xml.encode())
    choice = root.find(f'.//{{{TEI_NS}}}choice')
    assert choice is not None
    expan = xpath_select_nodes(choice, 'expan[1]', {})
    abbr = xpath_select_nodes(choice, 'abbr[1]', {})
    assert isinstance(expan, etree._Element)
    assert isinstance(abbr, etree._Element)
    assert etree.QName(expan).localname == 'expan'
    assert expan.text == 'Extensible'
    assert abbr.text == 'XML'


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
