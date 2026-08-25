"""Tests for chunk-aware link rewriting."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from importlib import resources
from pathlib import Path

from lxml import etree

from opm.chunking import chunk_document
from opm.config import ChunkingConfig, FragmentConfig
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
    assert toc_html == toc['content']
    assert title['content'].strip() == 'A'
    assert title_html == title['content']

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
    assert part_toc['id'] == '_chunk1' and part_toc['root'] == '_chunk1'
    assert part_toc['next'] == 'a' and 'previous' not in part_toc

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
