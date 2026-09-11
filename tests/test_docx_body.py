"""Top-level content of the assembled ``word/document.xml``."""

from __future__ import annotations

import zipfile
from io import BytesIO

from lxml import etree

from opm.runtime.context import RenderContext
from opm.runtime.docx_output_functions import W, DocxOutputFunctions


def test_page_break_at_top_level_is_wrapped_in_a_paragraph() -> None:
    """Word refuses to open a file whose ``w:body`` holds a ``w:r`` directly.

    ``behaviour="break"`` returns a bare run, so a page break before a heading
    on ``text`` (as in the serafin ODD) used to land straight in the body.
    """
    pmf = DocxOutputFunctions()
    config = RenderContext()
    heading = pmf._wrap_in_para(['Source'], 'Heading1')
    [page_break] = pmf.break_(config, None, [], None, type='page')

    [data] = pmf.finish(config, [page_break, heading])

    root = etree.fromstring(zipfile.ZipFile(BytesIO(data)).read('word/document.xml'))
    body = root.find(f'{{{W}}}body')
    assert [etree.QName(c).localname for c in body] == ['p', 'p', 'sectPr']
    assert body[0].find(f'{{{W}}}r/{{{W}}}br').get(f'{{{W}}}type') == 'page'
