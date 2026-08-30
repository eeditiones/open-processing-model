"""Tests for ``cli`` helpers."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from opm.cli import _preview_kind_from_module
from opm.cli import _prepare_chunk_output_dir
from opm.config import resolve_base_css
from opm.cli import main
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
    assert _preview_kind_from_module(PrintMod) == 'html'
    assert _preview_kind_from_module(TypstMod) == 'typst'
    assert _preview_kind_from_module(EmptyChannels) == 'text'


def test_resolve_base_css_uses_local_styles_if_present(tmp_path: Path, monkeypatch) -> None:
    """A project's own styles/default-styles.css replaces the packaged base."""
    styles = tmp_path / 'styles'
    styles.mkdir()
    (styles / 'default-styles.css').write_text('.alternate { color: red; }', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert resolve_base_css(None, Path.cwd()) == '.alternate { color: red; }'


def test_resolve_base_css_falls_back_to_packaged(tmp_path: Path, monkeypatch) -> None:
    """With nothing configured, the packaged rules are the base."""
    from opm.odd_compiler.css_generator import default_base_css

    monkeypatch.chdir(tmp_path)
    assert resolve_base_css(None, Path.cwd()) == default_base_css()


def test_resolve_base_css_explicit_path_overrides_default(tmp_path: Path, monkeypatch) -> None:
    styles = tmp_path / 'styles'
    styles.mkdir()
    (styles / 'default-styles.css').write_text('default', encoding='utf-8')
    custom = tmp_path / 'custom.css'
    custom.write_text('custom', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert resolve_base_css(custom, Path.cwd()) == 'custom'


def _write_tiny_odd(path: Path, *, ident: str = 'teipublisher') -> Path:
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        f'<schemaSpec ident="{ident}" ns="">'
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="div"><model behaviour="block"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
        '<elementSpec ident="ref"><model behaviour="link"/></elementSpec>'
        '<elementSpec ident="body"><model behaviour="block"/></elementSpec>'
        '<elementSpec ident="text"><model behaviour="block"/></elementSpec>'
        '<elementSpec ident="item"><model behaviour="inline"/></elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    return path


def _config_with_odd(tmp_path: Path, odd_name: str = 'tiny.odd') -> Path:
    """Write a minimal opm.toml that selects *odd_name* for web transforms."""
    path = tmp_path / 'opm.toml'
    path.write_text(f'[transform.web]\nodd = "{odd_name}"\n', encoding='utf-8')
    return path


def test_transform_uses_packaged_default_template_for_full_html(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'tiny.odd')
    _config_with_odd(tmp_path)
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><p>content</p></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '-c', 'opm.toml', '--output', str(out)])
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert '<!-- opm-default-template -->' in rendered
    assert '<p' in rendered
    assert 'content' in rendered


def test_transform_uses_template_override_for_full_html(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'tiny.odd')
    _config_with_odd(tmp_path)
    template = tmp_path / 'custom.j2'
    template.write_text(
        "<html><head><meta name='x' content='y'></head><body>{{ content_html|safe }}</body></html>",
        encoding='utf-8',
    )
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><p>X</p></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(
        ['transform', str(xml), '-c', 'opm.toml', '--template', str(template), '--output', str(out)],
    )
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert "name='x'" in rendered
    assert '<p' in rendered
    assert 'X' in rendered
    assert 'opm-default-template' not in rendered


def test_transform_fragment_output_skips_template_shell(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'tiny.odd')
    _config_with_odd(tmp_path)
    template = tmp_path / 'custom.j2'
    template.write_text("<html><body>WRAP {{ content_html|safe }}</body></html>", encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><item>ok</item></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    monkeypatch.chdir(tmp_path)

    rc = main(
        [
            'transform', str(xml), '-c', 'opm.toml',
            '--xpath', '/doc/item', '--template', str(template), '--output', str(out),
        ],
    )
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert 'WRAP' not in rendered
    assert 'ok' in rendered
    assert rendered.startswith('<')


def test_load_project_config_reads_per_type_odds(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "web.odd"

[transform.docx]
odd = "docx.odd"
template = "style.docx"

[transform.typst]
odd = "typst.odd"
template = "book.typ.j2"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.transform_odd == tmp_path / 'web.odd'
    assert cfg.odd_for_type('web') == tmp_path / 'web.odd'
    assert cfg.odd_for_type('docx') == tmp_path / 'docx.odd'
    assert cfg.odd_for_type('typst') == tmp_path / 'typst.odd'
    assert cfg.odd_for_type('markdown') == tmp_path / 'web.odd'  # falls back to web-as-default
    assert cfg.document_docx_template == tmp_path / 'style.docx'
    assert cfg.typst_template == tmp_path / 'book.typ.j2'


def test_load_project_config_print_template(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform]
odd = "shared.odd"

[transform.print]
template = "templates/print.html.j2"

[document]
template = "templates/web.html.j2"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.print_template == tmp_path / 'templates' / 'print.html.j2'
    assert cfg.document_template == tmp_path / 'templates' / 'web.html.j2'
    assert cfg.print_template != cfg.document_template


def test_load_project_config_shared_transform_odd(tmp_path: Path) -> None:
    """``[transform].odd`` is the default; per-type tables may override."""
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform]
odd = "shared.odd"

[transform.typst]
odd = "typst-only.odd"
template = "book.typ.j2"

[chunking]
xpath = "//div"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.transform_odd == tmp_path / 'shared.odd'
    assert cfg.odd_for_type('web') == tmp_path / 'shared.odd'
    assert cfg.odd_for_type('docx') == tmp_path / 'shared.odd'
    assert cfg.odd_for_type('markdown') == tmp_path / 'shared.odd'
    assert cfg.odd_for_type('typst') == tmp_path / 'typst-only.odd'
    assert cfg.chunking is not None
    assert cfg.chunking.odd == tmp_path / 'shared.odd'


def test_load_project_config_resolves_document_and_chunking_paths(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[document]
template = "templates/page.html.j2"
css = "styles/site.css"

[chunking]
template = "templates/chunk.html.j2"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.document_template == tmp_path / 'templates' / 'page.html.j2'
    assert cfg.document_css == tmp_path / 'styles' / 'site.css'
    assert cfg.chunking is not None
    assert cfg.chunking.template == tmp_path / 'templates' / 'chunk.html.j2'


def test_transform_config_paths_resolve_relative_to_config_file(tmp_path: Path, monkeypatch) -> None:
    """Running from an unrelated CWD with -c must find template and CSS next to the config."""
    project = tmp_path / 'project'
    (project / 'templates').mkdir(parents=True)
    _write_tiny_odd(project / 'tiny.odd')
    # [document] css is the base override, so it arrives compiled into odd_css.
    (project / 'templates' / 'custom.j2').write_text(
        '<html><head><!-- config-relative-template -->{{ head_html|safe }}'
        '<style>{{ odd_css }}</style></head>'
        '<body>{{ content_html|safe }}</body></html>',
        encoding='utf-8',
    )
    (project / 'site.css').write_text('.site { color: green; }', encoding='utf-8')
    (project / 'opm.toml').write_text(
        """[transform.web]
odd = "tiny.odd"

[document]
template = "templates/custom.j2"
css = "site.css"
""",
        encoding='utf-8',
    )
    xml = project / 'in.xml'
    xml.write_text('<doc><p>X</p></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'

    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    rc = main(['transform', str(xml), '-c', str(project / 'opm.toml'), '--output', str(out)])
    assert rc == 0
    rendered = out.read_text(encoding='utf-8')
    assert 'config-relative-template' in rendered
    assert '.site { color: green; }' in rendered
    assert 'X' in rendered


def test_load_project_config_reads_webcomponents_under_transform_web(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "web.odd"

[transform.web.webcomponents]
enabled = true
cdn = "https://example.test/pb.js"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.webcomponents_enabled is True
    assert cfg.webcomponents_cdn == 'https://example.test/pb.js'


def test_load_project_config_reads_template_context(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[context]
site_name = "My Edition"
show_downloads = true
issues = 3
nav = [ { label = "Home", url = "/" } ]
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    # TOML types survive: templates read these, XPath never does.
    assert cfg.template_context == {
        'site_name': 'My Edition',
        'show_downloads': True,
        'issues': 3,
        'nav': [{'label': 'Home', 'url': '/'}],
    }
    assert cfg.context_for('web') == cfg.template_context


def test_context_for_overlays_the_per_type_table(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[context]
site_name = "My Edition"
show_downloads = true

[transform.typst.context]
site_name = "My Edition (print)"
paper = "a5"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.context_for('typst') == {
        'site_name': 'My Edition (print)',
        'show_downloads': True,
        'paper': 'a5',
    }
    # The overlay is scoped to its own output type.
    assert cfg.context_for('web') == {
        'site_name': 'My Edition',
        'show_downloads': True,
    }


def test_context_for_derives_webcomponents_url(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web.webcomponents]
enabled = true
cdn = "https://example.test/pb-{version}.js"
version = "1.2.3"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert 'webcomponents_url' not in cfg.context_for('web')
    assert cfg.context_for('web', webcomponents=True)['webcomponents_url'] == (
        'https://example.test/pb-1.2.3.js'
    )


def test_explicit_context_wins_over_the_derived_webcomponents_url(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[context]
webcomponents_url = "/local/pb-components-bundle.js"

[transform.web.webcomponents]
enabled = true
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    ctx = cfg.context_for('web', webcomponents=True)
    assert ctx['webcomponents_url'] == '/local/pb-components-bundle.js'


def test_load_project_config_rejects_a_non_table_context(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text('context = "nope"\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'\[context\] must be a table'):
        load_project_config(tmp_path / 'opm.toml')


def test_load_project_config_ignores_legacy_top_level_webcomponents(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "web.odd"

[webcomponents]
enabled = true
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.webcomponents_enabled is None


def test_load_project_config_accepts_legacy_top_level_type_sections(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "web.odd"

[docx]
odd = "docx.odd"
template = "style.docx"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.odd_for_type('docx') == tmp_path / 'docx.odd'
    assert cfg.document_docx_template == tmp_path / 'style.docx'


def test_transform_type_selects_odd_from_config(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_tiny_odd(tmp_path / 'tiny.odd')
    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "tiny.odd"

[transform.typst]
odd = "tiny.odd"
""",
        encoding='utf-8',
    )
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><p>hi</p></doc>', encoding='utf-8')
    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '-c', 'opm.toml', '-t', 'typst', '-o', str(tmp_path / 'out.typ')])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'typst' in err

    rc = main(['transform', str(xml), '-c', 'opm.toml', '--type', 'web', '-o', str(tmp_path / 'out.html')])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'web' in err


def test_transform_type_missing_odd_uses_packaged_odd(tmp_path: Path, monkeypatch, capsys) -> None:
    """When --type has no config entry, fall back to the packaged stock ODD."""
    _write_tiny_odd(tmp_path / 'tiny.odd')
    (tmp_path / 'opm.toml').write_text('[transform.web]\nodd = "tiny.odd"\n', encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc/>', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '-c', 'opm.toml', '-t', 'markdown', '-o', str(tmp_path / 'out.md')])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'Cached module:' in err or 'Compiled ' in err
    assert (tmp_path / 'out.md').is_file()


def test_transform_odd_compiles_into_cache(tmp_path: Path, monkeypatch, capsys) -> None:
    odd = tmp_path / 'tiny.odd'
    odd.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>
  <publicationStmt><p/></publicationStmt>
  <sourceDesc><p/></sourceDesc></fileDesc></teiHeader>
  <text><body>
    <schemaSpec ident="tiny" start="doc">
      <elementSpec ident="doc">
        <model behaviour="document"/>
      </elementSpec>
      <elementSpec ident="p">
        <model behaviour="paragraph"/>
      </elementSpec>
    </schemaSpec>
  </body></text>
</TEI>
''',
        encoding='utf-8',
    )
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc xmlns="http://www.tei-c.org/ns/1.0"><p>hi</p></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    cache = tmp_path / 'cache'
    monkeypatch.setenv('XDG_CACHE_HOME', str(cache))
    # platformdirs on macOS ignores XDG_CACHE_HOME; redirect modules_cache_dir instead.
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '-d', str(odd), '--output', str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'Compiled ' in err
    assert str(cache / 'modules') in err or 'tiny-web-' in err
    assert out.is_file()

    rc = main(['transform', str(xml), '-d', str(odd), '--output', str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'Cached module:' in err


def test_load_project_config_reads_odd_paths(tmp_path: Path) -> None:
    from opm.config import load_project_config

    (tmp_path / 'opm.toml').write_text(
        """[transform.web]
odd = "odd/web.odd"

[transform.docx]
odd = "odd/docx.odd"

[chunking]
odd = "odd/chunk.odd"

[[chunking.fragments]]
name = "notes"
scope = "per-chunk"
xpath = ".//note"
odd = "odd/notes.odd"
mode = "markdown"
""",
        encoding='utf-8',
    )
    cfg = load_project_config(tmp_path / 'opm.toml')
    assert cfg.transform_odd == tmp_path / 'odd' / 'web.odd'
    assert cfg.odd_for_type('docx') == tmp_path / 'odd' / 'docx.odd'
    assert cfg.chunking is not None
    assert cfg.chunking.odd == tmp_path / 'odd' / 'chunk.odd'
    assert cfg.chunking.fragments is not None
    assert cfg.chunking.fragments[0].odd == tmp_path / 'odd' / 'notes.odd'
    assert cfg.chunking.fragments[0].mode == 'markdown'
    assert cfg.chunking.module is None
    assert cfg.chunking.fragments[0].module is None


def test_transform_odd_overrides_config_odd(tmp_path: Path, monkeypatch, capsys) -> None:
    config_odd = tmp_path / 'config.odd'
    _write_tiny_odd(config_odd, ident='config-odd')
    cli_odd = tmp_path / 'cli.odd'
    _write_tiny_odd(cli_odd, ident='cli-odd')
    (tmp_path / 'opm.toml').write_text('[transform.web]\nodd = "config.odd"\n', encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc><p>hi</p></doc>', encoding='utf-8')
    out = tmp_path / 'out.html'
    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.chdir(tmp_path)

    rc = main(['transform', str(xml), '-c', 'opm.toml', '-d', str(cli_odd), '--output', str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'Compiled ' in err or 'Cached module:' in err
    assert 'cli-odd' in err or 'cli-' in err
    assert out.is_file()


def test_chunk_directory_pb_view_appends_xml_filename_to_doc_path(tmp_path: Path, monkeypatch) -> None:
    # File stem becomes ODD_NAME → css/teipublisher.css and odd=teipublisher.odd keys.
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    docs = tmp_path / 'docs'
    docs.mkdir()
    _write_chunking_fixture_xml(docs / 'one.xml')
    _write_chunking_fixture_xml(docs / 'two.xml')
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
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
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    docs = tmp_path / 'docs'
    docs.mkdir()
    _write_chunking_fixture_xml(docs / 'one.xml')
    _write_chunking_fixture_xml(docs / 'two.xml')
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
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
    assert 'self' in one_chunk['content']
    assert two_manifest['anchors'] == {'a': '001.html', 'b': '002.html'}


def test_chunk_directory_html_writes_each_document_to_own_directory(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    docs = tmp_path / 'docs'
    docs.mkdir()
    _write_chunking_fixture_xml(docs / 'one.xml')
    _write_chunking_fixture_xml(docs / 'two.xml')
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
xpath = "//body/div[@type='chunk']"
output_dir = "html-site"
""",
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)

    rc = main(['chunk', 'docs', '--format', 'html', '-c', 'opm.toml'])

    assert rc == 0
    site = tmp_path / 'html-site'
    assert (site / 'one.xml' / 'manifest.json').is_file()
    assert (site / 'one.xml' / '001.html').is_file()
    assert (site / 'two.xml' / 'manifest.json').is_file()
    assert (site / 'two.xml' / '002.html').is_file()

    one_html = (site / 'one.xml' / '001.html').read_text(encoding='utf-8')
    two_manifest = json.loads((site / 'two.xml' / 'manifest.json').read_text(encoding='utf-8'))
    assert 'self' in one_html
    assert two_manifest['anchors'] == {'a': '001.html', 'b': '002.html'}


def test_prepare_chunk_output_dir_noop_if_missing(tmp_path: Path) -> None:
    out = tmp_path / 'chunks'
    _prepare_chunk_output_dir(out, force=False)
    assert not out.exists()


def test_prepare_chunk_output_dir_force_removes_tree(tmp_path: Path) -> None:
    out = tmp_path / 'chunks'
    nested = out / 'nested'
    nested.mkdir(parents=True)
    leftover = nested / 'stale.html'
    leftover.write_text('old', encoding='utf-8')
    _prepare_chunk_output_dir(out, force=True)
    assert not out.exists()


def test_prepare_chunk_output_dir_force_removes_file(tmp_path: Path) -> None:
    out = tmp_path / 'chunks'
    out.write_text('not a directory', encoding='utf-8')
    _prepare_chunk_output_dir(out, force=True)
    assert not out.exists()


def test_prepare_chunk_output_dir_errors_when_not_tty(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    out = tmp_path / 'chunks'
    out.mkdir()
    leftover = out / 'stale.html'
    leftover.write_text('old', encoding='utf-8')
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    with pytest.raises(SystemExit) as exc:
        _prepare_chunk_output_dir(out, force=False)
    assert exc.value.code == 1
    assert leftover.is_file()
    err = capsys.readouterr().err
    assert 'already exists' in err
    assert '--force' in err


def test_prepare_chunk_output_dir_confirm_yes_removes(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / 'chunks'
    out.mkdir()
    leftover = out / 'stale.html'
    leftover.write_text('old', encoding='utf-8')
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('opm.cli.typer.confirm', lambda *a, **k: True)
    _prepare_chunk_output_dir(out, force=False)
    assert not out.exists()


def test_prepare_chunk_output_dir_confirm_no_keeps(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / 'chunks'
    out.mkdir()
    leftover = out / 'stale.html'
    leftover.write_text('old', encoding='utf-8')
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('opm.cli.typer.confirm', lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        _prepare_chunk_output_dir(out, force=False)
    assert exc.value.code == 1
    assert leftover.is_file()


def test_chunk_force_removes_stale_files(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    xml = tmp_path / 'doc.xml'
    _write_chunking_fixture_xml(xml)
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
xpath = "//body/div[@type='chunk']"
output_dir = "chunks"
""",
        encoding='utf-8',
    )
    stale = tmp_path / 'chunks'
    stale.mkdir()
    leftover = stale / 'stale.html'
    leftover.write_text('old', encoding='utf-8')
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: tmp_path / 'cache' / 'modules')
    monkeypatch.chdir(tmp_path)

    rc = main(['chunk', 'doc.xml', '--force', '-c', 'opm.toml'])

    assert rc == 0
    assert not leftover.exists()
    assert (tmp_path / 'chunks' / 'manifest.json').is_file()


def test_chunk_preview_starts_serve(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    xml = tmp_path / 'doc.xml'
    _write_chunking_fixture_xml(xml)
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
xpath = "//body/div[@type='chunk']"
output_dir = "chunks"
""",
        encoding='utf-8',
    )
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: tmp_path / 'cache' / 'modules')
    monkeypatch.chdir(tmp_path)

    called: list[tuple[Path, int]] = []

    def _fake_serve(root: Path, port: int) -> None:
        called.append((root, port))

    monkeypatch.setattr('opm.cli._serve_directory', _fake_serve)

    rc = main(['chunk', 'doc.xml', '--force', '--preview', '-p', '9090', '-c', 'opm.toml'])

    assert rc == 0
    assert len(called) == 1
    assert called[0][0] == (tmp_path / 'chunks')
    assert called[0][1] == 9090
    assert (tmp_path / 'chunks' / 'manifest.json').is_file()


def test_chunk_depth_overrides_config(tmp_path: Path, monkeypatch) -> None:
    _write_tiny_odd(tmp_path / 'teipublisher.odd')
    xml = tmp_path / 'doc.xml'
    _write_chunking_fixture_xml(xml)
    (tmp_path / 'opm.toml').write_text(
        """[chunking]
odd = "teipublisher.odd"
xpath = "//body/div[@type='chunk']"
depth = 2
output_dir = "chunks"
""",
        encoding='utf-8',
    )
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: tmp_path / 'cache' / 'modules')
    monkeypatch.chdir(tmp_path)

    seen: list[int] = []

    def _fake_chunk_document(**kwargs):
        seen.append(kwargs['config'].depth)
        out = Path.cwd() / kwargs['config'].output_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / 'manifest.json').write_text('{"chunks":[]}', encoding='utf-8')

    monkeypatch.setattr('opm.cli.chunk_document', _fake_chunk_document)

    rc = main(['chunk', 'doc.xml', '--depth', '1', '-c', 'opm.toml'])

    assert rc == 0
    assert seen == [1]


def test_bind_http_server_skips_busy_port() -> None:
    import http.server

    from opm.cli import _bind_http_server

    handler = http.server.SimpleHTTPRequestHandler
    occupied, occupied_port = _bind_http_server(handler, 0)
    try:
        httpd, chosen = _bind_http_server(handler, occupied_port)
        try:
            assert chosen != occupied_port
        finally:
            httpd.server_close()
    finally:
        occupied.server_close()


def test_init_tei_creates_project(tmp_path: Path) -> None:
    from opm.config import load_project_config

    dest = tmp_path / 'edition'
    rc = main(['init', str(dest), '--title', 'Test Edition'])
    assert rc == 0
    assert (dest / 'opm.toml').is_file()
    assert (dest / 'odd' / 'custom.odd').is_file()
    assert not (dest / 'odd' / 'teipublisher.odd').exists()
    assert (dest / 'templates' / 'chapbook.html.j2').is_file()
    assert (dest / 'templates' / 'chapbook.css').is_file()
    assert (dest / 'templates' / 'journal.html.j2').is_file()
    assert (dest / 'templates' / 'journal.css').is_file()
    assert (dest / 'templates' / 'book.typ.j2').is_file()
    assert (dest / 'templates' / 'default.docx').is_file()
    # The base rules ship inside the ODD stylesheet, so no copy is scaffolded.
    assert not (dest / 'styles' / 'default-styles.css').exists()
    assert (dest / 'data' / 'sample.xml').is_file()
    assert (dest / 'extensions' / '__init__.py').is_file()
    assert (dest / 'AGENTS.md').is_file()
    assert (dest / 'CLAUDE.md').is_file()
    agents = (dest / 'AGENTS.md').read_text(encoding='utf-8')
    assert 'opm transform' in agents
    assert 'odd/custom.odd' in agents
    assert 'Claude Code' in (dest / 'CLAUDE.md').read_text(encoding='utf-8')
    cfg = load_project_config(dest / 'opm.toml')
    assert cfg.document_template is not None
    assert cfg.document_template.name == 'chapbook.html.j2'
    assert cfg.chunking is not None
    assert cfg.chunking.selector == 'opm.navigation.tei_div_chunks'
    assert cfg.transform_odd is not None
    assert cfg.transform_odd.name == 'custom.odd'
    assert cfg.document_docx_template is not None
    assert cfg.typst_template is not None
    assert 'Test Edition' in (dest / 'README.md').read_text(encoding='utf-8')


def test_init_preserves_existing_agent_files(tmp_path: Path) -> None:
    dest = tmp_path / 'edition'
    dest.mkdir()
    (dest / 'AGENTS.md').write_text('custom-agents', encoding='utf-8')
    (dest / 'CLAUDE.md').write_text('custom-claude', encoding='utf-8')
    assert main(['init', str(dest)]) == 0
    assert (dest / 'AGENTS.md').read_text(encoding='utf-8') == 'custom-agents'
    assert (dest / 'CLAUDE.md').read_text(encoding='utf-8') == 'custom-claude'
    # --force still must not overwrite agent guidance
    assert main(['init', str(dest), '--force']) == 0
    assert (dest / 'AGENTS.md').read_text(encoding='utf-8') == 'custom-agents'
    assert (dest / 'CLAUDE.md').read_text(encoding='utf-8') == 'custom-claude'


def test_init_refuses_existing_config_without_force(tmp_path: Path) -> None:
    dest = tmp_path / 'edition'
    assert main(['init', str(dest)]) == 0
    marker = dest / 'odd' / 'custom.odd'
    marker.write_text('keep-me', encoding='utf-8')
    rc = main(['init', str(dest)])
    assert rc == 1
    assert marker.read_text(encoding='utf-8') == 'keep-me'


def test_init_force_overwrites(tmp_path: Path) -> None:
    dest = tmp_path / 'edition'
    assert main(['init', str(dest)]) == 0
    (dest / 'odd' / 'custom.odd').write_text('stale', encoding='utf-8')
    rc = main(['init', str(dest), '--force'])
    assert rc == 0
    text = (dest / 'odd' / 'custom.odd').read_text(encoding='utf-8')
    assert 'stale' not in text
    assert 'source="teipublisher.odd"' in text


def test_init_invalid_vocabulary(tmp_path: Path) -> None:
    rc = main(['init', str(tmp_path / 'x'), '--vocabulary', 'nroff'])
    assert rc == 1
    assert not (tmp_path / 'x' / 'opm.toml').exists()


def test_init_docbook_copies_stock_odd(tmp_path: Path) -> None:
    from opm.config import load_project_config

    dest = tmp_path / 'dbk'
    rc = main(['init', str(dest), '--vocabulary', 'docbook'])
    assert rc == 0
    assert (dest / 'odd' / 'docbook.odd').is_file()
    assert (dest / 'odd' / 'docbook.css').is_file()
    assert not (dest / 'odd' / 'custom.odd').exists()
    sample = (dest / 'data' / 'sample.xml').read_text(encoding='utf-8')
    assert 'docbook.org/ns/docbook' in sample
    cfg = load_project_config(dest / 'opm.toml')
    assert cfg.chunking is not None
    assert cfg.chunking.selector == 'opm.navigation.dbk_section_chunks'
    assert cfg.transform_odd is not None
    assert cfg.transform_odd.name == 'docbook.odd'
    assert (dest / 'templates' / 'docbook.typ.j2').is_file()


def test_init_jats_copies_stock_odd(tmp_path: Path) -> None:
    from opm.config import load_project_config

    dest = tmp_path / 'jats'
    rc = main(['init', str(dest), '--vocabulary', 'jats'])
    assert rc == 0
    assert (dest / 'odd' / 'jats.odd').is_file()
    assert (dest / 'odd' / 'jats.css').is_file()
    assert not (dest / 'odd' / 'custom.odd').exists()
    sample = (dest / 'data' / 'sample.xml').read_text(encoding='utf-8')
    assert '<article-title>' in sample
    cfg = load_project_config(dest / 'opm.toml')
    assert cfg.chunking is not None
    assert cfg.chunking.selector == 'opm.navigation.jats_sec_chunks'
    assert cfg.transform_odd is not None
    assert cfg.transform_odd.name == 'jats.odd'
    # jats.odd has no mode='breadcrumb' models, so that fragment is not declared.
    assert [f.name for f in cfg.chunking.fragments] == ['title']


def test_init_jats_wires_journal_shell(tmp_path: Path) -> None:
    """A JATS project reads as a journal article, so it gets the journal shell."""
    from opm.config import load_project_config

    dest = tmp_path / 'jats'
    assert main(['init', str(dest), '--vocabulary', 'jats']) == 0
    cfg = load_project_config(dest / 'opm.toml')
    assert cfg.document_template is not None
    assert cfg.document_template.name == 'journal.html.j2'
    assert cfg.chunking is not None
    assert cfg.chunking.template is not None
    assert cfg.chunking.template.name == 'journal.html.j2'
    # The shell only styles what the ODD renders into .content, so the other
    # shells are still copied alongside it.
    assert (dest / 'templates' / 'journal.css').is_file()
    assert (dest / 'templates' / 'chapbook.html.j2').is_file()


def test_init_jats_transform_and_chunk(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / 'jats'
    assert main(['init', str(dest), '--vocabulary', 'jats']) == 0
    monkeypatch.chdir(dest)
    html = dest / 'out.html'
    assert main(['transform', 'data/sample.xml', '-o', str(html)]) == 0
    text = html.read_text(encoding='utf-8')
    assert '<html' in text.lower()
    assert 'Sample article' in text
    # The journal shell wraps the article; without a `journal` fragment the
    # masthead stays out and journal-meta keeps its place in the flow.
    body_tag = re.search(r'<body[^>]*>', text).group(0)
    assert 'jr' in body_tag
    assert 'jr--journal-meta' not in body_tag
    assert '<header class="jr-masthead">' not in text
    # A pb:template inside a no-namespace ODD must keep the markup it builds.
    assert '<li id="ref1">' in text
    assert main(['transform', 'data/sample.xml', '-t', 'markdown', '-o', str(dest / 'out.md')]) == 0
    typ = dest / 'out.typ'
    assert main(['transform', 'data/sample.xml', '-t', 'typst', '-o', str(typ)]) == 0
    # Front matter feeds the Typst title block rather than the body.
    assert 'title: [Sample article]' in typ.read_text(encoding='utf-8')
    assert main(['transform', 'data/sample.xml', '-t', 'docx', '-o', str(dest / 'out.docx')]) == 0
    assert (dest / 'out.docx').stat().st_size > 0
    assert main(['chunk', 'data/sample.xml', '--force']) == 0
    chunks = sorted((dest / 'chunks').glob('[0-9]*.html'))
    # front + two sections + back
    assert len(chunks) == 4
    # @id anchors resolve across chunks even though JATS has no xml:id.
    assert 'href="004.html#ref1"' in chunks[2].read_text(encoding='utf-8')


def test_init_copy_base_odd_tei(tmp_path: Path) -> None:
    dest = tmp_path / 'with-base'
    rc = main(['init', str(dest), '--copy-base-odd'])
    assert rc == 0
    assert (dest / 'odd' / 'teipublisher.odd').is_file()
    assert (dest / 'odd' / 'tp.css').is_file()


def test_init_tei_transform_and_chunk(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / 'edition'
    assert main(['init', str(dest)]) == 0
    monkeypatch.chdir(dest)
    html = dest / 'out.html'
    assert main(['transform', 'data/sample.xml', '-o', str(html)]) == 0
    assert '<html' in html.read_text(encoding='utf-8').lower()
    assert main(['transform', 'data/sample.xml', '-t', 'markdown', '-o', str(dest / 'out.md')]) == 0
    assert (dest / 'out.md').read_text(encoding='utf-8').strip()
    assert main(['transform', 'data/sample.xml', '-t', 'typst', '-o', str(dest / 'out.typ')]) == 0
    assert (dest / 'out.typ').read_text(encoding='utf-8').strip()
    assert main(['transform', 'data/sample.xml', '-t', 'docx', '-o', str(dest / 'out.docx')]) == 0
    assert (dest / 'out.docx').stat().st_size > 0
    assert main(['chunk', 'data/sample.xml', '--force']) == 0
    chunk_files = list((dest / 'chunks').glob('*.html'))
    assert len(chunk_files) >= 2


def test_init_docbook_transform_and_chunk(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / 'dbk'
    assert main(['init', str(dest), '--vocabulary', 'docbook']) == 0
    monkeypatch.chdir(dest)
    html = dest / 'out.html'
    assert main(['transform', 'data/sample.xml', '-o', str(html)]) == 0
    assert '<html' in html.read_text(encoding='utf-8').lower()
    assert main(['transform', 'data/sample.xml', '-t', 'markdown', '-o', str(dest / 'out.md')]) == 0
    assert main(['transform', 'data/sample.xml', '-t', 'typst', '-o', str(dest / 'out.typ')]) == 0
    assert main(['transform', 'data/sample.xml', '-t', 'docx', '-o', str(dest / 'out.docx')]) == 0
    assert (dest / 'out.docx').stat().st_size > 0
    assert main(['chunk', 'data/sample.xml', '--force']) == 0
    assert list((dest / 'chunks').glob('*.html'))
