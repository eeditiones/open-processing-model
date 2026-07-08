"""Tests for chunk-aware link rewriting."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

from opm.chunking import chunk_document
from opm.config import ChunkingConfig, FragmentConfig

ROOT = Path(__file__).resolve().parents[1]
WIBORADA_ODD = ROOT / 'odd' / 'wiborada.odd'


def _write_chunking_fixture_module(path: Path) -> None:
    path.write_text(
        """
from __future__ import annotations

from lxml import etree

from opm.runtime.output_functions import XML_ID

ODD_GENERATED_CSS = ''

ODD_NAME = 'teipublisher'


def transform_output_channels():
    return ['web']


def _append_children(node, out):
    if node.text:
        out.text = node.text
    for child in node:
        rendered = _render(child)
        last = None
        for item in rendered:
            if isinstance(item, str):
                if last is not None:
                    last.tail = (last.tail or '') + item
                else:
                    out.text = (out.text or '') + item
            else:
                out.append(item)
                last = item
        if child.tail:
            if last is not None:
                last.tail = (last.tail or '') + child.tail
            else:
                out.text = (out.text or '') + child.tail


def _render(node):
    tag = etree.QName(node).localname
    if tag == 'div':
        el = etree.Element('div')
        xml_id = node.get(XML_ID)
        if xml_id:
            el.set('id', xml_id)
        node_type = node.get('type')
        if node_type:
            el.set('class', node_type)
        _append_children(node, el)
        return [el]
    if tag == 'p':
        el = etree.Element('p')
        _append_children(node, el)
        return [el]
    if tag == 'ref':
        el = etree.Element('a')
        target = node.get('target')
        if target:
            el.set('href', target)
        _append_children(node, el)
        return [el]
    if tag == 'marker':
        el = etree.Element('span')
        target = node.get('target')
        if target:
            el.set('data-target', target)
        el.text = 'marker'
        return [el]
    return [node.text or '']


def transform(root, options=None):
    _ = options
    return _render(root)


def apply(config, nodes):
    _ = config
    result = []
    for node in nodes:
        if isinstance(node, str):
            result.append(node)
        elif isinstance(node, etree._Element):
            result.extend(_render(node))
        else:
            result.append(str(node))
    return result


def _dispatch(config, node):
    return apply(config, [node])
""".strip(),
        encoding='utf-8',
    )


def _write_chunking_fixture_xml(path: Path) -> None:
    path.write_text(
        """<doc>
  <body>
    <div type="toc">
      <p><ref target="#a">A</ref> <ref target="#b">B</ref></p>
    </div>
    <div type="chunk" xml:id="a">
      <p><ref target="#a">self</ref> <ref target="#b">next</ref></p>
      <marker target="#b"/>
    </div>
    <div type="chunk" xml:id="b">
      <p><ref target="#a">prev</ref> <ref target="#b">self</ref></p>
    </div>
  </body>
</doc>
""",
        encoding='utf-8',
    )


def _chunking_config(output_dir: str, link_pattern: str | None = None) -> ChunkingConfig:
    return ChunkingConfig(
        xpath="//body/div[@type='chunk']",
        output_dir=output_dir,
        link_pattern=link_pattern,
        fragments=[
            FragmentConfig(
                name='toc',
                scope='global',
                xpath="//body/div[@type='toc']",
            ),
        ],
    )


def test_chunk_document_rewrites_same_document_links_in_json_output(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('json-chunks'),
        project_root=tmp_path,
        output_format='json',
    )

    chunk_one = json.loads((tmp_path / 'json-chunks' / '001.json').read_text(encoding='utf-8'))
    manifest = json.loads((tmp_path / 'json-chunks' / 'manifest.json').read_text(encoding='utf-8'))

    assert 'href="#a"' in chunk_one['content']
    assert 'href="002.html#b"' in chunk_one['content']
    assert 'data-target="002.html#b"' in chunk_one['content']

    toc = chunk_one['fragments']['toc']
    assert 'href="#a"' in toc
    assert 'href="002.html#b"' in toc

    manifest_toc = manifest['fragments']['toc']
    assert 'href="001.html#a"' in manifest_toc
    assert 'href="002.html#b"' in manifest_toc
    assert manifest['anchors'] == {'a': '001.html', 'b': '002.html'}


def test_chunk_document_rewrites_same_document_links_in_html_output(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('html-chunks'),
        project_root=tmp_path,
        output_format='html',
    )

    chunk_one_html = (tmp_path / 'html-chunks' / '001.html').read_text(encoding='utf-8')
    toc_html = (tmp_path / 'html-chunks' / 'toc.html').read_text(encoding='utf-8')

    assert 'href="#a"' in chunk_one_html
    assert 'href="002.html#b"' in chunk_one_html
    assert 'data-target="002.html#b"' in chunk_one_html

    assert 'href="001.html#a"' in toc_html
    assert 'href="002.html#b"' in toc_html


def test_link_pattern_stem_anchor(tmp_path: Path) -> None:
    """link_pattern = '/{stem}#{anchor}' produces absolute paths without extension."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('lp-stem-chunks', link_pattern='/{stem}#{anchor}'),
        project_root=tmp_path,
        output_format='json',
    )

    chunk_one = json.loads((tmp_path / 'lp-stem-chunks' / '001.json').read_text(encoding='utf-8'))

    # Same-chunk link must stay as plain anchor
    assert 'href="#a"' in chunk_one['content']
    # Cross-chunk link must use the pattern (stem = "002", anchor = "b")
    assert 'href="/002#b"' in chunk_one['content']
    assert 'data-target="/002#b"' in chunk_one['content']

    toc = chunk_one['fragments']['toc']
    assert 'href="#a"' not in toc or 'href="/001#a"' in toc or 'href="#a"' in toc
    assert 'href="/002#b"' in toc


def test_link_pattern_full_url(tmp_path: Path) -> None:
    """link_pattern with a full base URL produces absolute URLs."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('lp-url-chunks', link_pattern='http://localhost:8080/{stem}#{anchor}'),
        project_root=tmp_path,
        output_format='json',
    )

    chunk_one = json.loads((tmp_path / 'lp-url-chunks' / '001.json').read_text(encoding='utf-8'))

    assert 'href="#a"' in chunk_one['content']
    assert 'href="http://localhost:8080/002#b"' in chunk_one['content']


def test_chunk_document_pb_view_export(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    config = ChunkingConfig(
        xpath="//body/div[@type='chunk']",
        output_dir='pb-view-chunks',
        view='div',
        parameters={'lang': 'de'},
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='pb-view',
    )

    out = tmp_path / 'pb-view-chunks'

    # One part file per chunk, named by xml:id.
    part_a = json.loads((out / 'a.json').read_text(encoding='utf-8'))
    part_b = json.loads((out / 'b.json').read_text(encoding='utf-8'))

    assert part_a['id'] == 'a' and part_a['root'] == 'a'
    assert part_a['next'] == 'b' and part_a['nextId'] == 'b'
    assert 'previous' not in part_a
    assert part_b['previous'] == 'a' and part_b['previousId'] == 'a'
    assert 'next' not in part_b
    assert 'id="a"' in part_a['content']

    # Lookup table mirrors pb-view's createKey() (sorted name=value, joined by &).
    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
    # Keys sort all parameter names together, as pb-view's createKey() does.
    assert index['odd=teipublisher.odd&user.lang=de&view=div'] == 'a.json'  # initial load
    assert index["odd=teipublisher.odd&user.lang=de&view=div&xpath=//body/div[@type='chunk']"] == 'a.json'
    assert index['id=a&odd=teipublisher.odd&user.lang=de&view=div'] == 'a.json'
    assert index['odd=teipublisher.odd&root=a&user.lang=de&view=div'] == 'a.json'
    assert index['id=b&odd=teipublisher.odd&user.lang=de&view=div'] == 'b.json'
    assert index['odd=teipublisher.odd&root=b&user.lang=de&view=div'] == 'b.json'
    # xpath key registered only once (first chunk), no positional suffix
    assert "xpath=//body/div[@type='chunk'][2]" not in str(index)

    # ODD stylesheet written where pb-view expects it.
    assert (out / 'css' / 'teipublisher.css').is_file()


def test_chunk_document_pb_view_doc_path_layout(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    config = ChunkingConfig(
        xpath="//body/div[@type='chunk']",
        output_dir='site',
        view='div',
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='pb-view',
        doc_path='fixture.xml',
    )

    site = tmp_path / 'site'
    # Data lives under the document path; pb-view fetches ${static}/${path}/...
    assert (site / 'fixture.xml' / 'index.json').is_file()
    assert (site / 'fixture.xml' / 'a.json').is_file()
    assert (site / 'fixture.xml' / 'b.json').is_file()
    # CSS is shared at the static root, not under the document path.
    assert (site / 'css' / 'teipublisher.css').is_file()
    assert not (site / 'fixture.xml' / 'css').exists()

    index = json.loads((site / 'fixture.xml' / 'index.json').read_text(encoding='utf-8'))
    assert index['odd=teipublisher.odd&view=div'] == 'a.json'


def test_pb_view_export_per_chunk_fragments(tmp_path: Path) -> None:
    """Per-chunk fragments produce {name}-{xml_id}.json files beside the main chunks."""
    module_path = tmp_path / 'chunk_fixture.py'
    _write_chunking_fixture_module(module_path)

    xml_path = tmp_path / 'parallel.xml'
    xml_path.write_text(
        """<doc>
  <body>
    <div xml:lang="zh" xml:id="zh1"><p>漢</p></div>
    <div xml:lang="zh" xml:id="zh2"><p>字</p></div>
    <div xml:lang="en" xml:id="en1"><p>one</p></div>
    <div xml:lang="en" xml:id="en2"><p>two</p></div>
  </body>
</doc>""",
        encoding='utf-8',
    )

    config = ChunkingConfig(
        xpath="//body/div[@xml:lang='zh']",
        output_dir='pb-frags',
        view='div',
        fragments=[
            FragmentConfig(
                name='en',
                scope='per-chunk',
                xpath="//body/div[@xml:lang='en']",
            ),
        ],
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='pb-view',
    )

    out = tmp_path / 'pb-frags'

    # Main chunk files.
    assert (out / 'zh1.json').is_file()
    assert (out / 'zh2.json').is_file()

    # Fragment files named {name}-{xml_id}.json.
    frag1 = json.loads((out / 'en-zh1.json').read_text(encoding='utf-8'))
    frag2 = json.loads((out / 'en-zh2.json').read_text(encoding='utf-8'))
    assert 'one' in frag1['content']
    assert 'two' in frag2['content']
    assert frag1['next'] == 'zh2' and frag2['previous'] == 'zh1'

    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))

    # Fragment xpath registered once (first chunk).
    assert index["odd=teipublisher.odd&view=div&xpath=//body/div[@xml:lang='en']"] == 'en-zh1.json'
    # Per-chunk/id fragment lookups include xpath to distinguish from main.
    assert index["odd=teipublisher.odd&root=zh1&view=div&xpath=//body/div[@xml:lang='en']"] == 'en-zh1.json'
    assert index["odd=teipublisher.odd&root=zh2&view=div&xpath=//body/div[@xml:lang='en']"] == 'en-zh2.json'
    assert index["id=zh1&odd=teipublisher.odd&view=div&xpath=//body/div[@xml:lang='en']"] == 'en-zh1.json'
    # No positional suffix anywhere.
    assert "[1]" not in str(index)


def test_chunk_document_pb_view_requires_xml_id(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    # Select every div, including the <div type="toc"> that has no xml:id.
    config = ChunkingConfig(xpath="//body/div", output_dir='pb-view-bad')

    with pytest.raises(ValueError, match=r'<div type="toc"> \(line \d+\)'):
        chunk_document(
            module_path=module_path,
            xml_path=xml_path,
            config=config,
            project_root=tmp_path,
            output_format='pb-view',
        )


@pytest.mark.skipif(not WIBORADA_ODD.is_file(), reason='Fixture odd/wiborada.odd not found')
def test_wiborada_web_div_with_n_preserves_xml_id(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd
    from opm.runtime.pm_runtime import serialize

    module_path = tmp_path / 'wiborada_web.py'
    module_path.write_text(compile_odd(str(WIBORADA_ODD)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('wiborada_web', str(module_path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    root = etree.fromstring(
        b"""<TEI xmlns="http://www.tei-c.org/ns/1.0" type="transcription" xml:lang="de">
<teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>
<text><body><div xml:id="intro" n="I"><p>x</p></div></body></text>
</TEI>""",
    )
    rendered = serialize(module.transform(root))

    assert 'id="intro"' in rendered


def _write_tei_namespaced_fixture_xml(path: Path) -> None:
    path.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <div xml:lang="zh" xml:id="zh1"><p>漢</p></div>
      <div xml:lang="en" xml:id="en1"><p>english</p></div>
      <div xml:lang="zh" xml:id="zh2"><p>字</p></div>
    </body>
  </text>
</TEI>
""",
        encoding='utf-8',
    )


def test_select_chunks_resolves_default_namespace(tmp_path: Path) -> None:
    """Unprefixed names in the chunk selector match TEI-namespaced elements.

    Regression: select_chunks() used raw lxml xpath() with a prefix-only nsmap,
    so //body/div never matched a document whose only namespace is the default
    TEI namespace, yielding "no chunks selected".
    """
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_tei_namespaced_fixture_xml(xml_path)

    config = ChunkingConfig(
        xpath="//body/div[@xml:lang='zh']",
        output_dir='tei-chunks',
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='json',
    )

    out_dir = tmp_path / 'tei-chunks'
    manifest = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))

    # Only the two zh divs are selected, not the en one.
    assert len(manifest['chunks']) == 2
    assert (out_dir / '001.json').is_file()
    assert (out_dir / '002.json').is_file()
    assert not (out_dir / '003.json').is_file()
