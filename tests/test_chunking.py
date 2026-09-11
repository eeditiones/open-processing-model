"""Tests for chunk-aware link rewriting."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from importlib import resources
from pathlib import Path

from lxml import etree

from opm.chunking import (
    ChunkProcessor,
    _wellformed_fragment_xml,
    build_index,
    build_index_json,
    chunk_document,
    collect_index_entries,
)
from opm.config import ChunkingConfig, FragmentConfig, ProjectConfig
from opm.resources import packaged_odd


def _scaffold_template(name: str) -> Path:
    return Path(str(resources.files('opm').joinpath(f'resources/scaffold/templates/{name}')))


def _write_chunking_fixture_module(path: Path) -> None:
    path.write_text(
        """
from __future__ import annotations

from lxml import etree

from opm.runtime.output_functions import XML_ID

ODD_GENERATED_CSS = ''

ODD_NAME = 'teipublisher'


OUTPUT_MODE = 'web'


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
    if tag == 'graphic':
        el = etree.Element('img')
        el.set('src', node.get('url') or '')
        return [el]
    if tag == 'marker':
        el = etree.Element('span')
        target = node.get('target')
        if target:
            el.set('data-target', target)
        el.text = 'marker'
        return [el]
    if tag == 'pblink':
        el = etree.Element('pb-link')
        target = node.get('target')
        if target:
            el.set('xml-id', target)
            el.set('node-id', target)
            el.set('emit', 'transcription')
            el.set('subscribe', 'transcription')
        path = node.get('path')
        if path:
            el.set('path', path)
        _append_children(node, el)
        return [el]
    return [node.text or '']


def transform(root, options=None, *, xpath_env=None):
    _ = options, xpath_env
    return _render(root)


def new_context(root, options=None, *, xpath_env=None):
    from opm.runtime.context import build_context

    return build_context(
        root, options, mode=OUTPUT_MODE, xpath_env=xpath_env,
        dispatch=_dispatch, apply=apply,
    )


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
      <p><pblink target="b">B page</pblink> <pblink path="other.xml">Other</pblink></p>
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


def test_chunk_document_resolves_pb_links(tmp_path: Path) -> None:
    """pb-link carries its target in xml-id, so it becomes a real anchor."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('pb-link-chunks'),
        project_root=tmp_path,
        output_format='html',
    )

    toc_html = (tmp_path / 'pb-link-chunks' / 'toc.html').read_text(encoding='utf-8')
    chunk_two_html = (tmp_path / 'pb-link-chunks' / '002.html').read_text(encoding='utf-8')

    # Resolved through the anchor index, with the pb-view wiring dropped.
    assert '<a href="002.html#b"' in toc_html
    assert 'xml-id=' not in toc_html
    assert 'emit=' not in toc_html
    # Inside the owning chunk the link collapses to a plain fragment.
    assert '<a href="#b"' in chunk_two_html
    # A pb-link with no resolvable target is left alone.
    assert '<pb-link path="other.xml">Other</pb-link>' in toc_html


def test_chunk_html_template_includes_odd_css(tmp_path: Path) -> None:
    """Chunk pages must receive ODD_GENERATED_CSS via the odd_css template variable."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    module_path.write_text(
        module_path.read_text(encoding='utf-8').replace(
            "ODD_GENERATED_CSS = ''",
            "ODD_GENERATED_CSS = '.tei-title { color: crimson; }'",
        ),
        encoding='utf-8',
    )
    _write_chunking_fixture_xml(xml_path)

    template = tmp_path / 'chunk.html.j2'
    template.write_text(
        '<html><head>{% if odd_css %}<style>{{ odd_css }}</style>{% endif %}</head>'
        '<body>{{ content_html | safe }}</body></html>',
        encoding='utf-8',
    )
    config = _chunking_config('css-chunks')
    config.template = Path('chunk.html.j2')

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='html',
    )

    html = (tmp_path / 'css-chunks' / '001.html').read_text(encoding='utf-8')
    assert '.tei-title { color: crimson; }' in html
    assert '<style>' in html


def test_link_pattern_includes_doc_subdirectory(tmp_path: Path) -> None:
    """link_pattern = '/{doc}/{file}' prefixes per-document output dirs."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    config = _chunking_config('lp-doc-chunks', link_pattern='/{doc}/{file}')
    config = replace(config, link_doc='quickstart.xml')
    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='json',
    )

    chunk_one = json.loads((tmp_path / 'lp-doc-chunks' / '001.json').read_text(encoding='utf-8'))
    assert 'href="#a"' in chunk_one['content']
    assert 'href="/quickstart.xml/002.html"' in chunk_one['content']
    toc = chunk_one['fragments']['toc']
    assert 'href="/quickstart.xml/002.html"' in toc


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

    assert part_a['id'] == 'a' and part_a['root'] is None and part_a['rootNode'] == 'a'
    assert part_a['next'] == 'b' and part_a['nextId'] == 'b'
    assert 'previous' not in part_a
    assert part_b['previous'] == 'a' and part_b['previousId'] == 'a'
    assert part_b['root'] is None and part_b['rootNode'] == 'b'
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


def test_pb_view_export_global_fragments(tmp_path: Path) -> None:
    """Global fragments (e.g. TOC) produce {name}.json/.html and index keys with user params."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    config = ChunkingConfig(
        xpath="//body/div[@type='chunk']",
        output_dir='pb-global',
        view='div',
        fragments=[
            FragmentConfig(
                name='toc',
                scope='global',
                xpath="//body/div[@type='toc']",
                parameters={'mode': 'toc'},
            ),
            FragmentConfig(
                name='title',
                scope='global',
                xpath="string(//body/div[@type='toc']/p/ref[1])",
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

    out = tmp_path / 'pb-global'
    toc = json.loads((out / 'toc.json').read_text(encoding='utf-8'))
    title = json.loads((out / 'title.json').read_text(encoding='utf-8'))
    toc_html = (out / 'toc.html').read_text(encoding='utf-8')
    title_html = (out / 'title.html').read_text(encoding='utf-8')

    assert 'class="toc"' in toc['content']
    assert 'href="#a"' in toc['content']
    assert 'href="#b"' in toc['content']
    # A single-root fragment keeps its shape: the .html sibling is the JSON
    # content verbatim.
    assert toc_html == toc['content']
    assert title['content'].strip() == 'A'
    # A text-only fragment has no root element of its own, so the XML copy is
    # wrapped; the JSON pb-view consumes stays bare text.
    assert title_html == '<div class="fragment fragment-title">A</div>'

    # Every .html export has to parse as XML — eXist-db stores them as XML
    # resources and rejects anything it cannot parse.
    for exported in sorted(out.glob('*.html')):
        etree.fromstring(exported.read_bytes())

    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
    toc_xpath = "//body/div[@type='toc']"
    assert index[f'odd=teipublisher.odd&user.mode=toc&view=div&xpath={toc_xpath}'] == 'toc.json'
    # Same TOC file resolves when a subscribed view re-fetches with root/id.
    assert index[f'odd=teipublisher.odd&root=a&user.mode=toc&view=div&xpath={toc_xpath}'] == 'toc.json'
    assert index[f'id=b&odd=teipublisher.odd&user.mode=toc&view=div&xpath={toc_xpath}'] == 'toc.json'
    title_xpath = "string(//body/div[@type='toc']/p/ref[1])"
    assert index[f'odd=teipublisher.odd&view=div&xpath={title_xpath}'] == 'title.json'


def test_chunk_document_pb_view_synthesizes_id_for_idless_chunks(tmp_path: Path) -> None:
    """Chunks without an xml:id get a stable synthetic id and still page correctly.

    pb-view navigates ``view="single"`` by echoing our previous/next values back as
    the ``root`` parameter, so a real xml:id is not required.
    """
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    # Select every div, including the <div type="toc"> that has no xml:id.
    config = ChunkingConfig(xpath="//body/div", output_dir='pb-view-mixed', view='div')

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='pb-view',
    )

    out = tmp_path / 'pb-view-mixed'

    # The id-less first chunk gets a synthetic id; the others keep their xml:id.
    assert (out / '_chunk1.json').is_file()
    part_toc = json.loads((out / '_chunk1.json').read_text(encoding='utf-8'))
    assert part_toc['id'] == '_chunk1' and part_toc['root'] is None and part_toc['rootNode'] == '_chunk1'
    assert part_toc['next'] == 'a' and part_toc['nextId'] == 'a' and 'previous' not in part_toc

    part_a = json.loads((out / 'a.json').read_text(encoding='utf-8'))
    assert part_a['previous'] == '_chunk1' and part_a['previousId'] == '_chunk1'
    assert part_a['next'] == 'b'

    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
    # Initial load (no id/root) resolves to the first chunk.
    assert index['odd=teipublisher.odd&view=div'] == '_chunk1.json'
    # Navigation by root resolves the synthetic and real ids alike.
    assert index['odd=teipublisher.odd&root=_chunk1&view=div'] == '_chunk1.json'
    assert index['odd=teipublisher.odd&root=a&view=div'] == 'a.json'


def test_web_div_with_n_preserves_xml_id(tmp_path: Path) -> None:
    """HTML output keeps ``@xml:id`` when the same element also has ``@n``."""
    from opm.odd_compiler import compile_odd
    from opm.runtime.pm_runtime import serialize

    odd = tmp_path / 'div_id.odd'
    odd.write_text(
        '''<?xml version="1.0"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc>
    <titleStmt><title>t</title></titleStmt>
    <publicationStmt><p>p</p></publicationStmt>
    <sourceDesc><p>s</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">
      <elementSpec ident="div" mode="change">
        <model behaviour="webcomponent">
          <param name="name" value="'section'"/>
        </model>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    module_path = tmp_path / 'div_id_web.py'
    module_path.write_text(compile_odd(str(odd)), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('div_id_web', str(module_path))
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
    assert 'id="I"' not in rendered


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


DOCBOOK_ODD = packaged_odd('docbook')


def test_docbook_per_chunk_breadcrumbs(tmp_path: Path) -> None:
    """Each DocBook section chunk gets a breadcrumb trail of ancestor titles.

    Ancestor crumbs are rewritten to the owning chunk file; the current
    section is unlinked.
    """
    from opm.odd_compiler import compile_odd

    module_path = tmp_path / 'docbook_web.py'
    module_path.write_text(compile_odd(str(DOCBOOK_ODD)), encoding='utf-8')

    xml_path = tmp_path / 'guide.xml'
    xml_path.write_text(
        """<article xmlns="http://docbook.org/ns/docbook" version="5.0">
  <info><title>Guide</title></info>
  <section xml:id="install">
    <title>Install</title>
    <para>Intro</para>
    <section xml:id="pip">
      <title>Using pip</title>
      <para>pip stuff</para>
    </section>
  </section>
  <section xml:id="usage">
    <title>Usage</title>
    <para>use it</para>
  </section>
</article>
""",
        encoding='utf-8',
    )

    config = ChunkingConfig(
        selector='opm.navigation.dbk_section_chunks',
        depth=2,
        output_dir='dbk-chunks',
        fragments=[
            FragmentConfig(
                name='breadcrumbs',
                scope='per-chunk',
                xpath='.',
                parameters={'mode': 'breadcrumb'},
            ),
        ],
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='json',
        xpath_extensions=('opm.runtime.common_xpath_functions',),
    )

    out = tmp_path / 'dbk-chunks'
    # depth=2: intro of "install", nested "pip", then "usage"
    pip = json.loads((out / '002.json').read_text(encoding='utf-8'))
    usage = json.loads((out / '003.json').read_text(encoding='utf-8'))

    intro = json.loads((out / '001.json').read_text(encoding='utf-8'))
    intro_crumbs = intro['fragments']['breadcrumbs']
    assert 'aria-label="breadcrumb"' in intro_crumbs
    assert 'Guide' in intro_crumbs
    assert 'Install' in intro_crumbs
    # Intro copy of a parent section: current crumb is unlinked
    assert 'href="#install"' not in intro_crumbs
    assert 'href="001.html#install"' not in intro_crumbs

    crumbs = pip['fragments']['breadcrumbs']
    assert 'aria-label="breadcrumb"' in crumbs
    assert 'Guide' in crumbs
    assert 'Install' in crumbs
    assert 'Using pip' in crumbs
    # Ancestor section links to the chunk that owns @xml:id="install"
    assert 'href="001.html#install"' in crumbs
    # Current page is not a link
    assert 'href="#pip"' not in crumbs
    assert 'href="002.html#pip"' not in crumbs

    usage_crumbs = usage['fragments']['breadcrumbs']
    assert 'Guide' in usage_crumbs
    assert 'Usage' in usage_crumbs
    assert 'href="#usage"' not in usage_crumbs
    assert 'href="003.html#usage"' not in usage_crumbs



def test_pb_view_export_per_chunk_breadcrumbs_xpath_dot(tmp_path: Path) -> None:
    """xpath='.' breadcrumbs are emitted for every chunk, not only the first.

    Keys omit xpath because the breadcrumb pb-view has no xpath attribute —
    only user.mode=breadcrumb — matching pb-view's static createKey().
    Part JSON leaves root null so subscribed dynamic views do not call the
    parts API with root=<xml:id>.
    """
    from opm.odd_compiler import compile_odd

    module_path = tmp_path / 'docbook_web.py'
    module_path.write_text(compile_odd(str(DOCBOOK_ODD)), encoding='utf-8')

    xml_path = tmp_path / 'guide.xml'
    xml_path.write_text(
        """<article xmlns="http://docbook.org/ns/docbook" version="5.0">
  <info><title>Guide</title></info>
  <section xml:id="install">
    <title>Install</title>
    <para>Intro</para>
    <section xml:id="pip">
      <title>Using pip</title>
      <para>pip stuff</para>
    </section>
  </section>
  <section xml:id="usage">
    <title>Usage</title>
    <para>use it</para>
  </section>
</article>
""",
        encoding='utf-8',
    )

    config = ChunkingConfig(
        selector='opm.navigation.dbk_section_chunks',
        depth=2,
        output_dir='pb-crumbs',
        view='div',
        fragments=[
            FragmentConfig(
                name='breadcrumbs',
                scope='per-chunk',
                xpath='.',
                parameters={'mode': 'breadcrumb'},
            ),
        ],
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='pb-view',
        xpath_extensions=('opm.runtime.common_xpath_functions',),
    )

    out = tmp_path / 'pb-crumbs'
    # depth=2 yields install intro, pip, usage — one breadcrumbs file each
    for xml_id in ('install', 'pip', 'usage'):
        path = out / f'breadcrumbs-{xml_id}.json'
        assert path.is_file(), xml_id
        part = json.loads(path.read_text(encoding='utf-8'))
        assert part['id'] == xml_id
        assert part['root'] is None
        assert part['rootNode'] == xml_id
        assert 'aria-label="breadcrumb"' in part['content']

    index = json.loads((out / 'index.json').read_text(encoding='utf-8'))
    # No xpath in keys — breadcrumb pb-view does not send xpath=.
    assert 'xpath=.' not in str(index)
    assert index['odd=docbook.odd&user.mode=breadcrumb&view=div'] == 'breadcrumbs-install.json'
    assert index['id=pip&odd=docbook.odd&user.mode=breadcrumb&view=div'] == 'breadcrumbs-pip.json'
    assert index['odd=docbook.odd&root=usage&user.mode=breadcrumb&view=div'] == 'breadcrumbs-usage.json'


def test_chapbook_running_head_uses_title_fragment(tmp_path: Path) -> None:
    """Chapbook running head shows a global title fragment, not the 'Chapbook' fallback."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'guide.xml'
    _write_chunking_fixture_module(module_path)
    xml_path.write_text(
        """<article xmlns="http://docbook.org/ns/docbook" version="5.0">
  <info><title>The Book of Tests</title></info>
  <section xml:id="one"><title>One</title><para>hello</para></section>
</article>
""",
        encoding='utf-8',
    )

    config = ChunkingConfig(
        xpath='//section',
        output_dir='title-chunks',
        template=_scaffold_template('chapbook.html.j2'),
        fragments=[
            FragmentConfig(
                name='title',
                scope='global',
                xpath='(/article/info/title, /book/info/title)[1]',
                parameters={'mode': 'title'},
            ),
        ],
    )
    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='html',
    )

    html = (tmp_path / 'title-chunks' / '001.html').read_text(encoding='utf-8')
    assert 'class="chap-running__work">The Book of Tests</span>' in html
    assert '<title>The Book of Tests</title>' in html
    assert 'class="chap-running__work">Chapbook</span>' not in html


def _write_manifest(out_dir: Path, name: str, *, chunks: int = 2, fragments: dict | None = None) -> None:
    """Write a minimal per-document manifest of the kind ``chunk`` produces."""
    doc_dir = out_dir / name
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'chunks': [
                    {'id': f'chunk-{i + 1:03d}', 'file': f'{i + 1:03d}.html', 'xpath': ''}
                    for i in range(chunks)
                ],
                'fragments': fragments or {},
                'anchors': {},
            }
        ),
        encoding='utf-8',
    )


def test_build_index_prefers_the_browse_fragment(tmp_path: Path) -> None:
    """A ``display='browse'`` record is emitted verbatim, links and all."""
    out = tmp_path / 'chunks'
    browse = '<h5><a class="tei-title" href="a.xml/001.html">Letter One</a></h5>'
    _write_manifest(out, 'a.xml', fragments={'browse': browse, 'title': '<span>ignored</span>'})

    index_file = build_index(out, title='Letters')
    assert index_file == out / 'index.html'
    html = index_file.read_text(encoding='utf-8')

    assert browse in html
    # The browse record already carries its own link, so the title fragment is
    # not used as well.
    assert 'ignored' not in html
    # A second link outside the record keeps the entry reachable regardless.
    assert '<a href="a.xml/001.html">a.xml</a>' in html
    assert '2 sections' in html


def test_build_index_falls_back_to_title_then_filename(tmp_path: Path) -> None:
    """Without a browse fragment the index degrades to the title, then the filename."""
    out = tmp_path / 'chunks'
    _write_manifest(out, 'has-title.xml', fragments={'title': '<span>A Gentle Guide</span>'})
    _write_manifest(out, 'no_fragments.xml', chunks=1, fragments={})

    html = build_index(out).read_text(encoding='utf-8')

    # Title fragment: wrapped in a link the ODD did not supply.
    assert '<h2><a href="has-title.xml/001.html"><span>A Gentle Guide</span></a></h2>' in html
    # Nothing at all: a readable label derived from the filename stem.
    assert '<h2><a href="no_fragments.xml/001.html">No fragments</a></h2>' in html
    assert '1 section' in html


def test_build_index_skips_directories_without_a_manifest(tmp_path: Path) -> None:
    """Stray directories (css/, images/) are not listed, and an empty run writes nothing."""
    out = tmp_path / 'chunks'
    out.mkdir()
    (out / 'css').mkdir()
    (out / 'css' / 'odd.css').write_text('body {}', encoding='utf-8')

    assert build_index(out) is None
    assert not (out / 'index.html').exists()

    _write_manifest(out, 'real.xml')
    html = build_index(out).read_text(encoding='utf-8')
    assert 'real.xml' in html
    assert 'odd.css' not in html


def test_collect_index_entries_reports_chunk_counts_and_hrefs(tmp_path: Path) -> None:
    out = tmp_path / 'chunks'
    _write_manifest(out, 'b.xml', chunks=3)
    _write_manifest(out, 'a.xml', chunks=1)

    entries = collect_index_entries(out)

    # Sorted by directory name, not manifest discovery order.
    assert [e.name for e in entries] == ['a.xml', 'b.xml']
    assert [e.href for e in entries] == ['a.xml/001.html', 'b.xml/001.html']
    assert [e.chunks for e in entries] == [1, 3]
    assert [e.label for e in entries] == ['A', 'B']


def test_global_fragments_receive_a_per_document_doc_parameter(tmp_path: Path) -> None:
    """``$parameters?doc`` defaults to the document entry point, and expands placeholders.

    The stock ODDs build browse links as ``<param name="uri" value="$parameters?doc"/>``,
    so each document in a directory run needs its own value.
    """
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    def _processor(config: ChunkingConfig) -> ChunkProcessor:
        return ChunkProcessor(
            module_path=module_path,
            xml_root=etree.parse(str(xml_path)).getroot(),
            config=config,
            project_root=tmp_path,
        )

    # Directory run: link_doc names the per-document subdirectory.
    proc = _processor(ChunkingConfig(xpath="//body/div[@type='chunk']", link_doc='fixture.xml'))
    assert proc.entry_href() == 'fixture.xml/001.html'
    assert proc._expand_document_params({})['doc'] == 'fixture.xml/001.html'

    # Single document: no prefix.
    single = _processor(ChunkingConfig(xpath="//body/div[@type='chunk']"))
    assert single.entry_href() == '001.html'
    assert single._expand_document_params({})['doc'] == '001.html'

    # An explicit value wins and gets {doc}/{stem}/{file} expanded.
    expanded = proc._expand_document_params({'doc': '/exist/apps/x/{doc}/{stem}'})
    assert expanded['doc'] == '/exist/apps/x/fixture.xml/001'

    # Values with unknown placeholders are left untouched rather than raising.
    assert proc._expand_document_params({'q': '{not-a-placeholder}'})['q'] == '{not-a-placeholder}'


def test_build_index_passes_the_stylesheet_to_the_template(tmp_path: Path) -> None:
    """An index template receives the same ODD stylesheet the chunk pages get.

    A browse record is ODD output, so the index needs the ODD's generated CSS
    to style its ``tei-*`` classes the way the document pages do.
    """
    out = tmp_path / 'chunks'
    _write_manifest(out, 'a.xml', fragments={'browse': '<span class="tei-title">T</span>'})

    template = tmp_path / 'index.html.j2'
    template.write_text(
        '<style>{{ odd_css }}</style>'
        '{% for doc in documents %}{{ doc.fragments.browse | safe }}{% endfor %}',
        encoding='utf-8',
    )

    html = build_index(
        out,
        template_path=template,
        odd_css='.tei-title { font-variant: small-caps; }',
    ).read_text(encoding='utf-8')

    assert '.tei-title { font-variant: small-caps; }' in html
    assert '<span class="tei-title">T</span>' in html


def test_build_index_reads_odd_css_from_the_transform_module(tmp_path: Path) -> None:
    """Without an explicit odd_css, the compiled module's stylesheet is used."""
    module_path = tmp_path / 'chunk_fixture.py'
    _write_chunking_fixture_module(module_path)
    module_path.write_text(
        module_path.read_text(encoding='utf-8').replace(
            "ODD_GENERATED_CSS = ''",
            "ODD_GENERATED_CSS = '.tei-title { color: rebeccapurple; }'",
        ),
        encoding='utf-8',
    )

    out = tmp_path / 'chunks'
    _write_manifest(out, 'a.xml')
    template = tmp_path / 'index.html.j2'
    template.write_text('<style>{{ odd_css }}</style>', encoding='utf-8')

    html = build_index(
        out, template_path=template, module_path=module_path
    ).read_text(encoding='utf-8')

    assert '.tei-title { color: rebeccapurple; }' in html


def _template_echoing_urls(path: Path) -> None:
    path.write_text(
        'ODD=[{{ odd_css_url }}] ASSETS=[{{ assets }}] STYLES=[{{ asset_styles|join(",") }}]\n'
        '{% if odd_css_url %}<link href="{{ odd_css_url }}">{% else %}<style>{{ odd_css }}</style>{% endif %}\n'
        '{{ content_html }}',
        encoding='utf-8',
    )


def test_no_stylesheets_written_when_there_are_none(tmp_path: Path) -> None:
    """No ODD CSS and no project CSS means no css/ directory and empty URLs.

    A project that sets no ``[transform] css`` has no second stylesheet at all —
    the rules every document needs live in the ODD stylesheet instead.
    """
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.j2'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)
    _template_echoing_urls(template)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(xpath="//body/div[@type='chunk']", output_dir='inline'),
        project_root=tmp_path,
        template_path=template,
    )

    page = (tmp_path / 'inline' / '001.html').read_text(encoding='utf-8')
    assert 'ODD=[] ASSETS=[] STYLES=[]' in page
    # No ODD stylesheet: the template's inline fallback is used instead.
    assert '<style></style>' in page
    assert not (tmp_path / 'inline' / 'css').exists()


def test_page_template_sees_the_documents_of_the_run(tmp_path: Path) -> None:
    """``documents`` lets a template link only to documents that were chunked."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.j2'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)
    template.write_text(
        "DOC=[{{ document }}] "
        "RUN=[{{ 'fixture.xml' in documents }}|{{ 'other.xml' in documents }}|"
        "{{ documents | length }}]",
        encoding='utf-8',
    )

    def _page(output_dir: str, **kwargs) -> str:
        chunk_document(
            module_path=module_path,
            xml_path=xml_path,
            config=ChunkingConfig(xpath="//body/div[@type='chunk']", output_dir=output_dir),
            project_root=tmp_path,
            template_path=template,
            **kwargs,
        )
        return (tmp_path / output_dir / '001.html').read_text(encoding='utf-8')

    # A single document knows only itself.
    assert 'DOC=[fixture.xml] RUN=[True|False|1]' in _page('single')
    # A directory run passes every file it chunks.
    run = frozenset({'fixture.xml', 'other.xml'})
    assert 'RUN=[True|True|2]' in _page('run', documents=run)


def test_chunking_always_writes_stylesheets_as_files(tmp_path: Path) -> None:
    """Chunk output is multi-page, so the stylesheet is a cacheable file, never inlined."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.j2'
    _write_chunking_fixture_module(module_path)
    module_path.write_text(
        module_path.read_text(encoding='utf-8').replace(
            "ODD_GENERATED_CSS = ''", "ODD_GENERATED_CSS = '.tei-p { margin: 0 }'"
        ),
        encoding='utf-8',
    )
    _write_chunking_fixture_xml(xml_path)
    _template_echoing_urls(template)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(
            xpath="//body/div[@type='chunk']", output_dir='ext'
        ),
        project_root=tmp_path,
        template_path=template,
    )

    out = tmp_path / 'ext'
    assert (out / 'css' / 'teipublisher.css').read_text(encoding='utf-8') == '.tei-p { margin: 0 }'
    page = (out / '001.html').read_text(encoding='utf-8')
    # Single document: the output dir is the root, so no ../ prefix.
    assert 'ODD=[css/teipublisher.css]' in page
    assert '<link href="css/teipublisher.css">' in page
    assert '<style>' not in page


def test_stylesheet_url_is_relative_to_the_shared_root(tmp_path: Path) -> None:
    """In a directory run the pages sit one level down, so URLs need ``../``."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.j2'
    _write_chunking_fixture_module(module_path)
    module_path.write_text(
        module_path.read_text(encoding='utf-8').replace(
            "ODD_GENERATED_CSS = ''", "ODD_GENERATED_CSS = '.tei-p { margin: 0 }'"
        ),
        encoding='utf-8',
    )
    _write_chunking_fixture_xml(xml_path)
    _template_echoing_urls(template)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(
            xpath="//body/div[@type='chunk']",
            output_dir='dir/fixture.xml',
            link_doc='fixture.xml',
        ),
        project_root=tmp_path,
        template_path=template,
    )

    # Written to the shared root, beside where the index would go — not into
    # the per-document subdirectory.
    assert (tmp_path / 'dir' / 'css' / 'teipublisher.css').is_file()
    assert not (tmp_path / 'dir' / 'fixture.xml' / 'css').exists()
    page = (tmp_path / 'dir' / 'fixture.xml' / '001.html').read_text(encoding='utf-8')
    assert 'ODD=[../css/teipublisher.css]' in page


def test_assets_are_copied_to_the_shared_root(tmp_path: Path) -> None:
    """Files and directories listed in chunking.assets land in assets/."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    template = tmp_path / 'page.html.j2'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)
    _template_echoing_urls(template)

    (tmp_path / 'style.css').write_text('body { margin: 0 }', encoding='utf-8')
    fonts = tmp_path / 'fonts'
    fonts.mkdir()
    (fonts / 'x.woff2').write_bytes(b'\x00\x01')

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(
            xpath="//body/div[@type='chunk']",
            output_dir='withassets',
            assets=(tmp_path / 'style.css', fonts),
        ),
        project_root=tmp_path,
        template_path=template,
    )

    out = tmp_path / 'withassets'
    assert (out / 'assets' / 'style.css').read_text(encoding='utf-8') == 'body { margin: 0 }'
    assert (out / 'assets' / 'fonts' / 'x.woff2').is_file()
    page = (out / '001.html').read_text(encoding='utf-8')
    assert 'ASSETS=[assets]' in page
    # Only entries explicitly listed as .css are linkable; the copied
    # fonts/ directory is not scanned.
    assert 'STYLES=[assets/style.css]' in page


def test_missing_asset_is_reported(tmp_path: Path) -> None:
    """A typo in chunking.assets fails loudly rather than producing a broken page."""
    import pytest

    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    with pytest.raises(FileNotFoundError, match='Asset not found'):
        chunk_document(
            module_path=module_path,
            xml_path=xml_path,
            config=ChunkingConfig(
                xpath="//body/div[@type='chunk']",
                output_dir='broken',
                assets=(tmp_path / 'nope.css',),
            ),
            project_root=tmp_path,
        )


def test_odd_stylesheet_carries_the_base_rules(tmp_path: Path) -> None:
    """The rules the runtime's markup needs ship inside css/<odd>.css.

    They describe what the output functions emit (``.alternate`` popovers,
    ``.tei-cb`` column breaks), not anything a project chose, so they have to
    reach every consumer of the ODD stylesheet — including ``--format pb-view``
    output loaded by a TEI Publisher app.
    """
    from opm.odd_cache import ensure_compiled_module
    from opm.resources import packaged_odd
    from opm.transform import load_transform_module as _load_module

    module_path, _ = ensure_compiled_module(packaged_odd('teipublisher'), output_mode='web')
    odd_css = getattr(_load_module(module_path), 'ODD_GENERATED_CSS', '')

    assert '.alternate .altcontent' in odd_css
    assert '.tei-cb:not([data-n="1"])' in odd_css
    # Base first, so an ODD's own outputRendition can override it.
    assert odd_css.index('.alternate') < odd_css.index('.tei-')


def test_document_css_overrides_the_base_rules(tmp_path: Path) -> None:
    """``[transform] css`` replaces the packaged base inside the ODD stylesheet.

    It is an override for the runtime's own rules, not an extra layer, so it
    lands ahead of the ODD's renditions and no second stylesheet is written.
    """
    from opm.odd_cache import ensure_compiled_module
    from opm.resources import packaged_odd
    from opm.transform import load_transform_module as _load_module

    custom = tmp_path / 'base.css'
    custom.write_text('.mine { color: rebeccapurple; }', encoding='utf-8')

    module_path, _ = ensure_compiled_module(
        packaged_odd('teipublisher'),
        output_mode='web',
        base_css=custom.read_text(encoding='utf-8'),
    )
    odd_css = getattr(_load_module(module_path), 'ODD_GENERATED_CSS', '')

    assert '.mine { color: rebeccapurple; }' in odd_css
    # The packaged rules it replaced are gone.
    assert '.alternate .altcontent' not in odd_css
    # Still ahead of the ODD's own renditions.
    assert odd_css.index('.mine') < odd_css.index('.tei-')


def test_base_css_override_gets_its_own_cached_module(tmp_path: Path) -> None:
    """Two projects with different base CSS must not share a compiled module."""
    from opm.odd_cache import cache_key
    from opm.resources import packaged_odd

    odd = packaged_odd('teipublisher')
    default = cache_key(odd, 'web')
    overridden = cache_key(odd, 'web', '.mine { color: red; }')

    assert default != overridden
    # Same input, same key — the cache still hits.
    assert overridden == cache_key(odd, 'web', '.mine { color: red; }')


def test_missing_document_css_is_reported(tmp_path: Path) -> None:
    """A typo in [transform] css fails loudly rather than dropping every base rule."""
    import pytest

    from opm.config import resolve_base_css

    with pytest.raises(FileNotFoundError, match='Stylesheet not found'):
        resolve_base_css(tmp_path / 'nope.css', tmp_path)


def test_chunk_document_applies_the_configured_base_override(tmp_path: Path) -> None:
    """Calling chunk_document as a library honours [transform] css, like the CLI does.

    The CLI pre-compiles via _materialize_chunking_modules; this covers the
    fallback path where chunk_document compiles config.odd itself.
    """
    from opm.resources import packaged_odd

    custom = tmp_path / 'base.css'
    custom.write_text('.libbase { color: teal; }', encoding='utf-8')
    xml_path = tmp_path / 'fixture.xml'
    xml_path.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        '<div><p>X</p></div></body></text></TEI>',
        encoding='utf-8',
    )

    chunk_document(
        module_path=None,
        xml_path=xml_path,
        config=ChunkingConfig(
            xpath='//text/body/div', output_dir='libbase', odd=packaged_odd('teipublisher')
        ),
        project_root=tmp_path,
        project_config=ProjectConfig(document_css=custom),
    )

    odd_css = (tmp_path / 'libbase' / 'css' / 'teipublisher.css').read_text(encoding='utf-8')
    assert '.libbase { color: teal; }' in odd_css
    assert '.alternate .altcontent' not in odd_css


def test_chunk_pages_and_index_receive_the_project_context(tmp_path: Path) -> None:
    """``[context]`` reaches chunk pages and the collection index alike."""
    from dataclasses import replace

    from opm.config import ProjectConfig

    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    template = tmp_path / 'page.html.j2'
    template.write_text(
        '<!doctype html><html><head><title>{{ context.site_name }}</title>'
        '{% if context.webcomponents_url %}<script src="{{ context.webcomponents_url }}"></script>'
        '{% endif %}</head><body>{{ content_html }}</body></html>',
        encoding='utf-8',
    )
    index_template = tmp_path / 'index.html.j2'
    index_template.write_text('<h1>{{ context.site_name }}</h1>', encoding='utf-8')

    project_config = ProjectConfig(
        template_context={'site_name': 'My Edition'},
        webcomponents_cdn='https://example.test/pb.js',
    )
    config = replace(
        _chunking_config('ctx-chunks'),
        template=template,
        index_template=index_template,
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        template_path=template,
        project_config=project_config,
        webcomponents=True,
        output_format='html',
    )

    page = (tmp_path / 'ctx-chunks' / '001.html').read_text(encoding='utf-8')
    assert '<title>My Edition</title>' in page
    assert '<script src="https://example.test/pb.js"></script>' in page

    # build_index scans the output root for per-document chunk directories.
    index_html = build_index(
        tmp_path,
        template_path=index_template,
        project_config=project_config,
    ).read_text(encoding='utf-8')
    assert '<h1>My Edition</h1>' in index_html


def test_link_pattern_doc_stem_drops_the_xml_suffix(tmp_path: Path) -> None:
    """``{doc_stem}`` is the document name a framework route wants — no ``.xml``."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    config = _chunking_config('lp-doc-stem', link_pattern='/letters/{doc_stem}/{stem}/')
    config = replace(config, link_doc='quickstart.xml')
    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=config,
        project_root=tmp_path,
        output_format='json',
    )

    chunk_one = json.loads((tmp_path / 'lp-doc-stem' / '001.json').read_text(encoding='utf-8'))
    assert 'href="/letters/quickstart/002/"' in chunk_one['content']
    assert '.xml' not in chunk_one['content']


def test_expand_document_params_supports_doc_stem(tmp_path: Path) -> None:
    """The browse link a stock ODD builds from ``$parameters?doc`` can be extensionless."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    proc = ChunkProcessor(
        module_path=module_path,
        xml_root=etree.parse(str(xml_path)).getroot(),
        config=ChunkingConfig(xpath="//body/div[@type='chunk']", link_doc='fixture.xml'),
        project_root=tmp_path,
    )

    expanded = proc._expand_document_params({'doc': '/letters/{doc_stem}/'})
    assert expanded['doc'] == '/letters/fixture/'


def test_chunk_metadata_records_the_chunk_root_xml_id(tmp_path: Path) -> None:
    """A consumer keys a page on the entry it renders, which the anchor map cannot say."""
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'fixture.xml'
    _write_chunking_fixture_module(module_path)
    _write_chunking_fixture_xml(xml_path)

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=_chunking_config('xml-id-chunks'),
        project_root=tmp_path,
        output_format='json',
    )

    out = tmp_path / 'xml-id-chunks'
    assert json.loads((out / '001.json').read_text(encoding='utf-8'))['xml_id'] == 'a'
    assert json.loads((out / '002.json').read_text(encoding='utf-8'))['xml_id'] == 'b'

    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert [c['xml_id'] for c in manifest['chunks']] == ['a', 'b']


def test_chunk_metadata_xml_id_is_none_without_one(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    xml_path = tmp_path / 'no_ids.xml'
    _write_chunking_fixture_module(module_path)
    xml_path.write_text(
        '<doc><body><div type="chunk"><p>one</p></div></body></doc>', encoding='utf-8'
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(xpath="//body/div[@type='chunk']", output_dir='no-id-chunks'),
        project_root=tmp_path,
        output_format='json',
    )

    chunk = json.loads((tmp_path / 'no-id-chunks' / '001.json').read_text(encoding='utf-8'))
    assert chunk['xml_id'] is None


def test_build_index_json_lists_documents(tmp_path: Path) -> None:
    """The JSON counterpart of build_index, for a consumer that renders its own index."""
    out = tmp_path / 'chunks'
    _write_manifest(out, 'b.xml', chunks=3, fragments={'browse': '<h5>B</h5>'})
    _write_manifest(out, 'a.xml', chunks=1)

    written = build_index_json(out, title='Listy')

    assert written == out / 'index.json'
    data = json.loads(written.read_text(encoding='utf-8'))
    assert data['title'] == 'Listy'
    assert [d['name'] for d in data['documents']] == ['a.xml', 'b.xml']
    assert [d['stem'] for d in data['documents']] == ['a', 'b']
    assert [d['chunks'] for d in data['documents']] == [1, 3]
    assert data['documents'][1]['fragments']['browse'] == '<h5>B</h5>'


def test_build_index_json_returns_none_without_documents(tmp_path: Path) -> None:
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert build_index_json(empty) is None
    assert not (empty / 'index.json').exists()


def test_wellformed_fragment_xml_wraps_only_what_needs_it() -> None:
    """A lone root element is left alone; anything else gains a wrapper."""
    single = '<div class="toc"><a href="#a">A</a></div>'
    assert _wellformed_fragment_xml(single, 'toc') == single
    # Surrounding whitespace does not count as a second root.
    assert _wellformed_fragment_xml(f'\n  {single}\n', 'toc') == single

    # ``display='browse'`` emits title, author and abstract as siblings.
    multi = _wellformed_fragment_xml('<h5>T</h5><div>A</div>', 'browse')
    assert multi == '<div class="fragment fragment-browse"><h5>T</h5><div>A</div></div>'

    # Text-only (a ``string()`` fragment xpath) and empty fragments have no root.
    assert _wellformed_fragment_xml('A', 'title') == '<div class="fragment fragment-title">A</div>'
    assert _wellformed_fragment_xml('', 'title') == '<div class="fragment fragment-title"></div>'


def test_wellformed_fragment_xml_closes_html_only_serialisations() -> None:
    """Void elements are closed and empty elements keep an explicit end tag."""
    # ``method='html'`` writes these open, which no XML parser accepts.
    assert _wellformed_fragment_xml('<p>a<br>b<img src="x.png">c</p>', 'f') == (
        '<p>a<br/>b<img src="x.png"/>c</p>'
    )
    # ``<span/>`` would read as an unclosed span to an HTML parser, swallowing
    # everything after it, so empty non-void elements keep both tags.
    assert _wellformed_fragment_xml('<div><span class="a"></span>t</div>', 'f') == (
        '<div><span class="a"></span>t</div>'
    )


def test_wellformed_fragment_xml_output_parses_as_xml() -> None:
    """Whatever the input shape, the result is parseable by an XML parser."""
    for fragment in (
        '<h5>T</h5><div>A</div>',
        'bare text <b>bold</b>',
        '<p>line<br>break</p>',
        '<p>Tom &amp; Jerry</p>',
        '<input type="checkbox" checked>',
        '',
    ):
        etree.fromstring(_wellformed_fragment_xml(fragment, 'f').encode('utf-8'))


def test_chunk_document_copies_referenced_images(tmp_path: Path) -> None:
    module_path = tmp_path / 'chunk_fixture.py'
    _write_chunking_fixture_module(module_path)
    src_dir = tmp_path / 'data'
    (src_dir / 'images').mkdir(parents=True)
    (src_dir / 'figs').mkdir()
    (src_dir / 'beside.png').write_bytes(b'beside')
    (src_dir / 'figs' / 'nested.png').write_bytes(b'nested')
    (src_dir / 'images' / 'fallback.png').write_bytes(b'fallback')
    (tmp_path / 'outside.png').write_bytes(b'outside')
    xml_path = src_dir / 'fixture.xml'
    xml_path.write_text(
        """<doc>
  <body>
    <div type="chunk" xml:id="a">
      <graphic url="beside.png"/>
      <graphic url="figs/nested.png"/>
      <graphic url="fallback.png"/>
      <graphic url="missing.png"/>
      <graphic url="https://example.com/remote.png"/>
      <graphic url="../outside.png"/>
    </div>
  </body>
</doc>
""",
        encoding='utf-8',
    )

    chunk_document(
        module_path=module_path,
        xml_path=xml_path,
        config=ChunkingConfig(xpath="//body/div[@type='chunk']", output_dir='out'),
        project_root=tmp_path,
    )

    out = tmp_path / 'out'
    assert (out / '001.html').is_file()
    assert (out / 'beside.png').read_bytes() == b'beside'
    assert (out / 'figs' / 'nested.png').read_bytes() == b'nested'
    assert (out / 'fallback.png').read_bytes() == b'fallback'
    assert not (out / 'missing.png').exists()
    assert sorted(p.name for p in out.rglob('*.png')) == ['beside.png', 'fallback.png', 'nested.png']
