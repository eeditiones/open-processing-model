"""Tests for ``teipublisher_cli`` helpers."""

from __future__ import annotations

from pathlib import Path

from teipublisher.teipublisher_cli import _preview_kind_from_module
from teipublisher.teipublisher_cli import _resolve_user_css
from teipublisher.teipublisher_cli import main


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

    class EmptyChannels:
        @staticmethod
        def transform_output_channels():
            return []

    assert _preview_kind_from_module(MarkdownMod) == 'markdown'
    assert _preview_kind_from_module(WebMod) == 'html'
    assert _preview_kind_from_module(TupleMod) == 'markdown'
    assert _preview_kind_from_module(PrintMod) == 'text'
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
    assert '<!-- teipublisher-default-template -->' in rendered
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
    assert 'teipublisher-default-template' not in rendered


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


