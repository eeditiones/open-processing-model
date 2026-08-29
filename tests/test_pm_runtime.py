"""Tests for pm_runtime helpers."""

from __future__ import annotations

import pytest
from lxml import etree

from opm.runtime.output_functions import (
    TemplateOutput,
    apply_children_without_normalization,
    apply_pb_template,
    normalize,
)
from opm.runtime.markdown_output_functions import normalize_markdown_xml_text
from opm.runtime.pm_runtime import apply_children
from opm.runtime.pm_runtime import (
    apply_template_param_value,
    inject_cached_footnotes,
    resolve_context_element,
    serialize,
    xpath_select_nodes,
    xpath_test,
)

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def test_apply_pb_template_preserves_line_breaks() -> None:
    out = apply_pb_template(
        '#note[\n[[title]]\n\n[[content]]\n]',
        {'title': 'Note title', 'content': 'Body'},
    )
    text = ''.join(str(x) for x in out)
    assert isinstance(out[0], TemplateOutput)
    assert '#note[\nNote title\n\nBody\n]' == text


def test_apply_children_skips_normalization_for_template_output() -> None:
    buf: list = []
    config = {
        'normalize_text': normalize_markdown_xml_text,
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }
    apply_children(config, None, [TemplateOutput('line one\nline two')], buf)
    assert buf == ['line one\nline two']


def test_apply_children_without_normalization_preserves_newlines() -> None:
    buf: list = []
    config = {
        'normalize_text': normalize_markdown_xml_text,
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }
    apply_children_without_normalization(
        config,
        None,
        ['keep\n  indent\n'],
        buf,
    )
    assert buf == ['keep\n  indent\n']


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
    from opm.runtime.markdown_output_functions import apply_markdown_finish_regexes

    assert apply_markdown_finish_regexes('a\n\n\n\nb') == 'a\n\nb'
    assert apply_markdown_finish_regexes('_  word  _') == '_word_'
    assert apply_markdown_finish_regexes('**  bold  **') == '**bold**'


def test_normalize_markdown_xml_text_collapses_pretty_print() -> None:
    from opm.runtime.markdown_output_functions import normalize_markdown_xml_text

    assert normalize_markdown_xml_text('hello\n              world') == 'hello world'
    assert normalize_markdown_xml_text('\n        ') == ''
    assert normalize_markdown_xml_text('a  \n  b') == 'a b'
    assert normalize_markdown_xml_text(' ') == ' '


def test_markdown_output_finish_serializes_then_cleans() -> None:
    from opm.runtime.markdown_output_functions import MarkdownOutputFunctions

    pmf = MarkdownOutputFunctions()
    out = pmf.finish({}, ['x', '**  y  **', 'z'])
    assert out == ['x**y**z']


def test_tag_and_ns_on_comment_do_not_use_qname_on_factory_tag() -> None:
    """Comments use a non-string ``.tag``; :func:`tag` / :func:`ns` must not call ``QName``."""
    from lxml import etree

    from opm.runtime.pm_runtime import ns, tag

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


def test_parameters_root_is_the_viewed_node_not_the_copy() -> None:
    """``$parameters?root`` can be the original node while ``.`` is a fill-copy."""
    from opm.runtime.pm_runtime import xpath_runtime_context

    dbk = 'http://docbook.org/ns/docbook'
    article = etree.fromstring(
        f'''<article xmlns="{dbk}">
  <info><title>Guide</title></info>
  <section xml:id="install"><title>Install</title>
    <section xml:id="pip"><title>pip</title></section>
  </section>
</article>'''.encode(),
    )
    install = article.xpath('//*[@xml:id="install"]')[0]
    intro = etree.Element(install.tag, attrib=dict(install.attrib), nsmap=install.nsmap)
    params = xpath_runtime_context(root=install)

    assert xpath_select_nodes(
        intro,
        'string(($parameters?root)/ancestor::article/info/title)',
        params,
    ) == 'Guide'
    assert xpath_select_nodes(
        intro,
        '$parameters?root is .',
        params,
    ) is False


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


def test_document_uri_reports_the_source_file(tmp_path) -> None:
    """``document-uri()``/``base-uri()`` resolve to the input document.

    The parser's static base URI only resolves relative doc()/collection()
    arguments; the URI has to be attached to the node tree as well, or
    teipublisher.odd's facsimile and static-link models get an empty sequence.
    """
    from opm.runtime.pm_runtime import xpath_runtime_context

    xml = tmp_path / 'play.xml'
    xml.write_text(
        f'<TEI xmlns="{TEI_NS}"><text><body><p>x</p></body></text></TEI>',
        encoding='utf-8',
    )
    root = etree.parse(str(xml)).getroot()
    uri = xml.resolve().as_uri()
    params = xpath_runtime_context(base_uri=uri, root=root)

    assert xpath_select_nodes(root, 'string(document-uri(root(.)))', params) == uri
    assert xpath_select_nodes(root, 'string(base-uri(root(.)))', params) == uri
    assert xpath_select_nodes(
        root, 'string(document-uri(root($parameters?root)))', params,
    ) == uri


def test_root_of_parameters_root_reaches_the_source_document(tmp_path) -> None:
    """From a synthetic chunk copy, ``root($parameters?root)`` is the whole document.

    Chunking transforms a rebuilt copy of the page, so the context node and
    ``$parameters?root`` live in different lxml trees. ``XPathContext.get_root()``
    searches only the context tree and its registered documents, so unless the
    source document is registered this yields the empty sequence — and every ODD
    model that walks up to the teiHeader degrades silently on chunk output.
    """
    from opm.runtime.pm_runtime import xpath_runtime_context

    xml = tmp_path / 'play.xml'
    header = '<teiHeader><fileDesc><titleStmt><title>Much Adoe</title></titleStmt></fileDesc></teiHeader>'
    body = '<text><body><div><pb n="101"/><p>one</p><pb n="102"/><p>two</p></div></body></text>'
    xml.write_text(
        f'<TEI xmlns="{TEI_NS}">{header}{body}</TEI>', encoding='utf-8',
    )
    doc_root = etree.parse(str(xml)).getroot()
    uri = xml.resolve().as_uri()
    source_div = doc_root.find(f'.//{{{TEI_NS}}}div')

    # Stand in for a chunk: a separate tree holding a copy of the page.
    chunk = etree.fromstring(etree.tostring(source_div))
    assert chunk.getroottree().getroot() is not doc_root

    params = xpath_runtime_context(base_uri=uri, root=source_div)
    pb = chunk.find(f'{{{TEI_NS}}}pb')

    assert xpath_select_nodes(
        pb, 'string(root($parameters?root)//teiHeader//title)', params,
    ) == 'Much Adoe'
    assert xpath_select_nodes(
        pb, 'count(root($parameters?root)//pb)', params,
    ) == 2
    assert xpath_select_nodes(
        pb, 'string(document-uri(root($parameters?root)))', params,
    ) == uri


def test_source_node_resolves_a_chunk_copy_to_the_stored_document() -> None:
    """``tp:source-node()`` steps out of a detached chunk into the document.

    ``$get()`` compiles to this. Without it ``preceding::pb`` is confined to the
    rebuilt page, so teipublisher.odd's ``count($get(.)/preceding::pb) + 1``
    reports page 1 for every folio.
    """
    from opm.config import ChunkingConfig
    from opm.navigation import tei_pb_chunks
    from opm.runtime import source_map
    from opm.runtime.pm_runtime import xpath_runtime_context

    pages = ''.join(f'<pb n="{n}"/><p>page {n}</p>' for n in (101, 102, 103))
    doc = etree.fromstring(
        f'<TEI xmlns="{TEI_NS}"><text><body><div>{pages}</div></body></text></TEI>'.encode(),
    )
    source_map.clear()
    try:
        chunks = tei_pb_chunks(doc, ChunkingConfig())
        assert len(chunks) == 3

        third = chunks[2]
        # The chunk really is a separate tree, not a live view of the document.
        assert third.getroottree().getroot() is not doc

        pb = third.iter(f'{{{TEI_NS}}}pb').__next__()
        params = xpath_runtime_context(root=doc)

        assert xpath_select_nodes(
            pb, 'count(tp:source-node(.)/preceding::pb) + 1', params,
        ) == 3
        assert xpath_select_nodes(
            pb, 'string(tp:source-node(.)/@n)', params,
        ) == '103'
        # Unmapped nodes pass through unchanged, so the identity case still works.
        assert xpath_select_nodes(
            doc, 'count(tp:source-node(.)//pb)', params,
        ) == 3
    finally:
        source_map.clear()


def test_source_node_is_identity_without_a_recorded_copy() -> None:
    """Outside chunking nothing is recorded, so ``$get(x)`` is just ``x``."""
    from opm.runtime import source_map

    source_map.clear()
    doc = etree.fromstring(
        f'<TEI xmlns="{TEI_NS}"><text><body><div><pb n="1"/><pb n="2"/></div></body></text></TEI>'.encode(),
    )
    second = list(doc.iter(f'{{{TEI_NS}}}pb'))[1]
    assert xpath_select_nodes(second, 'count(tp:source-node(.)/preceding::pb)') == 1


def test_get_compiles_to_source_node() -> None:
    """The ODD's ``$get(x)`` reaches the runtime as ``tp:source-node(x)``."""
    from opm.odd_compiler.codegen.python_generator import PythonGenerator

    expr = PythonGenerator._param_to_expr(
        PythonGenerator.__new__(PythonGenerator), 'count($get(.)/preceding::pb) + 1',
    )
    assert 'tp:source-node(.)' in expr
    assert '$get' not in expr


def test_apply_children_closes_up_a_word_split_at_a_soft_hyphen() -> None:
    """``daugh<shy><lb/>ter`` is one word, not two: drop the source indentation."""
    el = etree.Element('p')
    config = {
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }
    apply_children(config, None, ['your daugh­\n            ter,'], el)
    assert el.text == 'your daugh­ter,'


def test_apply_children_closes_up_across_an_omitted_element() -> None:
    """The two halves reach the output as separate runs when the ``lb`` is omitted."""
    el = etree.Element('p')
    config = {
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }
    apply_children(config, None, ['to your daugh­'], el)
    apply_children(config, None, ['\n            (ter,'], el)
    assert el.text == 'to your daugh­(ter,'
