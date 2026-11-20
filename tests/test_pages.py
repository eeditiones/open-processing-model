"""Auxiliary pages (``[[pages]]``): standalone site pages beside the reading view."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from opm import Project
from opm.chunking import collect_index_entries
from opm.config import load_project_config

_MODELS = (
    '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
    '<elementSpec ident="text"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="body"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="div"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
    '<elementSpec ident="register"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="listPlace"><model behaviour="block"/></elementSpec>'
    # The register-overview models follow teipublisher.odd's: a link to the
    # entry's page, addressed the TEI Publisher way (no suffix, from the root).
    '<elementSpec ident="place">'
    '<model predicate="$parameters?mode=\'register-overview\'" behaviour="pass-through">'
    '<param name="id" value="@xml:id"/><param name="label" value="placeName[1]/string()"/>'
    '<pb:template xmlns=""><div><header><a href="places/[[id]]">[[label]]</a></header></div></pb:template>'
    '</model><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="placeName"><model behaviour="paragraph"/></elementSpec>'
    '<elementSpec ident="listPerson"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="person">'
    '<model predicate="$parameters?mode=\'register-overview\'" behaviour="pass-through">'
    '<param name="id" value="@xml:id"/><param name="label" value="persName[1]/string()"/>'
    '<pb:template xmlns=""><div><header><a href="people/[[id]]">[[label]]</a></header></div></pb:template>'
    '</model><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="persName"><model behaviour="paragraph"/></elementSpec>'
)

_DOC = (
    '<doc><text><body>'
    '<div type="chunk" xml:id="a"><p key="pl1">The first chunk has a paragraph long enough to be indexed.</p></div>'
    '<div type="chunk" xml:id="b"><p>The second chunk has a paragraph long enough to be indexed too.</p></div>'
    '</body></text></doc>'
)

_REGISTER = (
    '<register><listPlace>'
    '<place xml:id="pl1"><placeName>Kraków</placeName></place>'
    '<place xml:id="pl2"><placeName>Warszawa</placeName></place>'
    '</listPlace></register>'
)

_PERSONS = (
    '<register><listPerson>'
    '<person xml:id="p1"><persName>Adam Mickiewicz</persName></person>'
    '<person xml:id="p2"><persName>Juliusz Słowacki</persName></person>'
    '</listPerson></register>'
)

_ABOUT_TEMPLATE = (
    '---toml\n[templating]\nextends = "opm/layout.html.tpl"\n---\n'
    '<template>[% template content %]<p id="about">About this project</p>[% endtemplate %]</template>\n'
)

_PAGES_TOML = (
    '[[pages]]\n'
    'path = "about.html"\n'
    'template = "templates/about.html.tpl"\n'
    'menu = "About"\n'
    '\n'
    '[[pages]]\n'
    'path = "places/index.html"\n'
    'menu = "Places"\n'
    'source = "register.xml"\n'
    'xpath = "//listPlace"\n'
    '\n'
    '[[pages]]\n'
    'path = "places/{xml_id}.html"\n'
    'source = "register.xml"\n'
    'xpath = "//listPlace/place"\n'
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch) -> Path:
    # A home directory of our own, so ~/.opm/profiles never leaks in.
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: tmp_path / 'cache' / 'modules')
    monkeypatch.setattr(sys, 'path', list(sys.path))
    return home


def _config(tmp_path: Path, toml: str) -> Path:
    path = tmp_path / 'opm.toml'
    path.write_text(toml, encoding='utf-8')
    return path


def _profile(base: Path, name: str, toml: str = '', templates: dict[str, str] | None = None) -> Path:
    path = base / name
    path.mkdir(parents=True)
    (path / 'opm-profile.toml').write_text(toml, encoding='utf-8')
    for file_name, text in (templates or {}).items():
        (path / 'templates').mkdir(exist_ok=True)
        (path / 'templates' / file_name).write_text(text, encoding='utf-8')
    return path


def _odd() -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        f'<text><body><schemaSpec ident="tiny" ns="">{_MODELS}</schemaSpec></body></text>'
        '</TEI>'
    )


def _project(tmp_path: Path, project_toml: str = '') -> Project:
    (tmp_path / 'tiny.odd').write_text(_odd(), encoding='utf-8')
    (tmp_path / 'doc.xml').write_text(_DOC, encoding='utf-8')
    (tmp_path / 'register.xml').write_text(_REGISTER, encoding='utf-8')
    (tmp_path / 'templates').mkdir(exist_ok=True)
    (tmp_path / 'templates' / 'about.html.tpl').write_text(_ABOUT_TEMPLATE, encoding='utf-8')
    return Project.load(_config(tmp_path, project_toml + (
        '\n[transform]\nodd = "tiny.odd"\n\n[chunking]\nodd = "tiny.odd"\n'
        'xpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
    )))


# ── parsing ──────────────────────────────────────────────────────────────────

def test_pages_are_parsed_from_the_config(tmp_path: Path) -> None:
    cfg = load_project_config(_config(tmp_path, _PAGES_TOML))
    assert [page.path for page in cfg.pages] == [
        'about.html', 'places/index.html', 'places/{xml_id}.html',
    ]
    about, overview, detail = cfg.pages
    assert about.menu == 'About'
    assert about.template == tmp_path / 'templates' / 'about.html.tpl'
    assert about.source is None
    assert overview.source == tmp_path / 'register.xml'
    assert overview.xpath == '//listPlace'
    assert detail.xpath == '//listPlace/place'


@pytest.mark.parametrize('toml, match', [
    ('[[pages]]\nmenu = "x"\n', 'missing "path"'),
    ('[[pages]]\npath = "a.html"\nweird = 1\n', 'unknown key'),
    ('[[pages]]\npath = "../a.html"\n', 'relative and stay below'),
    ('[[pages]]\npath = "/a.html"\n', 'relative and stay below'),
    ('[[pages]]\npath = "{bogus}.html"\n', 'placeholder \\{bogus\\}'),
    ('[[pages]]\npath = "a.html"\n[[pages]]\npath = "a.html"\n', 'declared twice'),
    ('[[pages]]\npath = "a.html"\nxpath = "//p"\nselector = "mod:f"\n', 'both "xpath" and "selector"'),
    ('pages = "a.html"\n', 'array of tables'),
])
def test_bad_pages_entries_are_reported(tmp_path: Path, toml: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_project_config(_config(tmp_path, toml))


# ── rendering ────────────────────────────────────────────────────────────────

def test_static_and_data_pages_are_written_beside_the_reading_view(tmp_path: Path) -> None:
    project = _project(tmp_path, _PAGES_TOML)
    run = project.chunk(tmp_path / 'doc.xml')
    site = run.output_dir

    # The reading view is untouched.
    assert (site / 'doc.xml' / '001.html').is_file()

    # The static page, at the root, with its own content.
    about = site / 'about.html'
    assert about.is_file()
    assert 'About this project' in about.read_text(encoding='utf-8')

    # The overview page: one file for the single selected node.
    overview = site / 'places' / 'index.html'
    assert overview.is_file()
    overview_html = overview.read_text(encoding='utf-8')
    assert 'Kraków' in overview_html and 'Warszawa' in overview_html

    # The detail pages: one per selected node, named by xml:id.
    assert 'Kraków' in (site / 'places' / 'pl1.html').read_text(encoding='utf-8')
    assert 'Warszawa' in (site / 'places' / 'pl2.html').read_text(encoding='utf-8')

    # ChunkRun reports the pages.
    assert about in run.pages
    assert site / 'places' / 'pl1.html' in run.pages

    # css/ and assets/ stay shared at the root, not copied into places/.
    assert (site / 'css').is_dir()
    assert not (site / 'places' / 'css').exists()

    # The page directory's manifest is tagged, so it is not a document.
    manifest = json.loads((site / 'places' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['role'] == 'page'
    assert {entry.name for entry in collect_index_entries(site)} == {'doc.xml'}

    # The index lists documents only: neither the page directories nor the
    # pages themselves (the menubar links those).
    index = run.index_file.read_text(encoding='utf-8')
    assert 'href="about.html"' not in index
    assert 'places/pl1.html' not in index
    assert 'doc.xml/' in index  # the document entry is still there


def test_single_page_path_must_select_exactly_one_node(tmp_path: Path) -> None:
    project = _project(tmp_path, (
        '[[pages]]\npath = "places/index.html"\nsource = "register.xml"\nxpath = "//listPlace/place"\n'
    ))
    with pytest.raises(ValueError, match='single page'):
        project.chunk(tmp_path / 'doc.xml')


def test_multi_page_path_selecting_nothing_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path, (
        '[[pages]]\npath = "places/{xml_id}.html"\nsource = "register.xml"\nxpath = "//nothing"\n'
    ))
    with pytest.raises(ValueError, match='selects nothing'):
        project.chunk(tmp_path / 'doc.xml')


def test_pages_can_be_skipped_or_filtered(tmp_path: Path) -> None:
    project = _project(tmp_path, _PAGES_TOML)
    run = project.chunk(tmp_path / 'doc.xml', pages=False)
    assert not (run.output_dir / 'about.html').exists()
    assert not (run.output_dir / 'places').exists()
    assert run.pages == ()

    run = project.chunk(tmp_path / 'doc.xml', overwrite=True, pages='places')
    assert not (run.output_dir / 'about.html').exists()
    assert (run.output_dir / 'places' / 'pl1.html').is_file()


def test_pages_are_skipped_for_json_output(tmp_path: Path) -> None:
    project = _project(tmp_path, _PAGES_TOML)
    run = project.chunk(tmp_path / 'doc.xml', format='json')
    assert not (run.output_dir / 'about.html').exists()
    assert run.pages == ()


def test_page_links_into_the_reading_view(tmp_path: Path) -> None:
    # A page rendering a node that references a chunk id gets the reading
    # view's anchors, prefixed with the document's directory.
    register = (
        '<register><listPlace>'
        '<place xml:id="pl1"><placeName>Kraków</placeName><ref target="#b">see letter</ref></place>'
        '</listPlace></register>'
    )
    project = _project(tmp_path, (
        '[[pages]]\npath = "places/{xml_id}.html"\nsource = "register.xml"\nxpath = "//listPlace/place"\n'
    ))
    (tmp_path / 'register.xml').write_text(register, encoding='utf-8')
    ref_spec = (
        '<elementSpec ident="ref">'
        '<model predicate="@target" behaviour="link">'
        '<param name="uri" value="@target"/></model></elementSpec>'
    )
    (tmp_path / 'tiny.odd').write_text(
        _odd().replace('</schemaSpec>', ref_spec + '</schemaSpec>'), encoding='utf-8',
    )
    run = project.chunk(tmp_path / 'doc.xml')
    page = (run.output_dir / 'places' / 'pl1.html').read_text(encoding='utf-8')
    assert 'href="../doc.xml/002.html#b"' in page


# ── profiles ─────────────────────────────────────────────────────────────────

_PROFILE_PAGES = (
    '[[pages]]\n'
    'path = "places/{xml_id}.html"\n'
    'menu = "Places"\n'
    'source = "register.xml"\n'
    'xpath = "//listPlace/place"\n'
    'template = "templates/place.html.tpl"\n'
)


def test_profile_pages_are_added_to_the_site(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path / 'profiles', 'places',
        _PROFILE_PAGES,
        templates={'place.html.tpl': '---toml\n[templating]\nextends = "opm/layout.html.tpl"\n---\n'},
    )
    project = _project(tmp_path, '[project]\nprofiles = ["places"]\n' + _PAGES_TOML[:0])
    # The profile's page joined the project's own (none here beyond the profile's).
    paths = {page.path for page in project.config.pages}
    assert paths == {'places/{xml_id}.html'}
    [page] = project.config.pages
    # template resolves against the profile dir, source against the project root.
    assert page.template == profile / 'templates' / 'place.html.tpl'
    assert page.source == tmp_path / 'register.xml'

    run = project.chunk(tmp_path / 'doc.xml')
    assert 'Kraków' in (run.output_dir / 'places' / 'pl1.html').read_text(encoding='utf-8')


def test_project_page_wins_over_a_profile_page_with_the_same_path(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'places', _PROFILE_PAGES)
    project = _project(tmp_path, (
        '[project]\nprofiles = ["places"]\n\n'
        '[[pages]]\npath = "places/{xml_id}.html"\nsource = "doc.xml"\nxpath = "//body/div"\n'
    ))
    [page] = project.config.pages
    assert page.source == tmp_path / 'doc.xml'
    assert page.xpath == '//body/div'

    run = project.chunk(tmp_path / 'doc.xml')
    # The project's page rendered the doc's divs, not the register's places.
    assert (run.output_dir / 'places' / 'a.html').is_file()
    assert not (run.output_dir / 'places' / 'pl1.html').exists()


def test_profile_page_errors_name_the_profile(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'places', '[[pages]]\npath = "../x.html"\n')
    with pytest.raises(ValueError, match="profile 'places'.*relative and stay below"):
        _project(tmp_path, '[project]\nprofiles = ["places"]\n')


def test_pages_are_merged_once_across_with_config(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'places', _PROFILE_PAGES)
    project = _project(tmp_path, '[project]\nprofiles = ["places"]\n')
    again = project.with_config()
    assert len(again.config.pages) == 1


# ── menubar ──────────────────────────────────────────────────────────────────

def _layout_page(tmp_path: Path) -> Path:
    """A page template on the packaged layout, which renders the menubar."""
    page = tmp_path / 'page.html.tpl'
    page.write_text('---toml\n[templating]\nextends = "opm/layout.html.tpl"\n---\n', encoding='utf-8')
    return page


def test_menubar_reads_context_menu_items_only(tmp_path: Path) -> None:
    # Pages do not add themselves to the menubar: only an explicit
    # [context.menu] entry does.
    project = _project(tmp_path, _PAGES_TOML + (
        '\n[context.menu]\nitems = [{ label = "About", url = "about.html" }]\n'
    ))
    assert project.config.template_context['menu']['items'] == [
        {'label': 'About', 'url': 'about.html'},
    ]

    run = project.chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    # From a chunk page (one level down) the link carries the ../ prefix…
    chunk_page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'href="../about.html"' in chunk_page
    assert 'places/index.html' not in chunk_page  # no Places entry without [context.menu]
    # … from the index (at the root) it does not.
    index = run.index_file.read_text(encoding='utf-8')
    assert 'href="about.html"' in index
    # … and from a page in places/ as well.
    place = (run.output_dir / 'places' / 'pl1.html').read_text(encoding='utf-8')
    assert 'href="../about.html"' in place


def test_a_disabled_page_is_not_rendered(tmp_path: Path) -> None:
    project = _project(tmp_path, (
        '[[pages]]\npath = "about.html"\ntemplate = "templates/about.html.tpl"\nmenu = "About"\nenabled = false\n'
    ))
    run = project.chunk(tmp_path / 'doc.xml')
    assert not (run.output_dir / 'about.html').exists()
    assert run.pages == ()


def test_a_profile_page_with_a_missing_source_is_skipped(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'places', _PROFILE_PAGES)
    # No register.xml at the profile's default source.
    _project(tmp_path, '[project]\nprofiles = ["places"]\n')
    (tmp_path / 'register.xml').unlink()
    project = Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["places"]\n\n[transform]\nodd = "tiny.odd"\n\n[chunking]\n'
        'odd = "tiny.odd"\nxpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
    )))
    [page] = project.config.pages
    assert page.from_profile
    run = project.chunk(tmp_path / 'doc.xml')
    assert not (run.output_dir / 'places').exists()
    assert run.pages == ()


def test_an_app_page_with_a_missing_source_is_an_error(tmp_path: Path) -> None:
    project = _project(tmp_path, (
        '[[pages]]\npath = "places/{xml_id}.html"\nsource = "nope.xml"\nxpath = "//place"\n'
    ))
    with pytest.raises(FileNotFoundError, match='source not found'):
        project.chunk(tmp_path / 'doc.xml')


# ── the bundled registers profile ────────────────────────────────────────────

def test_registers_profile_adds_the_register_pages(tmp_path: Path) -> None:
    registers = tmp_path / 'data' / 'registers'
    registers.mkdir(parents=True)
    (registers / 'places.xml').write_text(_REGISTER, encoding='utf-8')
    (registers / 'persons.xml').write_text(_PERSONS, encoding='utf-8')
    project = _project(tmp_path, (
        '[project]\nprofiles = ["registers"]\n\n'
        # The menubar entries are the project's explicit choice.
        '[context.menu]\nitems = [\n'
        '    { label = "People", url = "people/index.html" },\n'
        '    { label = "Places", url = "places/index.html" },\n'
        ']\n'
    ))
    paths = {page.path for page in project.config.pages}
    assert paths == {
        'places/index.html', 'places/{xml_id}.html',
        'people/index.html', 'people/{xml_id}.html',
    }

    run = project.chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    site = run.output_dir
    assert 'Kraków' in (site / 'places' / 'pl1.html').read_text(encoding='utf-8')
    assert 'Adam Mickiewicz' in (site / 'people' / 'p1.html').read_text(encoding='utf-8')

    # The overview: the ODD's register-overview entries, sorted under their
    # initial, each linking to its page relative to the overview.
    places = (site / 'places' / 'index.html').read_text(encoding='utf-8')
    assert 'id="letter-K"' in places and 'id="letter-W"' in places
    assert places.index('Kraków') < places.index('Warszawa')
    assert 'href="pl1.html"' in places and 'href="places/pl1"' not in places
    people = (site / 'people' / 'index.html').read_text(encoding='utf-8')
    assert 'href="p2.html"' in people and 'Juliusz Słowacki' in people

    # An entry lists the documents mentioning it; one nobody mentions does not.
    krakow = (site / 'places' / 'pl1.html').read_text(encoding='utf-8')
    assert 'Mentioned in' in krakow and 'href="../doc.xml/001.html"' in krakow
    assert '<a href="index.html">Places</a>' in krakow
    assert 'Mentioned in' not in (site / 'places' / 'pl2.html').read_text(encoding='utf-8')
    # The explicit [context.menu] entries are in the menubar of every page,
    # prefixed with the page's path back to the root.
    chunk_page = (site / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'href="../places/index.html"' in chunk_page
    assert 'href="../people/index.html"' in chunk_page
    assert '>Places<' in chunk_page and '>People<' in chunk_page
    assert 'href="../people/index.html"' in (site / 'people' / 'p1.html').read_text(encoding='utf-8')


def test_registers_profile_skips_a_register_whose_source_is_missing(tmp_path: Path) -> None:
    # Only the places register exists: the people pages are skipped, the
    # places pages are built.
    registers = tmp_path / 'data' / 'registers'
    registers.mkdir(parents=True)
    (registers / 'places.xml').write_text(_REGISTER, encoding='utf-8')
    project = _project(tmp_path, '[project]\nprofiles = ["registers"]\n')
    run = project.chunk(tmp_path / 'doc.xml')
    assert (run.output_dir / 'places' / 'pl1.html').is_file()
    assert not (run.output_dir / 'people').exists()


def test_registers_profile_without_registers_builds_no_pages(tmp_path: Path) -> None:
    project = _project(tmp_path, '[project]\nprofiles = ["registers"]\n')
    run = project.chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    assert not (run.output_dir / 'places').exists()
    assert not (run.output_dir / 'people').exists()
    assert run.pages == ()
    chunk_page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'Places' not in chunk_page and 'People' not in chunk_page


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_no_pages_and_page_flags(tmp_path: Path, monkeypatch) -> None:
    from opm.cli import main

    _project(tmp_path, _PAGES_TOML)
    monkeypatch.chdir(tmp_path)

    rc = main(['chunk', 'doc.xml', '-c', 'opm.toml', '--no-pages'])
    assert rc == 0
    site = tmp_path / 'site'
    assert (site / 'doc.xml' / '001.html').is_file()
    assert not (site / 'about.html').exists()

    rc = main(['chunk', 'doc.xml', '-c', 'opm.toml', '--page', 'places', '--force'])
    assert rc == 0
    assert not (site / 'about.html').exists()
    assert (site / 'places' / 'pl1.html').is_file()

    rc = main(['chunk', 'doc.xml', '-c', 'opm.toml', '--force'])
    assert rc == 0
    assert (site / 'about.html').is_file()
    assert (site / 'places' / 'pl1.html').is_file()
