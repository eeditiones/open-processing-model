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
