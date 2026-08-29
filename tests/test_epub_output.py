"""Tests for EPUB output functions and packager."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from lxml import etree

from opm.epub import (
    XHTML_NS,
    _resolve_internal_links,
    _rewrite_to_xhtml,
)
from opm.odd_cache import ensure_compiled_module
from opm.odd_compiler.codegen import _model_matches_output_mode
from opm.resources import packaged_odd
from opm.runtime.epub_output_functions import EPUB_TYPE, EpubOutputFunctions
from opm.runtime.pm_runtime import apply_children, serialize
from opm.transform import load_transform_module, run_transform


def _apply_children(config, node, content, parent_el) -> None:
    apply_children(config, node, content, parent_el)


def _config() -> dict:
    return {
        'apply_children': _apply_children,
        'apply': lambda _c, nodes: list(nodes) if isinstance(nodes, list) else [nodes],
        # Content elements pass straight through: these tests exercise the
        # output functions, not model dispatch.
        'dispatch': lambda _c, node, _params: [node],
        'footnotes': [],
        'webcomponents': False,
    }


def test_epub_block_sets_id_when_missing() -> None:
    """Port of tep:block-sets-id-when-missing."""
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.block(_config(), node, ['c'], 'X')
    assert len(res) == 1
    el = res[0]
    assert el.tag == 'div'
    assert el.get('class') == 'c'
    assert el.get('id')


def test_epub_break_page_with_label() -> None:
    """Port of tep:break-page-with-label."""
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.break_(_config(), node, ['c'], None, type='page', label='12')
    assert len(res) == 1
    el = res[0]
    assert el.tag == 'span'
    assert 'pagebreak' in el.get('class', '').split()
    assert el.get('id') == 'page12'
    assert el.get(EPUB_TYPE) == 'pagebreak'
    assert el.text == '12'


def test_epub_alternate_yields_linked_aside() -> None:
    """Port of tep:alternate-yields-linked-aside."""
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.alternate(_config(), node, ['c'], None, 'D', 'A')
    assert len(res) == 2
    a, aside = res
    assert a.tag == 'a'
    assert 'alternate' in a.get('class', '').split()
    assert aside.tag == 'aside'
    assert 'altcontent' in aside.get('class', '').split()
    assert a.get('href', '').lstrip('#') == aside.get('id')


def test_epub_note_noteref_and_aside() -> None:
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.note(_config(), node, ['c'], 'note body', place='footnote', label=None)
    assert len(res) == 2
    ref, aside = res
    assert ref.tag == 'a'
    assert ref.get(EPUB_TYPE) == 'noteref'
    assert aside.tag == 'aside'
    assert aside.get(EPUB_TYPE) == 'footnote'
    assert ref.get('href', '').lstrip('#') == aside.get('id')


def test_epub_webcomponent_degrades_to_block_wrapper() -> None:
    """Custom elements are not EPUB 3 vocabulary; block content becomes a div."""
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    inner = etree.Element('p')
    inner.text = 'body'
    res = pmf.webcomponent(_config(), node, ['c'], [inner], 'pb-observable')
    assert len(res) == 1
    assert res[0].tag == 'div'
    assert res[0].find('p') is not None


def test_epub_webcomponent_degrades_inline_to_span() -> None:
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.webcomponent(_config(), node, ['c'], 'text', 'pb-highlight')
    assert res[0].tag == 'span'


def test_epub_webcomponent_pb_link_becomes_anchor() -> None:
    """pb-link carries a cross-reference; keep it as a real fragment link."""
    pmf = EpubOutputFunctions()
    node = etree.Element('n')
    res = pmf.webcomponent(
        _config(), node, ['c'], 'see there', 'pb-link', {'xml-id': 'chapter-2'},
    )
    assert len(res) == 1
    assert res[0].tag == 'a'
    assert res[0].get('href') == '#chapter-2'


def test_rewrite_to_xhtml_drops_custom_elements() -> None:
    """pb:template markup reaches the packager directly, bypassing the PMF."""
    src = etree.fromstring(
        '<pb-observable data="x,y" emit="transcription" class="k">'
        '<p>text</p></pb-observable>'
    )
    out = _rewrite_to_xhtml(src)
    assert etree.QName(out).localname == 'div'
    assert out.get('class') == 'k'
    # Vocabulary-specific attributes are not valid on a plain div.
    assert out.get('data') is None
    assert out.get('emit') is None
    assert etree.QName(out[0]).localname == 'p'


def test_resolve_internal_links_qualifies_cross_file_targets() -> None:
    def doc(anchor_id: str, href: str) -> etree._Element:
        html = etree.Element(f'{{{XHTML_NS}}}html')
        body = etree.SubElement(html, f'{{{XHTML_NS}}}body')
        target = etree.SubElement(body, f'{{{XHTML_NS}}}div')
        target.set('id', anchor_id)
        a = etree.SubElement(body, f'{{{XHTML_NS}}}a')
        a.set('href', href)
        return html

    docs = {'one': doc('sec-one', '#sec-two'), 'two': doc('sec-two', '#sec-two')}
    _resolve_internal_links(docs)

    hrefs = {
        key: value.find(f'.//{{{XHTML_NS}}}a').get('href')
        for key, value in docs.items()
    }
    assert hrefs['one'] == 'two.xhtml#sec-two'
    # Same-file reference stays a bare fragment.
    assert hrefs['two'] == '#sec-two'


def test_resolve_internal_links_leaves_ambiguous_ids_alone() -> None:
    """Synthetic ids restart per chapter; an ambiguous target must not be guessed."""
    def doc(href: str) -> etree._Element:
        html = etree.Element(f'{{{XHTML_NS}}}html')
        body = etree.SubElement(html, f'{{{XHTML_NS}}}body')
        etree.SubElement(body, f'{{{XHTML_NS}}}div').set('id', 'n1')
        a = etree.SubElement(body, f'{{{XHTML_NS}}}a')
        a.set('href', href)
        return html

    docs = {'one': doc('#n1'), 'two': doc('#n1')}
    _resolve_internal_links(docs)
    for value in docs.values():
        assert value.find(f'.//{{{XHTML_NS}}}a').get('href') == '#n1'


def test_model_matches_epub_accepts_web_and_epub() -> None:
    web = etree.Element('model')
    web.set('output', 'web')
    epub_el = etree.Element('model')
    epub_el.set('output', 'epub')
    docx = etree.Element('model')
    docx.set('output', 'docx')
    unscoped = etree.Element('model')

    assert _model_matches_output_mode(web, 'epub')
    assert _model_matches_output_mode(epub_el, 'epub')
    assert not _model_matches_output_mode(docx, 'epub')
    assert _model_matches_output_mode(unscoped, 'epub')


def test_build_epub_package_roundtrip(tmp_path: Path) -> None:
    """Compile epub mode, package tei-test.xml, assert EPUB 3 structure."""
    odd_path, _ = ensure_compiled_module(packaged_odd('teipublisher'), output_mode='epub')
    mod = load_transform_module(odd_path)
    xml_path = Path(__file__).resolve().parents[1] / 'examples' / 'tei-test.xml'
    root = etree.parse(str(xml_path)).getroot()

    out = run_transform(
        mod,
        root,
        parameters={'input_path': str(xml_path)},
        epub_skip_title=False,
    )
    assert isinstance(out, bytes)
    assert out[:2] == b'PK'

    epub_path = tmp_path / 'book.epub'
    epub_path.write_bytes(out)

    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        names = zf.namelist()
        assert names[0] == 'mimetype'
        assert zf.read('mimetype') == b'application/epub+zip'
        info = zf.getinfo('mimetype')
        assert info.compress_type == zipfile.ZIP_STORED
        assert 'META-INF/container.xml' in names
        assert 'OEBPS/content.opf' in names
        assert 'OEBPS/nav.xhtml' in names
        assert 'OEBPS/toc.ncx' in names
        assert 'OEBPS/stylesheet.css' in names
        assert 'OEBPS/title.xhtml' in names
        chapter_files = [n for n in names if n.startswith('OEBPS/') and n.endswith('.xhtml')
                         and n not in ('OEBPS/nav.xhtml', 'OEBPS/title.xhtml')]
        assert chapter_files

        opf = etree.fromstring(zf.read('OEBPS/content.opf'))
        assert opf.get('version') == '3.0'
        # At least one spine itemref for a chapter
        spine = opf.find('{http://www.idpf.org/2007/opf}spine')
        assert spine is not None
        assert len(spine) >= 2  # title + chapters

        # XHTML is well-formed XML
        sample = zf.read(chapter_files[0])
        doc = etree.fromstring(sample)
        assert etree.QName(doc).localname == 'html'

        # Every element belongs to the XHTML vocabulary — no custom elements.
        for name in chapter_files + ['OEBPS/title.xhtml']:
            for el in etree.fromstring(zf.read(name)).iter():
                assert etree.QName(el).namespace == XHTML_NS

        css = zf.read('OEBPS/stylesheet.css').decode('utf-8')
        assert '@namespace epub' in css


def test_epub_project_css_is_appended_last(tmp_path: Path) -> None:
    """[transform.epub] css cascades after the baseline and the ODD stylesheet."""
    odd_path, _ = ensure_compiled_module(packaged_odd('teipublisher'), output_mode='epub')
    mod = load_transform_module(odd_path)
    xml_path = Path(__file__).resolve().parents[1] / 'examples' / 'tei-test.xml'
    root = etree.parse(str(xml_path)).getroot()

    project_css = tmp_path / 'epub.css'
    project_css.write_text('body { color: rebeccapurple; }\n', encoding='utf-8')

    out = run_transform(mod, root, epub_css=project_css)
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        css = zf.read('OEBPS/stylesheet.css').decode('utf-8')
    assert css.rstrip().endswith('body { color: rebeccapurple; }')
