"""Profiles: reusable templates and context a project switches on in ``[project] profiles``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from opm import Project
from opm.config import load_project_config
from opm.template_rendering import _searchpaths

_MODELS = (
    '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
    '<elementSpec ident="text"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="body"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="div"><model behaviour="block"/></elementSpec>'
    '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
)

_DOC = (
    '<doc><text><body>'
    '<div type="chunk" xml:id="a"><p>The first chunk has a paragraph long enough to be indexed.</p></div>'
    '<div type="chunk" xml:id="b"><p>The second chunk has a paragraph long enough to be indexed too.</p></div>'
    '</body></text></doc>'
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


# ── configuration ────────────────────────────────────────────────────────────

def test_profiles_are_read_from_the_project_table(tmp_path: Path) -> None:
    cfg = load_project_config(_config(tmp_path, '[project]\nprofiles = ["pagefind", "other"]\n'))
    assert cfg.profiles == ('pagefind', 'other')


def test_a_single_profile_may_be_a_string(tmp_path: Path) -> None:
    cfg = load_project_config(_config(tmp_path, '[project]\nprofiles = "pagefind"\n'))
    assert cfg.profiles == ('pagefind',)


def test_a_top_level_profiles_key_is_not_read(tmp_path: Path) -> None:
    cfg = load_project_config(_config(tmp_path, 'profiles = ["pagefind"]\n'))
    assert cfg.profiles == ()


# ── finding profiles ─────────────────────────────────────────────────────────

def test_a_project_without_profiles_loads_none(tmp_path: Path) -> None:
    assert Project.load(_config(tmp_path, ''))._profiles == ()


def test_bundled_profile_is_found(tmp_path: Path) -> None:
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["pagefind"]\n'))
    [(profile, path)] = project._profiles
    assert profile.name == 'pagefind'
    assert path.parent.name == 'profiles' and path.parent.parent.name == 'resources'


def test_user_profile_wins_over_bundled_one(tmp_path: Path, _isolated: Path) -> None:
    user = _profile(_isolated / '.opm' / 'profiles', 'pagefind', 'description = "mine"\n')
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["pagefind"]\n'))
    [(profile, path)] = project._profiles
    assert path == user
    assert profile.description == 'mine'


def test_project_profile_wins_over_user_and_bundled_ones(tmp_path: Path, _isolated: Path) -> None:
    _profile(_isolated / '.opm' / 'profiles', 'pagefind', 'description = "user"\n')
    local = _profile(tmp_path / 'profiles', 'pagefind', 'description = "project"\n')
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["pagefind"]\n'))
    [(profile, path)] = project._profiles
    assert path == local
    assert profile.description == 'project'


def test_profile_name_defaults_to_its_directory(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'nameless')
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["nameless"]\n'))
    assert project._profiles[0][0].name == 'nameless'


def test_unknown_profile_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Profile 'missing' not found"):
        Project.load(_config(tmp_path, '[project]\nprofiles = ["missing"]\n'))


def test_profile_without_its_toml_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / 'profiles' / 'broken').mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match='opm-profile.toml'):
        Project.load(_config(tmp_path, '[project]\nprofiles = ["broken"]\n'))


def test_a_key_below_the_wrong_table_is_reported(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'misplaced', '[templating]\nuse = ["x.html.tpl"]\nassets = ["a.css"]\n')
    with pytest.raises(ValueError, match=r'unknown key\(s\) assets in \[templating\]'):
        Project.load(_config(tmp_path, '[project]\nprofiles = ["misplaced"]\n'))


# ── context ──────────────────────────────────────────────────────────────────

def test_profile_context_is_added_to_the_project_context(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'extra', '[context]\nextra_flag = true\n')
    project = Project.load(_config(
        tmp_path, '[project]\nprofiles = ["extra"]\n\n[context]\nsite_name = "Edition"\n',
    ))
    assert project.config.template_context['extra_flag'] is True
    assert project.config.template_context['site_name'] == 'Edition'


def test_project_context_wins_over_profile_context(tmp_path: Path) -> None:
    """A profile supplies defaults; the project's own ``[context]`` overrides them."""
    project = Project.load(_config(
        tmp_path, '[project]\nprofiles = ["pagefind"]\n\n[context.features.pagefind]\nbase = "find"\n',
    ))
    pagefind = project.config.template_context['features']['pagefind']
    assert pagefind == {'enabled': True, 'base': 'find'}


def test_later_profile_context_wins_over_earlier_one(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'one', '[context]\nvalue = "one"\n')
    _profile(tmp_path / 'profiles', 'two', '[context]\nvalue = "two"\n')
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["one", "two"]\n'))
    assert project.config.template_context['value'] == 'two'


# ── templates ────────────────────────────────────────────────────────────────

def test_profile_templates_are_searched_after_the_project_ones(tmp_path: Path) -> None:
    profile = _profile(tmp_path / 'profiles', 'extra', templates={'part.html.tpl': 'profile'})
    (tmp_path / 'templates').mkdir()
    page = tmp_path / 'templates' / 'page.html.tpl'
    page.write_text('', encoding='utf-8')
    project = Project.load(_config(tmp_path, '[project]\nprofiles = ["extra"]\n'))

    paths = _searchpaths(page, project)
    assert paths.index(str(page.parent.resolve())) < paths.index(str((profile / 'templates').resolve()))


def test_page_template_uses_a_profile_template(tmp_path: Path) -> None:
    """A page ``use``s a template the profile ships, and its blocks fill the page."""
    _profile(
        tmp_path / 'profiles', 'extra',
        templates={'extra.html.tpl': (
            '<template>[% template body_end %]<p id="from-profile"/>[% endtemplate %]</template>'
        )},
    )
    (tmp_path / 'tiny.odd').write_text(_odd(), encoding='utf-8')
    (tmp_path / 'templates').mkdir()
    (tmp_path / 'templates' / 'page.html.tpl').write_text(
        '---toml\n[templating]\nextends = "opm/layout.html.tpl"\nuse = ["extra.html.tpl"]\n---\n',
        encoding='utf-8',
    )
    (tmp_path / 'doc.xml').write_text(_DOC, encoding='utf-8')
    project = Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["extra"]\n\n'
        '[chunking]\nodd = "tiny.odd"\ntemplate = "templates/page.html.tpl"\n'
        'xpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
    )))

    run = project.chunk(tmp_path / 'doc.xml')
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'id="from-profile"' in page


def _chunking_project(tmp_path: Path, project_toml: str = '') -> Project:
    (tmp_path / 'tiny.odd').write_text(_odd(), encoding='utf-8')
    (tmp_path / 'doc.xml').write_text(_DOC, encoding='utf-8')
    return Project.load(_config(tmp_path, project_toml + (
        '\n[transform]\nodd = "tiny.odd"\n\n[chunking]\nodd = "tiny.odd"\n'
        'xpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
    )))


def _layout_page(tmp_path: Path) -> Path:
    """A chunk page template on the packaged layout, which has the blocks profiles fill."""
    page = tmp_path / 'page.html.tpl'
    page.write_text('---toml\n[templating]\nextends = "opm/layout.html.tpl"\n---\n', encoding='utf-8')
    return page


def test_pagefind_profile_adds_search_to_the_site(tmp_path: Path) -> None:
    plain = _chunking_project(tmp_path).chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    assert 'pagefind' not in plain.index_file.read_text(encoding='utf-8')

    run = _chunking_project(tmp_path, '[project]\nprofiles = ["pagefind"]\n').chunk(
        tmp_path / 'doc.xml', overwrite=True, template=_layout_page(tmp_path),
    )
    index = run.index_file.read_text(encoding='utf-8')
    assert '<pagefind-modal-trigger></pagefind-modal-trigger>' in index
    assert '<pagefind-modal></pagefind-modal>' in index
    assert 'src="assets/search/pagefind-component-ui.js"' in index
    # Every page gets the blocks, one level down with the path adjusted.
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'src="../assets/search/pagefind-component-ui.js"' in page

    search = run.output_dir / 'assets' / 'search'
    assert (search / 'pagefind-component-ui.js').is_file()
    entry = json.loads((search / 'pagefind-entry.json').read_text(encoding='utf-8'))
    assert sum(lang['page_count'] for lang in entry['languages'].values()) > 0


def test_profile_blocks_can_be_switched_off(tmp_path: Path) -> None:
    run = _chunking_project(
        tmp_path, '[project]\nprofiles = ["pagefind"]\n\n[context.features.pagefind]\nenabled = false\n',
    ).chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    assert 'pagefind-modal' not in (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')


def test_pagefind_search_folder_follows_the_context(tmp_path: Path) -> None:
    pytest.importorskip('pagefind.index')
    run = _chunking_project(
        tmp_path, '[project]\nprofiles = ["pagefind"]\n\n[context.features.pagefind]\nbase = "find"\n',
    ).chunk(tmp_path / 'doc.xml')
    assert (run.output_dir / 'assets' / 'find' / 'pagefind-entry.json').is_file()
    assert 'src="assets/find/pagefind-component-ui.js"' in run.index_file.read_text(encoding='utf-8')


def test_pagefind_profile_without_the_package_says_how_to_install_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, 'pagefind.index', None)
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["pagefind"]\n')
    with pytest.raises(RuntimeError, match='Reinstall opm'):
        project.chunk(tmp_path / 'doc.xml')


# ── assets and fragments ─────────────────────────────────────────────────────

def test_profile_assets_are_copied_and_linked_before_the_projects(tmp_path: Path) -> None:
    profile = _profile(tmp_path / 'profiles', 'styled', 'assets = ["assets/styled.css"]\n')
    (profile / 'assets').mkdir()
    (profile / 'assets' / 'styled.css').write_text('.styled {}', encoding='utf-8')
    (tmp_path / 'own.css').write_text('.own {}', encoding='utf-8')
    _chunking_project(tmp_path)
    project = Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["styled"]\n\n'
        '[chunking]\nodd = "tiny.odd"\nxpath = "//div"\noutput_dir = "site"\nassets = ["own.css"]\n'
    )))

    run = project.chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))

    assert (run.output_dir / 'assets' / 'styled.css').is_file()
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert page.index('../assets/styled.css') < page.index('../assets/own.css')


def test_profile_assets_are_added_once(tmp_path: Path) -> None:
    profile = _profile(tmp_path / 'profiles', 'styled', 'assets = ["assets/styled.css"]\n')
    (profile / 'assets').mkdir()
    (profile / 'assets' / 'styled.css').write_text('', encoding='utf-8')
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["styled"]\n')
    again = project.with_config()
    assert again.config.chunking.assets.count(profile / 'assets' / 'styled.css') == 1
    assert again.config.web_assets.count(profile / 'assets' / 'styled.css') == 1


_FRAGMENT_PROFILE = (
    '[[chunking.fragments]]\nname = "whole"\nscope = "global"\nxpath = "//body"\n'
)


def test_profile_fragments_are_added_to_every_run(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'frag', _FRAGMENT_PROFILE)
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["frag"]\n')
    [fragment] = project.config.chunking.fragments
    assert (fragment.name, fragment.scope, fragment.xpath) == ('whole', 'global', '//body')
    assert project.config.chunking_runs[0].fragments == [fragment]

    project.chunk(tmp_path / 'doc.xml')
    manifest = json.loads((tmp_path / 'site' / 'doc.xml' / 'manifest.json').read_text(encoding='utf-8'))
    assert 'second chunk' in manifest['fragments']['whole']


def test_project_fragment_wins_over_a_profile_fragment_of_the_same_name(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'frag', _FRAGMENT_PROFILE)
    (tmp_path / 'tiny.odd').write_text(_odd(), encoding='utf-8')
    project = Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["frag"]\n\n'
        '[chunking]\nodd = "tiny.odd"\nxpath = "//div"\n\n'
        '[[chunking.fragments]]\nname = "whole"\nxpath = "."\n'
    )))
    [fragment] = project.config.chunking.fragments
    assert (fragment.scope, fragment.xpath) == ('per-chunk', '.')


# ── hooks ────────────────────────────────────────────────────────────────────

_RECORDING_HOOK = """
calls = []

def record(project, run):
    calls.append((project, run, run.index_file.is_file()))
"""


def test_after_chunking_hook_runs_once_when_the_site_is_written(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'rec', '[hooks]\nafter_chunking = "hook.py:record"\n')
    (tmp_path / 'profiles' / 'rec' / 'hook.py').write_text(_RECORDING_HOOK, encoding='utf-8')
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["rec"]\n')

    run = project.chunk(tmp_path / 'doc.xml')

    calls = sys.modules['opm_profile_rec_hook'].calls
    assert calls == [(project, run, True)]
    assert run.document_dirs == {tmp_path / 'doc.xml': 'doc.xml'}


def test_hooks_run_in_profile_order_and_same_named_files_do_not_clash(tmp_path: Path) -> None:
    log = tmp_path / 'log.txt'
    for name in ('one', 'two'):
        _profile(tmp_path / 'profiles', name, '[hooks]\nafter_chunking = ["hook.py:run"]\n')
        (tmp_path / 'profiles' / name / 'hook.py').write_text(
            f'def run(project, run):\n'
            f'    with open({str(log)!r}, "a") as f:\n'
            f'        f.write({name!r} + "\\n")\n',
            encoding='utf-8',
        )
    _chunking_project(tmp_path, '[project]\nprofiles = ["two", "one"]\n').chunk(tmp_path / 'doc.xml')
    assert log.read_text(encoding='utf-8').split() == ['two', 'one']


def test_unknown_hook_name_is_reported(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'bad', '[hooks]\nbefore_lunch = "hook.py:eat"\n')
    with pytest.raises(ValueError, match="unknown hook 'before_lunch'"):
        Project.load(_config(tmp_path, '[project]\nprofiles = ["bad"]\n'))


def test_hook_entry_must_name_a_function(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'bad', '[hooks]\nafter_chunking = "hook.py"\n')
    with pytest.raises(ValueError, match="'file.py:function'"):
        Project.load(_config(tmp_path, '[project]\nprofiles = ["bad"]\n'))


def test_missing_hook_file_is_reported(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'bad', '[hooks]\nafter_chunking = "nope.py:run"\n')
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["bad"]\n')
    with pytest.raises(FileNotFoundError, match='hook file not found'):
        project.chunk(tmp_path / 'doc.xml')


def test_missing_hook_function_is_reported(tmp_path: Path) -> None:
    _profile(tmp_path / 'profiles', 'bad', '[hooks]\nafter_chunking = "hook.py:nope"\n')
    (tmp_path / 'profiles' / 'bad' / 'hook.py').write_text('', encoding='utf-8')
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["bad"]\n')
    with pytest.raises(AttributeError, match="no function 'nope'"):
        project.chunk(tmp_path / 'doc.xml')


# ── bundled profiles ─────────────────────────────────────────────────────────

_NAV_MODELS = (
    '<elementSpec ident="doc">'
    '<model predicate="$parameters?mode = \'edition-navigation\'" behaviour="pass-through">'
    '<param name="previous" value="string(@prev)"/><param name="next" value="string(@next)"/>'
    '<pb:template xml:space="preserve"><nav hidden="hidden" data-previous="[[previous]]" '
    'data-next="[[next]]"></nav></pb:template></model>'
    '<model behaviour="document"/></elementSpec>'
)


def test_edition_navigation_links_neighbouring_documents(tmp_path: Path) -> None:
    (tmp_path / 'tiny.odd').write_text(
        _odd(models=_NAV_MODELS + _MODELS.split('</elementSpec>', 1)[1]), encoding='utf-8',
    )
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'a.xml').write_text(_DOC.replace('<doc>', '<doc next="b.xml">'), encoding='utf-8')
    (docs / 'b.xml').write_text(_DOC.replace('<doc>', '<doc prev="a" next="missing">'), encoding='utf-8')
    project = Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["edition-navigation"]\n\n'
        '[context.features.edition-navigation]\nnext_label = "Onward"\n\n'
        '[transform]\nodd = "tiny.odd"\n\n'
        '[chunking]\nodd = "tiny.odd"\nxpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
    )))

    run = project.chunk(docs, template=_layout_page(tmp_path))

    a = (run.output_dir / 'a.xml' / '001.html').read_text(encoding='utf-8')
    b = (run.output_dir / 'b.xml' / '001.html').read_text(encoding='utf-8')
    assert 'class="edition-nav"' in a and '../assets/edition-navigation.css' in a
    assert 'href="../b.xml/001.html"' in a and 'Onward' in a
    assert 'href="../a.xml/001.html"' in b
    # A neighbour this site has no page for stays unlinked.
    assert 'missing' not in b


_REGISTER_MODELS = (
    '<elementSpec ident="doc">'
    '<model predicate="$parameters?mode = \'register\'" behaviour="pass-through">'
    '<param name="what" value="($parameters?category, \'all\')[1]"/>'
    '<pb:template xml:space="preserve"><ul class="reg"><li>[[what]]</li></ul></pb:template></model>'
    '<model behaviour="document"/></elementSpec>'
)


def _register_project(tmp_path: Path, toml: str) -> Project:
    (tmp_path / 'tiny.odd').write_text(
        _odd(models=_REGISTER_MODELS + _MODELS.split('</elementSpec>', 1)[1]), encoding='utf-8',
    )
    (tmp_path / 'doc.xml').write_text(_DOC, encoding='utf-8')
    return Project.load(_config(tmp_path, (
        '[project]\nprofiles = ["registers"]\n\n' + toml + '\n'
        '[transform]\nodd = "tiny.odd"\n\n'
        '[chunking]\nodd = "tiny.odd"\nxpath = "//body/div[@type=\'chunk\']"\noutput_dir = "site"\n'
        '[[chunking.fragments]]\nname = "register_people"\nxpath = "/doc"\n'
        'parameters = { mode = "register", category = "people" }\n'
        '[[chunking.fragments]]\nname = "register_places"\nxpath = "/doc"\n'
        'parameters = { mode = "register", category = "places" }\n'
    )))


def _after_column(page: str) -> str:
    return page.split('<aside class="after"', 1)[1].split('</aside>', 1)[0]


def test_registers_profile_shows_one_panel_by_default(tmp_path: Path) -> None:
    run = _register_project(tmp_path, '').chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    after = _after_column(page)
    assert '<h2 class="register-panel__title">Register</h2>' in after
    assert '<li>all</li>' in after and 'register-tabs' not in after
    assert '../assets/registers.css' in page


def test_registers_profile_shows_categories_as_tabs_in_the_chosen_column(tmp_path: Path) -> None:
    run = _register_project(tmp_path, (
        '[context.features.register]\ncolumn = "before"\n'
        'categories = ["people", "places", "works"]\n'
        'category_labels = { places = "Orte" }\n'
    )).chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    before = page.split('<aside class="before"', 1)[1].split('</aside>', 1)[0]
    assert 'register-panel' not in _after_column(page)
    # "works" has no fragment, so no tab; the others are labelled.
    assert before.count('class="register-tabs__tab"') == 2
    assert '>People</label>' in before and '>Orte</label>' in before
    assert '<li>people</li>' in before and '<li>places</li>' in before
    assert 'register-panel__title' not in before


def _iiif_project(tmp_path: Path, toml: str = '') -> Project:
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["iiif"]\n\n' + toml)
    return project


def test_iiif_profile_adds_pb_tify_beside_the_text(tmp_path: Path) -> None:
    run = _iiif_project(tmp_path).chunk(
        tmp_path / 'doc.xml', template=_layout_page(tmp_path), webcomponents=True,
    )
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert '<pb-tify subscribe="transcription" emit="transcription">' in _after_column(page)
    # pb-tify.js comes from the same place as the pb-components bundle.
    assert '@teipublisher/pb-components@3.6.8/dist/pb-tify.js' in page
    assert '<pb-page endpoint="." api-version="1.0.0"' in page
    assert 'iiif--with-facs' in page and '../assets/iiif.css' in page
    # The collection index has no text, so no viewer.
    assert 'iiif-facs' not in run.index_file.read_text(encoding='utf-8')


def test_iiif_profile_can_use_pb_facsimile(tmp_path: Path) -> None:
    run = _iiif_project(tmp_path, (
        '[context.features.iiif]\nviewer = "pb-facsimile"\nbase_uri = "https://images.test/iiif/"\n'
    )).chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path), webcomponents=True)
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert '<pb-facsimile base-uri="https://images.test/iiif/"' in _after_column(page)
    assert 'pb-tify' not in page


def test_iiif_profile_needs_web_components(tmp_path: Path) -> None:
    run = _iiif_project(tmp_path).chunk(tmp_path / 'doc.xml', template=_layout_page(tmp_path))
    assert 'iiif-facs' not in (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')


def _odd(models: str = _MODELS) -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:pb="http://teipublisher.com/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        f'<text><body><schemaSpec ident="tiny" ns="">{models}</schemaSpec></body></text>'
        '</TEI>'
    )
