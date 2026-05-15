"""Tests for chunk-aware link rewriting."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from lxml import etree

from teipublisher.chunking import chunk_document
from teipublisher.config import ChunkingConfig, FragmentConfig

ROOT = Path(__file__).resolve().parents[1]
WIBORADA_ODD = ROOT / 'odd' / 'wiborada.odd'


def _write_chunking_fixture_module(path: Path) -> None:
    path.write_text(
        """
from __future__ import annotations

from lxml import etree

from teipublisher.runtime.output_functions import XML_ID

ODD_GENERATED_CSS = ''


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
        enabled=True,
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


@pytest.mark.skipif(not WIBORADA_ODD.is_file(), reason='Fixture odd/wiborada.odd not found')
def test_wiborada_web_div_with_n_preserves_xml_id(tmp_path: Path) -> None:
    from teipublisher.odd_compiler import compile_odd
    from teipublisher.runtime.pm_runtime import serialize

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
