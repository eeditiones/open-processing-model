"""Tests for ``cli`` helpers."""

from __future__ import annotations

import json
from pathlib import Path

from opm.cli import _preview_kind_from_module
from opm.cli import _resolve_user_css
from opm.cli import main
from tests.test_chunking import _write_chunking_fixture_module
from tests.test_chunking import _write_chunking_fixture_xml


def test_preview_kind_from_transform_output_channels() -> None:
    class MarkdownMod:
        @staticmethod
        def transform_output_channels():
            return ['markdown']

    class WebMod:
        @staticmethod
        def transform_output_channels():
            return ['web']

    class TupleMod:
        @staticmethod
        def transform_output_channels():
            return ('markdown',)

    class PrintMod:
        @staticmethod
        def transform_output_channels():
            return ['print']

    class TypstMod:
        @staticmethod
        def transform_output_channels():
            return ['typst']

    class EmptyChannels:
        @staticmethod
        def transform_output_channels():
            return []

    assert _preview_kind_from_module(MarkdownMod) == 'markdown'
    assert _preview_kind_from_module(WebMod) == 'html'
    assert _preview_kind_from_module(TupleMod) == 'markdown'
    assert _preview_kind_from_module(PrintMod) == 'text'
    assert _preview_kind_from_module(TypstMod) == 'typst'
    assert _preview_kind_from_module(EmptyChannels) == 'text'


def test_resolve_user_css_uses_default_if_present(tmp_path: Path, monkeypatch) -> None:
    styles = tmp_path / 'styles'
    styles.mkdir()
    css_file = styles / 'default-styles.css'
    css_file.write_text('.alternate { color: red; }', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    css = _resolve_user_css(None)
    assert css == '.alternate { color: red; }'


def test_resolve_user_css_none_if_default_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert _resolve_user_css(None) is None


def test_resolve_user_css_explicit_path_overrides_default(tmp_path: Path, monkeypatch) -> None:
    styles = tmp_path / 'styles'
    styles.mkdir()
    (styles / 'default-styles.css').write_text('default', encoding='utf-8')
    custom = tmp_path / 'custom.css'
    custom.write_text('custom', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert _resolve_user_css(custom) == 'custom'


def test_transform_uses_packaged_default_template_for_full_html(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / 'transform_mod.py'
    script.write_text(
        "from lxml import etree\n"
        "def transform_output_channels():\n"
        "    return ['web']\n"
        "ODD_GENERATED_CSS = '.odd { color: blue; }'\n"
        "def transform(root, options=None):\n"
        "    _ = root, options\n"
        "    html = etree.Element('html')\n"
        "    head = etree.SubElement(html, 'head')\n"
        "    title = etree.SubElement(head, 'title')\n"
        "    title.text = 'T'\n"
        "    body = etree.SubElement(html, 'body')\n"
        "    p = etree.SubElement(body, 'p')\n"
        "    p.text = 'content'\n"
        "    return [html]\n",
        encoding='utf-8',
    )
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc/>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '--module', str(script), '--output', str(out)])
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert '<!-- opm-default-template -->' in rendered
    assert '<p>content</p>' in rendered


def test_transform_uses_template_override_for_full_html(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / 'transform_mod.py'
    script.write_text(
        "from lxml import etree\n"
        "def transform_output_channels():\n"
        "    return ['web']\n"
        "ODD_GENERATED_CSS = ''\n"
        "def transform(root, options=None):\n"
        "    _ = root, options\n"
        "    html = etree.Element('html')\n"
        "    etree.SubElement(html, 'head')\n"
        "    body = etree.SubElement(html, 'body')\n"
        "    div = etree.SubElement(body, 'div')\n"
        "    div.text = 'X'\n"
        "    return [html]\n",
        encoding='utf-8',
    )
    template = tmp_path / 'custom.j2'
    template.write_text(
        "<html><head><meta name='x' content='y'></head><body>{{ content_html|safe }}</body></html>",
        encoding='utf-8',
    )
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc/>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '--module', str(script), '--template', str(template), '--output', str(out)])
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert "name='x'" in rendered
    assert '<div>X</div>' in rendered
    assert 'opm-default-template' not in rendered


def test_transform_fragment_output_skips_template_shell(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / 'transform_mod.py'
    script.write_text(
        "from lxml import etree\n"
        "def transform_output_channels():\n"
        "    return ['web']\n"
        "def transform(root, options=None):\n"
        "    _ = options\n"
        "    p = etree.Element('p')\n"
        "    p.text = root.tag\n"
        "    return [p]\n",
        encoding='utf-8',
    )
    template = tmp_path / 'custom.j2'
    template.write_text("<html><body>WRAP {{ content_html|safe }}</body></html>", encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><item>ok</item></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(
        ['transform', str(xml), '--module', str(script), '--xpath', '/doc/item', '--template', str(template), '--output', str(out)],
    )
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert rendered == '<p>item</p>'


def test_chunk_directory_pb_view_appends_xml_filename_to_doc_path(tmp_path: Path, monkeypatch) -> None:
    _write_chunking_fixture_module(tmp_path / 'chunk_fixture.py')
    docs = tmp_path / 'docs'
    docs.mkdir()
    _write_chunking_fixture_xml(docs / 'one.xml')
    _write_chunking_fixture_xml(docs / 'two.xml')
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
module = "chunk_fixture.py"
xpath = "//body/div[@type='chunk']"
output_dir = "site"
view = "div"
doc_path = "letters"
""",
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)

    rc = main(['chunk', 'docs', '--format', 'pb-view', '-c', 'opm.toml'])

    assert rc == 0
    site = tmp_path / 'site'
    assert (site / 'letters' / 'one.xml' / 'index.json').is_file()
    assert (site / 'letters' / 'one.xml' / 'a.json').is_file()
    assert (site / 'letters' / 'two.xml' / 'index.json').is_file()
    assert (site / 'letters' / 'two.xml' / 'b.json').is_file()
    assert (site / 'css' / 'teipublisher.css').is_file()

    one_index = json.loads((site / 'letters' / 'one.xml' / 'index.json').read_text(encoding='utf-8'))
    two_index = json.loads((site / 'letters' / 'two.xml' / 'index.json').read_text(encoding='utf-8'))
    assert one_index['odd=teipublisher.odd&view=div'] == 'a.json'
    assert two_index['odd=teipublisher.odd&view=div'] == 'a.json'


def test_chunk_directory_json_writes_each_document_to_own_directory(tmp_path: Path, monkeypatch) -> None:
    _write_chunking_fixture_module(tmp_path / 'chunk_fixture.py')
    docs = tmp_path / 'docs'
    docs.mkdir()
    _write_chunking_fixture_xml(docs / 'one.xml')
    _write_chunking_fixture_xml(docs / 'two.xml')
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
module = "chunk_fixture.py"
xpath = "//body/div[@type='chunk']"
output_dir = "json-site"
""",
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)

    rc = main(['chunk', 'docs', '--format', 'json', '-c', 'opm.toml'])

    assert rc == 0
    site = tmp_path / 'json-site'
    assert (site / 'one.xml' / 'manifest.json').is_file()
    assert (site / 'one.xml' / '001.json').is_file()
    assert (site / 'two.xml' / 'manifest.json').is_file()
    assert (site / 'two.xml' / '002.json').is_file()

    one_chunk = json.loads((site / 'one.xml' / '001.json').read_text(encoding='utf-8'))
    two_manifest = json.loads((site / 'two.xml' / 'manifest.json').read_text(encoding='utf-8'))
    assert 'id="a"' in one_chunk['content']
    assert two_manifest['anchors'] == {'a': '001.html', 'b': '002.html'}


