"""Tests for whitespace preservation in Markdown code blocks."""

from __future__ import annotations

from lxml import etree

from teipublisher.runtime.markdown_output_functions import (
    MarkdownOutputFunctions,
    normalize_markdown_xml_text,
)
from teipublisher.runtime.output_functions import TemplateOutput
from teipublisher.runtime.pm_runtime import apply_children


def test_markdown_code_preserves_line_breaks() -> None:
    pmf = MarkdownOutputFunctions()
    config = {
        'normalize_text': normalize_markdown_xml_text,
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }

    class Node:
        def get(self, key):
            return None

    result = pmf.code(
        config,
        Node(),
        [],
        ['def foo():\n', '    return 1\n'],
        'python',
    )
    assert len(result) == 1
    assert isinstance(result[0], TemplateOutput)
    assert result[0] == '```python\ndef foo():\n    return 1\n\n```'


def test_markdown_code_preserves_xml_markup_literally() -> None:
    tei = 'http://www.tei-c.org/ns/1.0'
    listing = etree.Element(f'{{{tei}}}programlisting')
    tag = etree.SubElement(listing, f'{{{tei}}}tag')
    tag.text = 'elementSpec'

    pmf = MarkdownOutputFunctions()
    config: dict = {'dispatch': lambda *a, **k: ['SHOULD_NOT_APPEAR']}

    result = pmf.code(config, listing, [], listing, 'xml')
    body = str(result[0])
    assert 'SHOULD_NOT_APPEAR' not in body
    assert '<tag>elementSpec</tag>' in body
    assert '#tei_' not in body


def test_markdown_block_programlisting_preserves_whitespace() -> None:
    pmf = MarkdownOutputFunctions()
    config = {
        'normalize_text': normalize_markdown_xml_text,
        'apply_children': apply_children,
        'dispatch': lambda *a, **k: [],
    }

    class Node:
        def get(self, key):
            return None

    result = pmf.block(
        config,
        Node(),
        ['programlisting'],
        ['  indented\n', '  text\n'],
    )
    text = ''.join(str(x) for x in result)
    assert '  indented\n  text\n' in text
