"""Markdown output for lists and HTML from pass-through templates.

Markdown is whitespace-sensitive: an item whose text is pushed four columns past
the marker reads as an indented code block, and so does pretty-printed ``<dl>``
markup from a pass-through template.  Mirrors the fixes in tei-publisher-lib's
``markdown-functions.xql`` (``pmf:paragraph``, ``pmf:serialize-html``,
``pmf:finish``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_odd
from opm.runtime.markdown_output_functions import (
    _serialize_html,
    apply_markdown_finish_regexes,
)

ROOT = Path(__file__).resolve().parents[1]
ODD = packaged_odd('docbook')
TEST_XML = ROOT / 'tests' / 'test-markdown-docbook.xml'


@pytest.fixture(scope='module')
def markdown(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Compile docbook.odd for markdown and transform the fixture."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    tmp = tmp_path_factory.mktemp('markdown_docbook')
    path = tmp / 'docbook_markdown.py'
    path.write_text(compile_odd(str(ODD), output_mode='markdown'), encoding='utf-8')
    mod = load_transform_module(path)

    root = etree.parse(str(TEST_XML)).getroot()
    result = run_transform(mod, root)
    assert isinstance(result, str)
    return result


def test_list_item_text_follows_the_marker(markdown: str) -> None:
    assert '\n1. first item\n' in markdown
    assert '\n2. second item\n' in markdown


def test_further_paragraphs_are_indented(markdown: str) -> None:
    assert '\n2. second item\n\n    still the second item\n' in markdown


def test_definition_list_is_passed_on_as_html(markdown: str) -> None:
    assert '<dl><dt>Alpha</dt><dd>\n\nthe first letter\n\n</dd>' in markdown


def test_nested_definition_list(markdown: str) -> None:
    assert '<dl><dt>Gamma</dt><dd>\n\nthe third letter\n\n</dd></dl>' in markdown


def test_no_html_line_is_indented(markdown: str) -> None:
    assert not re.search(r'^[ \t]+<', markdown, flags=re.MULTILINE)


def test_blank_line_between_html_block_and_heading() -> None:
    assert apply_markdown_finish_regexes('</dl>\n## Next') == '</dl>\n\n## Next'


def test_serialize_html_keeps_attributes() -> None:
    assert _serialize_html(etree.fromstring('<a id="sec-1"/>')) == '<a id="sec-1"></a>'


def test_serialize_html_pads_definition() -> None:
    el = etree.fromstring('<dl><dt>path</dt><dd>the relative path</dd></dl>')
    assert _serialize_html(el) == '<dl><dt>path</dt><dd>\n\nthe relative path\n</dd></dl>'
