"""Tests for ``cli`` helpers."""

from __future__ import annotations

import json
from pathlib import Path

from opm.cli import _preview_kind_from_module
from opm.cli import _resolve_user_css
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
    monkeypatch.setattr('opm.cli.packaged_default_css', lambda: None)
    assert _resolve_user_css(None) is None


def test_resolve_user_css_falls_back_to_packaged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    packaged = tmp_path / 'packaged.css'
    packaged.write_text('.packaged { color: blue; }', encoding='utf-8')
    monkeypatch.setattr('opm.cli.packaged_default_css', lambda: packaged)
    assert _resolve_user_css(None) == '.packaged { color: blue; }'


def test_resolve_user_css_explicit_path_overrides_default(tmp_path: Path, monkeypatch) -> None:
    styles = tmp_path / 'styles'
    styles.mkdir()
    (styles / 'default-styles.css').write_text('default', encoding='utf-8')
    custom = tmp_path / 'custom.css'
    custom.write_text('custom', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    assert _resolve_user_css(custom) == 'custom'


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
    (project / 'templates' / 'custom.j2').write_text(
        '<html><head><!-- config-relative-template --><style>{{ user_css }}</style></head>'
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
