"""``opm.Project`` — the Python API the ``transform``, ``chunk``, ``index`` and ``coverage`` commands run through."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from lxml import etree

import opm
from opm import Project, ProjectConfig
from opm.chunking import chunk_document
from opm.config import ChunkingConfig, FragmentConfig
from opm.indexing import index_document
from opm.transform import transform_file

_MODELS = (
    '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
    '<elementSpec ident="text"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="body"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="div"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
    '<elementSpec ident="ref"><model behaviour="link"/></elementSpec>'
)

_DOC = (
    '<doc><text><body>'
    '<div type="chunk" xml:id="a"><p>The first chunk has a paragraph long enough to index.</p></div>'
    '<div type="chunk" xml:id="b"><p>The second chunk links back to '
    '<ref target="#a">the first</ref> one, and is long enough too.</p></div>'
    '</body></text></doc>'
)


def _odd(path: Path, models: str = _MODELS) -> Path:
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        f'<text><body><schemaSpec ident="{path.stem}" ns="">{models}</schemaSpec></body></text>'
        '</TEI>',
        encoding='utf-8',
    )
    return path


def _doc(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DOC, encoding='utf-8')
    return path


def _project(tmp_path: Path, toml: str = '') -> Project:
    _odd(tmp_path / 'tiny.odd')
    config = tmp_path / 'opm.toml'
    config.write_text(
        '[transform]\nodd = "tiny.odd"\n\n'
        '[chunking]\nodd = "tiny.odd"\n'
        'xpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n' + toml,
        encoding='utf-8',
    )
    return Project.load(config)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch) -> None:
    # Compiled modules go to a throwaway cache; `pythonpath` entries are undone.
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: tmp_path / 'cache' / 'modules')
    monkeypatch.setattr(sys, 'path', list(sys.path))


# ── loading ──────────────────────────────────────────────────────────────────

def test_load_roots_the_project_at_the_config_directory(tmp_path: Path, monkeypatch) -> None:
    edition = tmp_path / 'edition'
    (edition / 'lib').mkdir(parents=True)
    (edition / 'opm.toml').write_text(
        '[project]\npythonpath = ["lib"]\n\n[transform.parameters]\nlang = "de"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)

    project = Project.load('edition/opm.toml')

    assert project.root == edition
    assert project.config.parameters == {'lang': 'de'}
    assert str((edition / 'lib').resolve()) in sys.path


def test_load_without_a_config_file_has_default_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    project = Project.load()

    assert project.root == tmp_path
    assert project.config == ProjectConfig()


def test_load_rejects_a_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match='missing.toml'):
        Project.load(tmp_path / 'missing.toml')


def test_with_config_replaces_fields_on_a_copy(tmp_path: Path) -> None:
    project = Project(ProjectConfig(parameters={'lang': 'de'}), root=tmp_path)

    changed = project.with_config(parameters={'lang': 'en'})

    assert changed.config.parameters == {'lang': 'en'}
    assert changed.root == tmp_path
    assert project.config.parameters == {'lang': 'de'}


def test_package_exports() -> None:
    assert opm.Project is Project
    assert isinstance(opm.__version__, str)
    assert set(opm.__all__) <= set(dir(opm))
    with pytest.raises(AttributeError):
        opm.no_such_name  # noqa: B018


# ── compiling and transforming ───────────────────────────────────────────────

def test_each_mode_uses_its_configured_odd(tmp_path: Path) -> None:
    _odd(tmp_path / 'md.odd')
    project = _project(tmp_path, '\n[transform.markdown]\nodd = "md.odd"\n')

    assert project.compile().source_odd == tmp_path / 'tiny.odd'
    assert project.compile('markdown').source_odd == tmp_path / 'md.odd'
    assert project.compile('markdown', odd=tmp_path / 'tiny.odd').source_odd == tmp_path / 'tiny.odd'
    with pytest.raises(ValueError):
        project.compile('no-such-mode')


def test_transform_matches_transform_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')

    expected = transform_file(project.module(), xml, config=project.config)

    assert project.transform(xml) == expected
    assert project.transform(str(xml)) == expected
    # An element parsed from the file stands for the file.
    assert project.transform(etree.parse(str(xml))) == expected
    assert project.transform(etree.parse(str(xml)).getroot()) == expected


def test_transform_accepts_an_element_not_read_from_a_file(tmp_path: Path) -> None:
    project = _project(tmp_path)

    out = project.transform(etree.fromstring(_DOC), mode='markdown', xpath='//div[@xml:id="b"]')

    assert 'second chunk' in out
    assert 'first chunk has' not in out


def test_modules_and_registers_are_loaded_once(tmp_path: Path, monkeypatch) -> None:
    import opm.project

    calls = {'resolve': 0, 'load': 0, 'registers': 0}

    def counting(name, function):
        def wrapper(*args, **kwargs):
            calls[name] += 1
            return function(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(opm.project, 'resolve_transform_module',
                        counting('resolve', opm.project.resolve_transform_module))
    monkeypatch.setattr(opm.project, 'load_transform_module',
                        counting('load', opm.project.load_transform_module))
    monkeypatch.setattr(opm.project, 'load_project_documents',
                        counting('registers', opm.project.load_project_documents))
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')

    first = project.transform(xml)
    assert project.transform(xml) == first
    assert calls == {'resolve': 1, 'load': 1, 'registers': 1}


# ── chunking ─────────────────────────────────────────────────────────────────

def test_chunk_writes_below_the_project_root(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    run = project.chunk(xml)

    site = tmp_path / 'site'
    assert run.output_dir == site
    assert run.documents == (xml,)
    assert run.format == 'html'
    # One document or many, an HTML run writes the collection index.
    assert run.index_file == site / 'index.html'
    assert run.modules[0].source_odd == tmp_path / 'tiny.odd'
    manifest = json.loads((site / 'doc.xml' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['anchors'] == {'a': '001.html', 'b': '002.html'}
    assert not (elsewhere / 'site').exists()


def test_chunk_replaces_existing_output_only_when_asked(tmp_path: Path) -> None:
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')
    stale = tmp_path / 'site' / 'stale.html'
    stale.parent.mkdir()
    stale.write_text('old', encoding='utf-8')

    with pytest.raises(FileExistsError):
        project.chunk(xml)
    assert stale.is_file()

    project.chunk(xml, overwrite=True)
    assert not stale.exists()
    assert (tmp_path / 'site' / 'doc.xml' / '001.html').is_file()


def test_chunk_a_directory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    one = _doc(tmp_path / 'docs' / 'one.xml')
    two = _doc(tmp_path / 'docs' / 'two.xml')
    seen: list[tuple[int, str]] = []

    run = project.chunk(
        tmp_path / 'docs',
        output_dir='out',
        on_document=lambda position, path: seen.append((position, path.name)),
    )

    out = tmp_path / 'out'
    assert run.documents == (one, two)
    assert seen == [(0, 'one.xml'), (1, 'two.xml')]
    assert (out / 'one.xml' / '001.html').is_file()
    assert (out / 'two.xml' / '002.html').is_file()
    assert run.index_file == out / 'index.html'
    assert run.index_file.is_file()


def test_chunk_json_and_pb_view_formats(tmp_path: Path) -> None:
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')

    project.chunk(xml, format='json')
    chunk = json.loads(
        (tmp_path / 'site' / 'doc.xml' / '001.json').read_text(encoding='utf-8'),
    )
    assert 'first chunk' in chunk['content']

    project.chunk(xml, format='pb-view', doc_path='letters', overwrite=True)
    assert (tmp_path / 'site' / 'letters' / 'index.json').is_file()

    with pytest.raises(ValueError, match='format'):
        project.chunk(xml, format='pdf', overwrite=True)


def test_chunk_needs_a_chunking_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r'\[chunking\]'):
        Project(root=tmp_path).chunk(_doc(tmp_path / 'doc.xml'))


_FRAGMENT_MODELS = (
    '<elementSpec ident="doc"><model behaviour="inline">'
    '<param name="content" value="\'from the fragment ODD\'"/>'
    '</model></elementSpec>'
)


def test_chunk_compiles_fragment_odds(tmp_path: Path) -> None:
    _odd(tmp_path / 'frag.odd', _FRAGMENT_MODELS)
    project = _project(
        tmp_path,
        '\n[[chunking.fragments]]\nname = "toc"\nscope = "global"\nxpath = "."\nodd = "frag.odd"\n',
    )

    run = project.chunk(_doc(tmp_path / 'doc.xml'))

    assert [m.source_odd for m in run.modules] == [tmp_path / 'tiny.odd', tmp_path / 'frag.odd']
    manifest = json.loads(
        (tmp_path / 'site' / 'doc.xml' / 'manifest.json').read_text(encoding='utf-8'),
    )
    assert 'from the fragment ODD' in manifest['fragments']['toc']


def test_chunk_document_compiles_fragment_odds_itself(tmp_path: Path) -> None:
    config = ChunkingConfig(
        xpath="//body/div[@type='chunk']",
        output_dir='out',
        odd=_odd(tmp_path / 'tiny.odd'),
        fragments=[
            FragmentConfig(
                name='toc', scope='global', xpath='.',
                odd=_odd(tmp_path / 'frag.odd', _FRAGMENT_MODELS),
            ),
        ],
    )

    chunk_document(None, _doc(tmp_path / 'doc.xml'), config, tmp_path)

    manifest = json.loads((tmp_path / 'out' / 'manifest.json').read_text(encoding='utf-8'))
    assert 'from the fragment ODD' in manifest['fragments']['toc']


# ── indexing and coverage ────────────────────────────────────────────────────

def test_index_matches_index_document(tmp_path: Path) -> None:
    project = _project(tmp_path)
    one = _doc(tmp_path / 'docs' / 'one.xml')
    two = _doc(tmp_path / 'docs' / 'nested' / 'two.xml')

    records = project.index(tmp_path / 'docs')

    expected = [
        record
        for path in (two, one)  # sorted: docs/nested/two.xml < docs/one.xml
        for record in index_document(path, cfg=project.config, project_root=project.root)
    ]
    assert records
    assert records == expected
    assert project.index([one]) == index_document(one, cfg=project.config, project_root=project.root)


def test_coverage_reports_on_the_configured_odd(tmp_path: Path) -> None:
    project = _project(tmp_path)
    xml = _doc(tmp_path / 'doc.xml')

    report = project.coverage(xml)

    assert report.odd == tmp_path / 'tiny.odd'
    assert report.channel == 'web'
    assert report.documents == [xml]
    assert project.coverage(xml, mode='json-print').channel == 'print'


# ── several chunking runs ([[chunking]]) ────────────────────────────────────

_TWO_RUN_DOC = (
    '<doc><text><body>'
    '<div type="chapter" xml:id="intro"><p>The introduction, long enough to be a page.</p>'
    '<div xml:id="intro-sec"><p>A section inside it.</p></div></div>'
    '<div type="ref" xml:id="ref-p"><p>A reference entry that points '
    '<ref target="#intro-sec">into the introduction</ref>.</p></div>'
    '</body></text></doc>'
)


def _two_run_project(tmp_path: Path, runs: str) -> Project:
    # A link model that carries its target, so a resolved cross-run link shows.
    _odd(tmp_path / 'tiny.odd', _MODELS.replace(
        '<elementSpec ident="ref"><model behaviour="link"/></elementSpec>',
        '<elementSpec ident="ref"><model behaviour="link">'
        '<param name="uri" value="@target"/></model></elementSpec>',
    ))
    config = tmp_path / 'opm.toml'
    config.write_text('[transform]\nodd = "tiny.odd"\n\n' + runs, encoding='utf-8')
    return Project.load(config)


_TWO_RUNS = (
    '[[chunking]]\nname = "text"\noutput_dir = "site"\n'
    'xpath = "//body/div[@type=\'chapter\']"\nfile_pattern = "{xml_id}.html"\n\n'
    '[[chunking.fragments]]\nname = "toc"\nscope = "global"\nxpath = "."\n\n'
    '[[chunking]]\nname = "reference"\n'
    'xpath = "//body/div[@type=\'ref\']"\nfile_pattern = "{xml_id}.html"\n'
)


def test_a_chunking_table_is_one_run(tmp_path: Path) -> None:
    """The form every existing project uses reads exactly as before."""
    project = _project(tmp_path)
    assert project.config.chunking_runs == (project.config.chunking,)
    assert project.config.chunking.name is None


def test_a_chunking_array_is_several_runs(tmp_path: Path) -> None:
    project = _two_run_project(tmp_path, _TWO_RUNS)
    runs = project.config.chunking_runs
    assert [run.name for run in runs] == ['text', 'reference']
    # Fragments attach to the run they follow; the ODD and output directory
    # reach every run.
    assert [f.name for f in runs[0].fragments or ()] == ['toc']
    assert runs[1].fragments is None
    assert {run.output_dir for run in runs} == {'site'}
    assert {run.odd for run in runs} == {tmp_path / 'tiny.odd'}
    assert project.config.chunking is runs[0]


def test_a_later_run_cannot_move_the_output(tmp_path: Path) -> None:
    runs = _TWO_RUNS.replace('name = "reference"\n', 'name = "reference"\noutput_dir = "elsewhere"\n')
    with pytest.raises(ValueError, match=r'"reference".*output_dir'):
        _two_run_project(tmp_path, runs)


def test_chunking_must_be_a_table_or_an_array_of_tables(tmp_path: Path) -> None:
    config = tmp_path / 'opm.toml'
    # Top level, before any table header, or TOML files it under that table.
    config.write_text('chunking = "pages"\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'\[chunking\] table or a \[\[chunking\]\] array'):
        Project.load(config)


def test_runs_share_one_directory_and_resolve_each_others_links(tmp_path: Path) -> None:
    project = _two_run_project(tmp_path, _TWO_RUNS)
    xml = tmp_path / 'doc.xml'
    xml.write_text(_TWO_RUN_DOC, encoding='utf-8')

    project.chunk(xml, format='json')

    out = tmp_path / 'site' / 'doc.xml'
    assert (out / 'intro.json').is_file() and (out / 'ref-p.json').is_file()
    # The reference run was handed the text run's anchors.
    ref = json.loads((out / 'ref-p.json').read_text(encoding='utf-8'))
    assert 'intro.html#intro-sec' in ref['content']
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    assert [(c['file'], c['run']) for c in manifest['chunks']] == [
        ('intro.html', 'text'), ('ref-p.html', 'reference'),
    ]
    assert manifest['anchors']['intro-sec'] == 'intro.html'
    assert 'toc' in manifest['fragments']


def test_the_search_index_covers_every_run(tmp_path: Path) -> None:
    """A documentation site's search finds chapters and reference pages alike."""
    project = _two_run_project(tmp_path, _TWO_RUNS)
    xml = tmp_path / 'doc.xml'
    xml.write_text(_TWO_RUN_DOC, encoding='utf-8')

    records = project.index(xml)

    files = {record['metadata'].get('chunk') for record in records}
    assert {'intro.html', 'ref-p.html'} <= files, sorted(map(str, files))
