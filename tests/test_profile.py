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
        tmp_path, '[project]\nprofiles = ["pagefind"]\n\n[context]\npagefind_base = "find"\n',
    ))
    assert project.config.template_context['pagefind_base'] == 'find'
    assert project.config.template_context['pagefind_enabled'] is True


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


def test_pagefind_profile_adds_search_to_the_site(tmp_path: Path) -> None:
    pytest.importorskip('pagefind.index')
    plain = _chunking_project(tmp_path).chunk(tmp_path / 'doc.xml')
    assert 'pagefind' not in plain.index_file.read_text(encoding='utf-8')

    # Pages opt in by using the profile's template; the index does so itself.
    page_template = tmp_path / 'page.html.tpl'
    page_template.write_text(
        '---toml\n[templating]\nextends = "opm/layout.html.tpl"\nuse = ["pagefind.html.tpl"]\n---\n',
        encoding='utf-8',
    )
    run = _chunking_project(tmp_path, '[project]\nprofiles = ["pagefind"]\n').chunk(
        tmp_path / 'doc.xml', overwrite=True, template=page_template,
    )
    index = run.index_file.read_text(encoding='utf-8')
    assert '<!-- pagefind-enabled -->' in index
    assert '<pagefind-modal></pagefind-modal>' in index
    assert 'src="assets/search/pagefind-component-ui.js"' in index
    # Pages one level down reach the same files.
    page = (run.output_dir / 'doc.xml' / '001.html').read_text(encoding='utf-8')
    assert 'src="../assets/search/pagefind-component-ui.js"' in page

    search = run.output_dir / 'assets' / 'search'
    assert (search / 'pagefind-component-ui.js').is_file()
    entry = json.loads((search / 'pagefind-entry.json').read_text(encoding='utf-8'))
    assert sum(lang['page_count'] for lang in entry['languages'].values()) > 0


def test_pagefind_search_folder_follows_the_context(tmp_path: Path) -> None:
    pytest.importorskip('pagefind.index')
    run = _chunking_project(
        tmp_path, '[project]\nprofiles = ["pagefind"]\n\n[context]\npagefind_base = "find"\n',
    ).chunk(tmp_path / 'doc.xml')
    assert (run.output_dir / 'assets' / 'find' / 'pagefind-entry.json').is_file()
    assert 'src="assets/find/pagefind-component-ui.js"' in run.index_file.read_text(encoding='utf-8')


def test_pagefind_profile_without_the_package_says_how_to_install_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, 'pagefind.index', None)
    project = _chunking_project(tmp_path, '[project]\nprofiles = ["pagefind"]\n')
    with pytest.raises(RuntimeError, match='Reinstall opm'):
        project.chunk(tmp_path / 'doc.xml')


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


def _odd() -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        f'<text><body><schemaSpec ident="tiny" ns="">{_MODELS}</schemaSpec></body></text>'
        '</TEI>'
    )
