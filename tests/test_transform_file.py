"""``transform_file()`` — the path ``opm transform`` runs — takes the project config."""

from __future__ import annotations

from pathlib import Path

from opm.config import ChunkingConfig, ProjectConfig
from opm.transform import transform_file

_ECHO_MODULE = """OUTPUT_MODE = {mode!r}


def serialize(result):
    return ''.join(str(item) for item in result)


def transform(root, options=None, *, xpath_env=None):
    return [repr(sorted((options or {{}}).items()))]
"""


def _module(tmp_path: Path, mode: str = 'markdown') -> Path:
    path = tmp_path / f'echo_{mode}.py'
    path.write_text(_ECHO_MODULE.format(mode=mode), encoding='utf-8')
    return path


def test_parameters_are_merged_over_the_configured_ones(tmp_path: Path) -> None:
    xml = tmp_path / 'doc.xml'
    xml.write_text('<doc/>', encoding='utf-8')
    cfg = ProjectConfig(parameters={'view': 'page', 'lang': 'de'})

    out = transform_file(_module(tmp_path), xml, parameters={'lang': 'en'}, config=cfg)

    assert out == repr(sorted({'view': 'page', 'lang': 'en', 'input_path': str(xml)}.items()))


def test_epub_uses_the_epub_chapter_selection(tmp_path: Path, monkeypatch) -> None:
    import opm.epub

    seen: list = []
    monkeypatch.setattr(
        opm.epub, 'build_epub', lambda *args, chunking, **kwargs: seen.append(chunking) or b'',
    )
    xml = tmp_path / 'doc.xml'
    xml.write_text('<doc/>', encoding='utf-8')
    cfg = ProjectConfig(
        chunking=ChunkingConfig(xpath='//div'),
        epub_chunk_overrides={'xpath': '//body/div'},
    )

    transform_file(_module(tmp_path, 'epub'), xml, config=cfg)

    assert [c.xpath for c in seen] == ['//body/div']


def test_project_extensions_import_through_the_configured_pythonpath(
    tmp_path: Path, monkeypatch,
) -> None:
    import sys

    from lxml import etree

    from opm.transform import project_xpath_env

    monkeypatch.setattr(sys, 'path', list(sys.path))
    project = tmp_path / 'project'
    (project / 'extensions').mkdir(parents=True)
    (project / 'extensions' / 'opm_pythonpath_probe.py').write_text(
        'def shout(text):\n    return str(text).upper()\n', encoding='utf-8',
    )
    cfg = ProjectConfig(
        pythonpath=(project / 'extensions',),
        xpath_extensions=('opm_pythonpath_probe',),
    )

    env = project_xpath_env(cfg)

    assert env.select(etree.fromstring('<doc/>'), "tp:shout('hi')") == 'HI'
    # Calling it again adds nothing.
    project_xpath_env(cfg)
    assert sys.path.count(str((project / 'extensions').resolve())) == 1


_PAGED_TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>Paged</title></titleStmt></fileDesc></teiHeader>
  <text><body><div>
    <pb n="1"/><cb n="1"/><p>one-a</p><cb n="2"/><p>one-b</p>
    <pb n="2"/><cb n="1"/><p>two-a</p><cb n="2"/><p>two-b</p>
  </div></body></text>
</TEI>"""


def _paged_run(tmp_path: Path, mode: str, cfg: ProjectConfig) -> str:
    from lxml import html

    from opm.odd_cache import ensure_compiled_module
    from opm.resources import packaged_odd

    xml = tmp_path / 'doc.xml'
    xml.write_text(_PAGED_TEI, encoding='utf-8')
    module_path, _ = ensure_compiled_module(packaged_odd('teipublisher'), output_mode=mode)
    return html.fromstring(transform_file(module_path, xml, config=cfg))


def test_web_pages_renders_one_section_per_page(tmp_path: Path) -> None:
    cfg = ProjectConfig(web_pages='opm.navigation.tei_pb_chunks')

    doc = _paged_run(tmp_path, 'web', cfg)

    pages = doc.xpath('//section[@class="opm-page"]')
    assert [''.join(p.text_content().split()) for p in pages] == ['1one-aone-b', '2two-atwo-b']
    # Each page brings its own column break, as on a chunk page.
    assert [len(p.xpath('.//*[contains(@class, "tei-cb")]')) for p in pages] == [2, 2]


def test_web_pages_leaves_other_modes_alone(tmp_path: Path) -> None:
    cfg = ProjectConfig(web_pages='opm.navigation.tei_pb_chunks')

    assert not _paged_run(tmp_path, 'print', cfg).xpath('//section[@class="opm-page"]')
    assert not _paged_run(tmp_path, 'web', ProjectConfig()).xpath('//section[@class="opm-page"]')
