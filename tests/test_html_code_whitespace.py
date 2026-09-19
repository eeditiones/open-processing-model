"""HTML / print whitespace preservation for code listings."""

from __future__ import annotations

from lxml import etree

from opm.runtime.context import RenderContext
from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.pm_runtime import apply_children, serialize
from opm.runtime.print_output_functions import PrintOutputFunctions


def _config(*, webcomponents: bool = False) -> RenderContext:
    return RenderContext(
        apply=lambda _c, nodes: list(nodes) if isinstance(nodes, list) else [nodes],
        webcomponents=webcomponents,
    )


def test_html_code_emits_pre_code() -> None:
    pmf = HtmlOutputFunctions()
    node = etree.Element('programlisting')
    body = 'line1\n    indented\nline3'
    res = pmf.code(_config(), node, ['programlisting'], body, language='xml')
    assert len(res) == 1
    assert res[0].tag == 'pre'
    code = res[0].find('code')
    assert code is not None
    assert code.get('data-language') == 'xml'
    assert 'language-' not in (code.get('class') or '')
    assert 'line1\n    indented\nline3' in serialize(res)


def test_webcomponent_code_highlight_degrades_without_webcomponents() -> None:
    pmf = HtmlOutputFunctions()
    node = etree.Element('programlisting')
    body = '<a>\n  <b/>\n</a>'
    res = pmf.webcomponent(
        _config(webcomponents=False),
        node,
        ['tei-programlisting'],
        body,
        name='pb-code-highlight',
        optional={'language': 'xml'},
    )
    html = serialize(res)
    assert res[0].tag == 'pre'
    assert '<pb-code-highlight' not in html
    assert '&lt;b/&gt;' in html
    assert '\n  ' in html


def test_webcomponent_code_highlight_kept_when_webcomponents_on() -> None:
    pmf = HtmlOutputFunctions()
    node = etree.Element('programlisting')
    res = pmf.webcomponent(
        _config(webcomponents=True),
        node,
        ['c'],
        'x',
        name='pb-code-highlight',
        optional={'language': 'xml'},
    )
    assert res[0].tag == 'pb-code-highlight'


def test_print_inherits_code_degrade() -> None:
    pmf = PrintOutputFunctions()
    node = etree.Element('programlisting')
    res = pmf.webcomponent(
        _config(webcomponents=False),
        node,
        ['c'],
        'a\n  b\n',
        name='pb-code-highlight',
        optional={'language': 'json'},
    )
    html = serialize(res)
    assert res[0].tag == 'pre'
    assert '\n  ' in html
    assert 'b' in html


def test_html_code_inserts_tp_highlight_nodes() -> None:
    from opm.xml_highlight import highlight_markup

    pmf = HtmlOutputFunctions()
    node = etree.Element('programlisting')
    wrap = highlight_markup('<div n="1"/>', 'xml')
    res = pmf.code(_config(), node, ['programlisting'], wrap, language='xml')
    html = serialize(res)
    assert '<span class="highlight">' in html
    assert 'class="nt"' in html
    assert 'language-' not in html
    assert 'pb-code-highlight' not in html


def test_html_code_omits_language_attrs_when_webcomponents_on() -> None:
    """Prism in pb-components re-highlights ``data-language`` / ``language-*``."""
    from opm.xml_highlight import highlight_markup

    pmf = HtmlOutputFunctions()
    node = etree.Element('programlisting')
    wrap = highlight_markup('display: block;', 'css')
    res = pmf.code(
        _config(webcomponents=True),
        node,
        ['programlisting'],
        wrap,
        language='css',
    )
    code = res[0].find('code')
    assert code is not None
    assert code.get('data-language') is None
    assert 'language-' not in (code.get('class') or '')
    html = serialize(res)
    assert 'display' in html
    assert 'class="highlight"' in html
