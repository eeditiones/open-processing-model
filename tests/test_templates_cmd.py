# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`opm templates list|show`: reading the templates without copying them."""

from __future__ import annotations

from pathlib import Path

import pytest

from opm.cli import main
from opm.template_rendering import packaged_templates_dir, template_header, template_summary

_LAYOUT = 'opm/layout.html.tpl'


@pytest.fixture
def wide(monkeypatch) -> None:
    """A wide terminal, so rich does not wrap the table."""
    monkeypatch.setenv('COLUMNS', '200')


def _project(tmp_path: Path, monkeypatch, *, profiles: str = '') -> Path:
    dest = tmp_path / 'edition'
    args = ['init', str(dest)] + (['-p', profiles] if profiles else [])
    assert main(args) == 0
    monkeypatch.chdir(dest)
    return dest


def test_list_outside_a_project_shows_opms_templates(tmp_path: Path, monkeypatch, capsys, wide) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['templates', 'list']) == 0
    out = capsys.readouterr().out
    assert _LAYOUT in out and 'The page layout' in out
    assert 'opm/defaults.toml' in out
    # No profile is in use outside a project.
    assert 'iiif.html.tpl' not in out
    # Square brackets in a summary are text, not rich markup.
    assert "a project's [context] in opm.toml" in out


def test_list_shows_the_projects_profiles_and_copies_first(tmp_path: Path, monkeypatch, capsys, wide) -> None:
    dest = _project(tmp_path, monkeypatch, profiles='iiif')
    copy = dest / 'templates' / 'opm' / 'layout.html.tpl'
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text('[# My own layout. #]\n', encoding='utf-8')
    capsys.readouterr()

    assert main(['templates', 'list']) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith(_LAYOUT + ' ')]
    assert len(lines) == 2
    assert 'project' in lines[0] and 'My own layout.' in lines[0]
    assert 'opm' in lines[1] and '(overridden)' in lines[1]

    assert main(['templates', 'list']) == 0
    out = capsys.readouterr().out
    assert 'iiif.html.tpl' in out and 'profile iiif' in out

    assert main(['templates', 'show', _LAYOUT, '--path']) == 0
    assert Path(capsys.readouterr().out.strip()) == copy.resolve()


def test_list_shows_the_projects_page_templates_only_with_all(tmp_path: Path, monkeypatch, capsys, wide) -> None:
    dest = _project(tmp_path, monkeypatch)
    own = sorted(p.name for p in (dest / 'templates').glob('*.html.tpl'))
    assert own
    capsys.readouterr()
    assert main(['templates', 'list']) == 0
    assert own[0] not in capsys.readouterr().out
    assert main(['templates', 'list', '--all']) == 0
    assert own[0] in capsys.readouterr().out


def test_show_prints_the_file_unchanged(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['templates', 'show', _LAYOUT]) == 0
    packaged = packaged_templates_dir() / 'opm' / 'layout.html.tpl'
    assert capsys.readouterr().out == packaged.read_text(encoding='utf-8')


def test_show_header_prints_only_the_leading_comment(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['templates', 'show', _LAYOUT, '--header']) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith('[#') and out.endswith('#]')
    assert 'menu.items' in out
    assert '<header' not in out


def test_show_an_unknown_template_suggests_names(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['templates', 'show', 'layout.html']) == 1
    assert 'opm/layout.html.tpl' in capsys.readouterr().err


@pytest.mark.parametrize(('text', 'header', 'summary'), [
    ('[#\n  SPDX-License-Identifier: CC0-1.0\n\n  A page. More.\n#]\n<p/>', '[#\n  SPDX-License-Identifier: CC0-1.0\n\n  A page. More.\n#]', 'A page.'),
    ('/* Layout: grid. */\nbody {}', '/* Layout: grid. */', 'Layout: grid.'),
    ('# Defaults for\n# the context.\n\n[a]\n', '# Defaults for\n# the context.', 'Defaults for the context.'),
    ('// Typst shell\n#let x = 1\n', '// Typst shell', 'Typst shell'),
    ('<p/>', None, ''),
])
def test_header_and_summary_by_kind(tmp_path: Path, text: str, header: str | None, summary: str) -> None:
    path = tmp_path / 'file.tpl'
    path.write_text(text, encoding='utf-8')
    assert template_header(path) == header
    assert template_summary(path) == summary
