"""HTML / print whitespace preservation for code listings."""

from __future__ import annotations

from lxml import etree

from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.pm_runtime import apply_children, serialize
from opm.runtime.print_output_functions import PrintOutputFunctions


def _config(*, webcomponents: bool = False) -> dict:
    return {
        'apply_children': apply_children,
        'apply': lambda _c, nodes: list(nodes) if isinstance(nodes, list) else [nodes],
        'footnotes': [],
        'webcomponents': webcomponents,
    }


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
    assert res[0].tag == 'pre'
    assert 'pb-code-highlight' not in serialize(res)
    assert '  <b/>' in serialize(res) or '  &lt;b/&gt;' in serialize(res)


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
    assert res[0].tag == 'pre'
    assert '\n  b\n' in serialize(res)
