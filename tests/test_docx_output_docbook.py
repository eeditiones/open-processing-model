"""Integration test: compile packaged docbook.odd (docx mode), transform tests/test-docx-docbook.xml,
verify list numbering and hyperlink styling.
"""

from __future__ import annotations

import importlib.util
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_default_docx, packaged_odd

ROOT = Path(__file__).resolve().parents[1]
ODD = packaged_odd('docbook')
TEST_XML = ROOT / 'tests' / 'test-docx-docbook.xml'

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _parse_docx(data: bytes) -> dict[str, etree._Element]:
    parts: dict[str, etree._Element] = {}
    with zipfile.ZipFile(BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith('.xml') or name.endswith('.rels'):
                parts[name] = etree.fromstring(z.read(name))
    return parts


def _list_paras(doc_root: etree._Element) -> list[dict]:
    results = []
    for p in doc_root.iter(f'{{{W}}}p'):
        pPr = p.find(f'{{{W}}}pPr')
        if pPr is None:
            continue
        numPr = pPr.find(f'{{{W}}}numPr')
        if numPr is None:
            continue
        ilvl_el = numPr.find(f'{{{W}}}ilvl')
        numId_el = numPr.find(f'{{{W}}}numId')
        ilvl = int(ilvl_el.get(f'{{{W}}}val', '0')) if ilvl_el is not None else 0
        numid = int(numId_el.get(f'{{{W}}}val', '0')) if numId_el is not None else 0
        text = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))
        results.append({'ilvl': ilvl, 'numid': numid, 'text': text})
    return results


@pytest.fixture(scope='module')
def docx_parts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, etree._Element]:
    """Compile docbook.odd for docx, transform test-docx-docbook.xml, return parsed parts."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    tmp = tmp_path_factory.mktemp('docx_docbook')
    path = tmp / 'docbook_docx.py'
    path.write_text(compile_odd(str(ODD), output_mode='docx'), encoding='utf-8')
    mod = load_transform_module(path)

    root = etree.parse(str(TEST_XML)).getroot()
    result = run_transform(mod, root, docx_template=packaged_default_docx())
    assert isinstance(result, bytes), 'transform must return bytes for docx mode'
    return _parse_docx(result)


def test_docx_docbook_list_items_have_numpr(docx_parts):
    """Every list item must carry w:numPr."""
    paras = _list_paras(docx_parts['word/document.xml'])
    texts = [p['text'] for p in paras]
    for expected in ('AAA', 'BBB', 'One', 'Two', 'Three'):
        assert any(expected in t for t in texts), f'list item "{expected}" has no w:numPr'


def test_docx_docbook_outer_items_at_ilvl_0(docx_parts):
    paras = _list_paras(docx_parts['word/document.xml'])
    for label in ('AAA', 'BBB'):
        matches = [p for p in paras if label in p['text']]
        assert matches, f'paragraph "{label}" not found'
        assert matches[0]['ilvl'] == 0, f'"{label}" should be at ilvl=0, got {matches[0]["ilvl"]}'


def test_docx_docbook_inner_items_at_ilvl_1(docx_parts):
    paras = _list_paras(docx_parts['word/document.xml'])
    for label in ('One', 'Two', 'Three'):
        matches = [p for p in paras if label in p['text']]
        assert matches, f'paragraph "{label}" not found'
        assert matches[0]['ilvl'] == 1, f'"{label}" should be at ilvl=1, got {matches[0]["ilvl"]}'


def test_docx_docbook_inner_list_uses_different_numid(docx_parts):
    paras = _list_paras(docx_parts['word/document.xml'])
    outer_numid = next(p['numid'] for p in paras if 'AAA' in p['text'])
    inner_numid = next(p['numid'] for p in paras if 'One' in p['text'])
    assert inner_numid != outer_numid, 'inner ordered list must use a different numId'


def test_docx_docbook_hyperlink_style_in_styles_xml(docx_parts):
    """Hyperlink character style must be present (injected if absent from template)."""
    styles_root = docx_parts['word/styles.xml']
    hl_styles = [
        el for el in styles_root.findall(f'.//{{{W}}}style')
        if el.get(f'{{{W}}}styleId') == 'Hyperlink'
        and el.get(f'{{{W}}}type') == 'character'
    ]
    assert hl_styles, 'Hyperlink character style must be present in word/styles.xml'
    rPr = hl_styles[0].find(f'{{{W}}}rPr')
    assert rPr is not None
    color = rPr.find(f'{{{W}}}color')
    assert color is not None and color.get(f'{{{W}}}val') == '0563C1'
    u_el = rPr.find(f'{{{W}}}u')
    assert u_el is not None and u_el.get(f'{{{W}}}val') == 'single'


def test_docx_docbook_link_run_uses_hyperlink_style(docx_parts):
    """The link text must be rendered with the Hyperlink character style."""
    doc = docx_parts['word/document.xml']
    hl_runs = []
    for r in doc.iter(f'{{{W}}}r'):
        rPr = r.find(f'{{{W}}}rPr')
        if rPr is None:
            continue
        rStyle = rPr.find(f'{{{W}}}rStyle')
        if rStyle is not None and rStyle.get(f'{{{W}}}val') == 'Hyperlink':
            hl_runs.append(r)
    assert hl_runs, 'at least one run must reference the Hyperlink character style'
    texts = [''.join(t.text or '' for t in r.iter(f'{{{W}}}t')) for r in hl_runs]
    assert any('link' in t for t in texts), \
        f'run with Hyperlink style must contain the link text; found: {texts}'


_R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_HYPERLINK_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'


def test_docx_docbook_hyperlink_element_present(docx_parts):
    """External links must be wrapped in w:hyperlink elements."""
    doc = docx_parts['word/document.xml']
    hl_els = list(doc.iter(f'{{{W}}}hyperlink'))
    assert hl_els, 'at least one w:hyperlink element must be present in word/document.xml'


def test_docx_docbook_hyperlink_has_relationship_id(docx_parts):
    """Each w:hyperlink must carry an r:id attribute."""
    doc = docx_parts['word/document.xml']
    for hl in doc.iter(f'{{{W}}}hyperlink'):
        r_id = hl.get(f'{{{_R_NS}}}id')
        assert r_id, f'w:hyperlink missing r:id attribute'


def test_docx_docbook_hyperlink_relationship_in_rels(docx_parts):
    """The relationship file must contain a Hyperlink relationship pointing to example.com."""
    rels_key = 'word/_rels/document.xml.rels'
    assert rels_key in docx_parts, f'{rels_key} not found in docx parts'
    rels_root = docx_parts[rels_key]
    RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
    hyperlinks = [
        el for el in rels_root.iter(f'{{{RELS_NS}}}Relationship')
        if el.get('Type') == _HYPERLINK_RT
    ]
    assert hyperlinks, 'no Hyperlink relationship found in document.xml.rels'
    targets = [el.get('Target', '') for el in hyperlinks]
    assert any('example.com' in t for t in targets), \
        f'expected example.com in hyperlink targets; got: {targets}'
