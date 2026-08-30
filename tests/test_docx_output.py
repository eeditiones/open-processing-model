"""Integration tests for DOCX output mode.

Compiles packaged ``teipublisher.odd`` for docx mode, transforms ``tests/test-docx.xml``
with the packaged Word template, and asserts the structural properties of the
resulting Word document.
"""

from __future__ import annotations

import importlib.util
import re
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from lxml import etree

from opm.resources import packaged_default_docx, packaged_odd

ROOT = Path(__file__).resolve().parents[1]
ODD = packaged_odd('teipublisher')
TEST_XML = ROOT / 'tests' / 'test-docx.xml'

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
TEI = 'http://www.tei-c.org/ns/1.0'
DC = 'http://purl.org/dc/elements/1.1/'
CORE_PROPS = 'docProps/core.xml'
DOCX_SENTINEL_NS = 'http://www.tei-c.org/ns/docx'


def _parse_docx(data: bytes) -> dict[str, etree._Element]:
    """Open a docx byte string and return parsed XML roots keyed by part name."""
    parts: dict[str, etree._Element] = {}
    with zipfile.ZipFile(BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith('.xml') or name.endswith('.rels'):
                parts[name] = etree.fromstring(z.read(name))
    return parts


def _list_paras(doc_root: etree._Element) -> list[dict]:
    """Return all paragraphs that carry w:numPr, with their key properties."""
    results = []
    # Use xpath instead of iter for better type compatibility
    for p in doc_root.xpath('.//w:p', namespaces={'w': W}):
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


def _compile_docx_module(tmp_path: Path) -> object:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD), output_mode='docx')
    path = tmp_path / 'teipublisher_docx.py'
    path.write_text(src, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('teipublisher_docx_fixture', str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def docx_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """Compile ODD, transform test-docx.xml with the packaged Word template, return raw .docx bytes."""
    from opm.transform import run_transform

    tmp = tmp_path_factory.mktemp('docx')
    mod = _compile_docx_module(tmp)

    root = etree.parse(str(TEST_XML)).getroot()
    result = run_transform(
        mod,
        root,
        parameters={'input_path': str(TEST_XML)},
        docx_template=packaged_default_docx(),
    )
    assert isinstance(result, bytes), 'transform must return bytes for docx mode'
    return result


@pytest.fixture(scope='module')
def docx_parts(docx_bytes: bytes) -> dict[str, etree._Element]:
    """Parsed XML parts from :func:`docx_bytes`."""
    return _parse_docx(docx_bytes)


def test_docx_contains_required_parts(docx_parts):
    assert 'word/document.xml' in docx_parts
    assert 'word/numbering.xml' in docx_parts


def test_docx_list_items_have_numpr(docx_parts):
    """Every list item (AAA, BBB, One, Two, Three) must have a w:numPr."""
    paras = _list_paras(docx_parts['word/document.xml'])
    texts = [p['text'] for p in paras]
    for expected in ('AAA', 'BBB', 'One', 'Two', 'Three'):
        assert any(expected in t for t in texts), f'list item "{expected}" has no w:numPr'


def test_docx_outer_list_items_at_ilvl_0(docx_parts):
    paras = _list_paras(docx_parts['word/document.xml'])
    for label in ('AAA', 'BBB'):
        matches = [p for p in paras if label in p['text']]
        assert matches, f'paragraph "{label}" not found'
        assert matches[0]['ilvl'] == 0, f'"{label}" should be at ilvl=0, got {matches[0]["ilvl"]}'


def test_docx_outer_list_items_share_numid(docx_parts):
    """AAA and BBB belong to the same list and must share the same numId."""
    paras = _list_paras(docx_parts['word/document.xml'])
    aaa = next(p for p in paras if 'AAA' in p['text'])
    bbb = next(p for p in paras if 'BBB' in p['text'])
    assert aaa['numid'] == bbb['numid'], 'AAA and BBB must share the same numId'


def test_docx_inner_ordered_items_use_different_numid(docx_parts):
    """The inner ordered list (One/Two/Three) must use a different numId than the outer bullet list."""
    paras = _list_paras(docx_parts['word/document.xml'])
    outer_numid = next(p['numid'] for p in paras if 'AAA' in p['text'])
    inner_numid = next(p['numid'] for p in paras if 'One' in p['text'])
    assert inner_numid != outer_numid, 'inner ordered list must have its own numId'


def test_docx_inner_ordered_items_share_numid(docx_parts):
    """One, Two, Three belong to the same list and must share a numId."""
    paras = _list_paras(docx_parts['word/document.xml'])
    one = next(p for p in paras if 'One' in p['text'])
    two = next(p for p in paras if 'Two' in p['text'])
    three = next(p for p in paras if 'Three' in p['text'])
    assert one['numid'] == two['numid'] == three['numid'], \
        'One/Two/Three must share the same numId'


def test_docx_numbering_abstracts_are_multilevel(docx_parts):
    """The injected abstract definitions must cover at least levels 0-2."""
    num_root = docx_parts['word/numbering.xml']
    abstracts = num_root.findall(f'{{{W}}}abstractNum')
    multilevel = [
        a for a in abstracts
        if len(a.findall(f'{{{W}}}lvl')) >= 3
    ]
    assert multilevel, 'at least one multilevel abstract (≥3 levels) must be present'


def test_docx_num_instances_have_start_override(docx_parts):
    """Each per-list w:num (numId ≥ 100) must carry a lvlOverride/startOverride for restart."""
    num_root = docx_parts['word/numbering.xml']
    for num_el in num_root.findall(f'{{{W}}}num'):
        numid = int(num_el.get(f'{{{W}}}numId', '0'))
        if numid < 100:
            continue
        override = num_el.find(f'{{{W}}}lvlOverride')
        assert override is not None, f'numId={numid} missing lvlOverride'
        start = override.find(f'{{{W}}}startOverride')
        assert start is not None, f'numId={numid} missing startOverride'
        assert start.get(f'{{{W}}}val') == '1', f'numId={numid} startOverride must be 1'


def test_docx_outer_list_uses_bullet_abstract(docx_parts):
    """The outer (bullet) list numId must reference an abstract with bullet numFmt at level 0."""
    num_root = docx_parts['word/numbering.xml']
    paras = _list_paras(docx_parts['word/document.xml'])
    outer_numid = next(p['numid'] for p in paras if 'AAA' in p['text'])

    # Find the abstractNumId that outer_numid references
    abstract_id = None
    for num_el in num_root.findall(f'{{{W}}}num'):
        if int(num_el.get(f'{{{W}}}numId', '0')) == outer_numid:
            ref = num_el.find(f'{{{W}}}abstractNumId')
            if ref is not None:
                abstract_id = ref.get(f'{{{W}}}val')
    assert abstract_id is not None, f'numId={outer_numid} not found in numbering.xml'

    # Find that abstract and check its level-0 numFmt
    for abs_el in num_root.findall(f'{{{W}}}abstractNum'):
        if abs_el.get(f'{{{W}}}abstractNumId') == abstract_id:
            lvl0 = abs_el.find(f'{{{W}}}lvl[@{{{W}}}ilvl="0"]')
            if lvl0 is None:
                lvl0 = abs_el.find(f'{{{W}}}lvl')
            fmt = lvl0.find(f'{{{W}}}numFmt') if lvl0 is not None else None
            assert fmt is not None and fmt.get(f'{{{W}}}val') == 'bullet', \
                f'outer list abstract (id={abstract_id}) must use bullet numFmt'
            return
    pytest.fail(f'abstractNumId={abstract_id} not found')


def test_docx_inner_list_uses_decimal_abstract(docx_parts):
    """The inner ordered list numId must reference an abstract with decimal numFmt at level 0."""
    num_root = docx_parts['word/numbering.xml']
    paras = _list_paras(docx_parts['word/document.xml'])
    inner_numid = next(p['numid'] for p in paras if 'One' in p['text'])

    abstract_id = None
    for num_el in num_root.findall(f'{{{W}}}num'):
        if int(num_el.get(f'{{{W}}}numId', '0')) == inner_numid:
            ref = num_el.find(f'{{{W}}}abstractNumId')
            if ref is not None:
                abstract_id = ref.get(f'{{{W}}}val')
    assert abstract_id is not None

    for abs_el in num_root.findall(f'{{{W}}}abstractNum'):
        if abs_el.get(f'{{{W}}}abstractNumId') == abstract_id:
            lvl0 = abs_el.find(f'{{{W}}}lvl[@{{{W}}}ilvl="0"]')
            if lvl0 is None:
                lvl0 = abs_el.find(f'{{{W}}}lvl')
            fmt = lvl0.find(f'{{{W}}}numFmt') if lvl0 is not None else None
            assert fmt is not None and fmt.get(f'{{{W}}}val') == 'decimal', \
                f'inner list abstract (id={abstract_id}) must use decimal numFmt'
            return
    pytest.fail(f'abstractNumId={abstract_id} not found (inner decimal)')


def test_docx_hyperlink_style_in_styles_xml(docx_parts):
    """word/styles.xml must define a Hyperlink character style (injected if absent from template)."""
    styles_root = docx_parts['word/styles.xml']
    hl_styles = styles_root.findall(
        f'.//{{{W}}}style[@{{{W}}}styleId="Hyperlink"][@{{{W}}}type="character"]'
    )
    assert hl_styles, 'Hyperlink character style must be present in word/styles.xml'
    rPr = hl_styles[0].find(f'{{{W}}}rPr')
    assert rPr is not None, 'Hyperlink style must have w:rPr'
    color = rPr.find(f'{{{W}}}color')
    assert color is not None and color.get(f'{{{W}}}val') == '0563C1', \
        'Hyperlink style must carry the standard blue color'
    u_el = rPr.find(f'{{{W}}}u')
    assert u_el is not None and u_el.get(f'{{{W}}}val') == 'single', \
        'Hyperlink style must be underlined'


def test_docx_link_run_uses_hyperlink_style(docx_parts):
    """Runs inside a hyperlink must reference the Hyperlink character style."""
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


R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HYPERLINK_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'


def test_docx_hyperlink_element_present(docx_parts):
    """External links must be wrapped in w:hyperlink elements (not just styled runs)."""
    doc = docx_parts['word/document.xml']
    # Use xpath instead of iter for better type compatibility
    hl_els = doc.xpath('.//w:hyperlink', namespaces={'w': W})
    assert hl_els, 'at least one w:hyperlink element must be present in word/document.xml'


def test_docx_hyperlink_has_relationship_id(docx_parts):
    """Each w:hyperlink must carry an r:id attribute pointing to an OPC relationship."""
    doc = docx_parts['word/document.xml']
    # Use xpath instead of iter for better type compatibility
    for hl in doc.xpath('.//w:hyperlink', namespaces={'w': W}):
        r_id = hl.get(f'{{{R_NS}}}id')
        assert r_id, f'w:hyperlink missing r:id attribute: {etree.tostring(hl)}'


def test_docx_hyperlink_relationship_in_rels(docx_parts):
    """The relationship file must contain a Hyperlink relationship pointing to example.com."""
    rels_key = 'word/_rels/document.xml.rels'
    assert rels_key in docx_parts, f'{rels_key} not found in docx parts'
    rels_root = docx_parts[rels_key]
    RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
    hyperlinks = [
        el for el in rels_root.iter(f'{{{RELS_NS}}}Relationship')
        if el.get('Type') == HYPERLINK_RT
    ]
    assert hyperlinks, 'no Hyperlink relationship found in document.xml.rels'
    targets = [el.get('Target', '') for el in hyperlinks]
    assert any('example.com' in t for t in targets), \
        f'expected example.com in hyperlink targets; got: {targets}'


def test_docx_image_element_present(docx_parts):
    """Images must be wrapped in w:drawing elements within paragraphs."""
    doc = docx_parts['word/document.xml']
    # Use xpath instead of iter for better type compatibility
    drawing_els = doc.xpath('.//w:drawing', namespaces={'w': W})
    assert drawing_els, 'at least one w:drawing element must be present in word/document.xml'


def test_docx_image_has_relationship_id(docx_parts):
    """Each w:drawing must reference an image relationship."""
    doc = docx_parts['word/document.xml']
    # Use xpath instead of iter for better type compatibility
    for drawing in doc.xpath('.//w:drawing', namespaces={'w': W}):
        # Look for blip element with r:embed attribute
        A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        blip = drawing.find(f'.//{{{A}}}blip')
        if blip is not None:
            r_id = blip.get(f'{{{R_NS}}}embed')
            assert r_id, f'w:drawing blip missing r:embed attribute: {etree.tostring(drawing)}'


def test_docx_image_relationship_in_rels(docx_parts):
    """The relationship file must contain an Image relationship."""
    rels_key = 'word/_rels/document.xml.rels'
    assert rels_key in docx_parts, f'{rels_key} not found in docx parts'
    rels_root = docx_parts[rels_key]
    RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
    IMAGE_RT = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
    images = [
        el for el in rels_root.iter(f'{{{RELS_NS}}}Relationship')
        if el.get('Type') == IMAGE_RT
    ]
    assert images, 'no Image relationship found in document.xml.rels'


def test_docx_image_file_present(docx_bytes):
    """The image file must be present in the DOCX package."""
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        image_files = [f for f in z.namelist() if f.startswith('word/media/')]
        assert image_files, 'no image files found in word/media/ directory'
        # Check that at least one image file exists
        for img_file in image_files:
            assert img_file.endswith('.svg') or img_file.endswith('.png') or img_file.endswith('.jpg'), \
                f'unexpected image file extension: {img_file}'


def test_docx_title_reaches_core_properties(docx_parts):
    """The ODD's metadata models populate the Word document properties."""
    assert docx_parts[CORE_PROPS].findtext(f'{{{DC}}}title') == 'Testing'


def test_docx_authors_joined_into_creator(tmp_path):
    """Multiple authors collapse into one dc:creator and stay out of the body."""
    from opm.transform import run_transform

    mod = _compile_docx_module(tmp_path)
    root = etree.parse(str(TEST_XML)).getroot()
    title_stmt = root.find(f'.//{{{TEI}}}titleStmt')
    assert title_stmt is not None
    for name in ('Ada Lovelace', 'Charles Babbage'):
        etree.SubElement(title_stmt, f'{{{TEI}}}author').text = name

    parts = _parse_docx(run_transform(mod, root, docx_template=packaged_default_docx()))
    assert parts[CORE_PROPS].findtext(f'{{{DC}}}creator') == 'Ada Lovelace, Charles Babbage'

    body_text = ''.join(t.text or '' for t in parts['word/document.xml'].iter(f'{{{W}}}t'))
    assert 'Ada Lovelace' not in body_text


def test_docx_missing_image_leaves_no_sentinel(tmp_path):
    """A missing image degrades to a placeholder run, never a foreign element.

    Word refuses to open a document containing elements outside the OOXML
    namespaces, so an unresolvable image must not leave its sentinel behind.
    """
    from opm.transform import run_transform

    mod = _compile_docx_module(tmp_path)
    root = etree.parse(str(TEST_XML)).getroot()
    body = root.find(f'.//{{{TEI}}}body')
    assert body is not None
    p = etree.SubElement(body, f'{{{TEI}}}p')
    etree.SubElement(p, f'{{{TEI}}}graphic').set('corresp', 'does_not_exist.png')

    parts = _parse_docx(
        run_transform(
            mod,
            root,
            parameters={'input_path': str(TEST_XML)},
            docx_template=packaged_default_docx(),
        )
    )
    doc_root = parts['word/document.xml']
    leftover = [
        etree.QName(el).localname
        for el in doc_root.iter()
        if isinstance(el.tag, str) and etree.QName(el).namespace == DOCX_SENTINEL_NS
    ]
    assert not leftover, f'sentinels left in body: {leftover}'

    texts = [t.text or '' for t in doc_root.iter(f'{{{W}}}t')]
    assert any('does_not_exist.png' in t for t in texts), 'no placeholder for missing image'


_FOOTNOTE_LINK_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    '<teiHeader><fileDesc><titleStmt><title>Notes</title></titleStmt>'
    '<publicationStmt><p>n</p></publicationStmt><sourceDesc><p>s</p></sourceDesc>'
    '</fileDesc></teiHeader>'
    '<text><body><div><p>Text.'
    '<note place="foot">See <ref target="https://example.org/a">A</ref>.</note>'
    '<note place="foot">And <ref target="https://example.org/b">B</ref>.</note>'
    '<note place="foot">Again <ref target="https://example.org/a">A</ref>.</note>'
    '</p></div></body></text></TEI>'
)


def _docx_zip(xml: str, tmp_path):
    import zipfile

    from opm.odd_compiler import compile_odd
    from opm.resources import packaged_odd
    from opm.transform import load_transform_module, run_transform

    mod_path = tmp_path / 'tei_docx.py'
    mod_path.write_text(
        compile_odd(str(packaged_odd('teipublisher')), output_mode='docx'), encoding='utf-8'
    )
    out = run_transform(load_transform_module(mod_path), etree.fromstring(xml.encode()))
    assert isinstance(out, bytes)
    path = tmp_path / 'out.docx'
    path.write_bytes(out)
    return zipfile.ZipFile(str(path))


def test_footnote_hyperlinks_become_relationships_not_sentinels(tmp_path) -> None:
    """A link inside a footnote must resolve against footnotes.xml.rels.

    Only body sentinels used to be replaced, so ``footnotes.xml`` kept internal
    placeholder elements and an empty rels part — Word offered to repair the file.
    """
    import re

    z = _docx_zip(_FOOTNOTE_LINK_TEI, tmp_path)
    footnotes = z.read('word/footnotes.xml').decode()
    rels = z.read('word/_rels/footnotes.xml.rels').decode()

    assert 'hyperlink-sentinel' not in footnotes
    assert footnotes.count('<w:hyperlink') == 3

    used = set(re.findall(r'r:id="(rId\d+)"', footnotes))
    declared = set(re.findall(r'Id="(rId\d+)"', rels))
    assert used and not used - declared
    # Repeated targets share one relationship.
    assert rels.count('<Relationship ') == 2
    assert 'TargetMode="External"' in rels


def test_no_part_keeps_an_internal_sentinel_namespace(tmp_path) -> None:
    """Sentinels are an internal device; any that survive make the package invalid."""
    z = _docx_zip(_FOOTNOTE_LINK_TEI, tmp_path)
    for name in z.namelist():
        if name.endswith(('.xml', '.rels')):
            assert b'tei-c.org/ns/docx' not in z.read(name), name
