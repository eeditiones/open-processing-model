"""Tests for TEI pb milestone chunking (view=page)."""

from __future__ import annotations

from lxml import etree

from opm.config import ChunkingConfig
from opm.navigation import dbk_section_chunks, tei_pb_chunks
from opm.runtime.output_functions import XML_ID

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode('utf-8'))


def test_tei_pb_chunks_splits_on_milestones_preserving_structure() -> None:
    root = _parse(
        f'''<TEI xmlns="{TEI_NS}">
  <text><body>
    <div type="play">
      <pb facs="a.jpg" n="1"/>
      <head>Title</head>
      <div type="scene">
        <sp><speaker>A</speaker>
          <p>Before the break
            <pb facs="b.jpg" n="2"/>
            and after it.</p>
        </sp>
        <sp><speaker>B</speaker><p>Next speech.</p></sp>
        <pb facs="c.jpg" n="3"/>
        <sp><speaker>C</speaker><p>Last page.</p></sp>
      </div>
    </div>
  </body></text>
</TEI>'''
    )
    chunks = tei_pb_chunks(root, ChunkingConfig())
    assert len(chunks) == 3
    assert [c.get(XML_ID) for c in chunks] == ['page-1', 'page-2', 'page-3']

    # Page 1: from first pb through head, up to but not including second pb.
    page1 = etree.tostring(chunks[0], encoding='unicode')
    assert 'facs="a.jpg"' in page1
    assert 'Title' in page1
    assert 'Before the break' in page1
    assert 'facs="b.jpg"' not in page1
    assert 'and after it' not in page1

    # Page 2: starts at second pb, includes rest of speech + next speech, not third pb.
    page2 = etree.tostring(chunks[1], encoding='unicode')
    assert 'facs="b.jpg"' in page2
    assert 'and after it' in page2
    assert 'Next speech' in page2
    assert 'facs="c.jpg"' not in page2
    assert 'Last page' not in page2

    # Page 3: last pb through end of context.
    page3 = etree.tostring(chunks[2], encoding='unicode')
    assert 'facs="c.jpg"' in page3
    assert 'Last page' in page3


def test_tei_pb_chunks_unnamespaced_and_single_pb_uses_text() -> None:
    root = _parse(
        '''<TEI>
  <text><body>
    <div>
      <pb n="10"/>
      <p>Only page.</p>
    </div>
  </body></text>
</TEI>'''
    )
    chunks = tei_pb_chunks(root, ChunkingConfig())
    assert len(chunks) == 1
    assert chunks[0].get(XML_ID) == 'page-10'
    # Single-pb documents carve from tei:text.
    assert etree.QName(chunks[0]).localname == 'text'
    assert 'Only page' in etree.tostring(chunks[0], encoding='unicode')


def test_tei_pb_chunks_prefers_existing_xml_id() -> None:
    root = _parse(
        f'''<TEI xmlns="{TEI_NS}">
  <text><body><div>
    <pb xml:id="leaf-1" n="9"/>
    <p>a</p>
    <pb xml:id="leaf-2" n="10"/>
    <p>b</p>
  </div></body></text>
</TEI>'''
    )
    chunks = tei_pb_chunks(root, ChunkingConfig())
    assert [c.get(XML_ID) for c in chunks] == ['leaf-1', 'leaf-2']


def test_tei_pb_chunks_empty_without_pb() -> None:
    root = _parse(f'<TEI xmlns="{TEI_NS}"><text><body><div><p>x</p></div></body></text></TEI>')
    assert tei_pb_chunks(root, ChunkingConfig()) == []


def test_dbk_intro_chunks_are_detached_copies() -> None:
    """Fill intros are new elements; ``$parameters?root`` maps back via xml:id."""
    dbk = 'http://docbook.org/ns/docbook'
    root = etree.fromstring(
        f'''<article xmlns="{dbk}">
  <info><title>Guide</title></info>
  <section xml:id="install">
    <title>Install</title>
    <para>Intro</para>
    <section xml:id="pip"><title>pip</title><para>x</para></section>
  </section>
</article>'''.encode(),
    )
    chunks = dbk_section_chunks(root, ChunkingConfig(depth=2))
    assert len(chunks) == 2
    intro, pip = chunks
    assert intro.get(XML_ID) == 'install'
    assert intro.getroottree().getroot() is intro
    assert pip.getroottree().getroot() is root
