from __future__ import annotations

import json
from pathlib import Path

import pytest

import opm.scaffold as scaffold
from opm.cli import main
from opm.update import (
    CONFLICT_SUFFIX,
    MANIFEST_PATH,
    UpdateError,
    file_hash,
    read_manifest,
    update_project,
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))


SHELL = 'templates/handbook.html.tpl'
SHELL_SRC = 'scaffold/templates/handbook.html.tpl'


def _init(tmp_path: Path, *args: str) -> Path:
    dest = tmp_path / 'project'
    assert main(['init', str(dest), '--vocabulary', 'docbook', *args]) == 0
    return dest


def _upstream(monkeypatch, src_rel: str, extra: bytes = b'<!-- new in opm -->\n') -> bytes:
    """Make the packaged resource *src_rel* look as if a newer opm changed it."""
    original = scaffold._read_packaged

    def patched(rel: str) -> bytes:
        data = original(rel)
        return data + extra if rel == src_rel else data

    monkeypatch.setattr(scaffold, '_read_packaged', patched)
    return original(src_rel) + extra


def _actions(report) -> dict[str, str]:
    return {c.path: c.action for c in report.files}


def test_init_writes_manifest(tmp_path: Path) -> None:
    dest = _init(tmp_path, '--profile', 'registers')
    manifest = read_manifest(dest)
    assert manifest is not None
    assert manifest.options['vocabulary'] == 'docbook'
    assert manifest.options['profiles'] == ['registers']
    assert manifest.files[SHELL] == file_hash((dest / SHELL).read_bytes())
    assert manifest.files['opm.toml'] == file_hash((dest / 'opm.toml').read_bytes())
    assert 'registers' in manifest.profiles


def test_fresh_project_is_up_to_date(tmp_path: Path) -> None:
    dest = _init(tmp_path)
    report = update_project(dest)
    assert report.files == []
    assert report.profiles == []


def test_untouched_file_is_updated(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    new = _upstream(monkeypatch, SHELL_SRC)

    report = update_project(dest)
    assert _actions(report) == {SHELL: 'updated'}
    assert (dest / SHELL).read_bytes() != new  # dry run writes nothing

    update_project(dest, apply=True)
    assert (dest / SHELL).read_bytes() == new
    assert read_manifest(dest).files[SHELL] == file_hash(new)
    assert update_project(dest).files == []


def test_edited_file_conflicts(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    mine = (dest / SHELL).read_text(encoding='utf-8') + '<!-- mine -->\n'
    (dest / SHELL).write_text(mine, encoding='utf-8')
    new = _upstream(monkeypatch, SHELL_SRC)

    report = update_project(dest, apply=True)
    assert _actions(report) == {SHELL: 'conflict'}
    assert (dest / SHELL).read_text(encoding='utf-8') == mine
    assert (dest / (SHELL + CONFLICT_SUFFIX)).read_bytes() == new
    # Still a conflict until resolved.
    assert _actions(update_project(dest)) == {SHELL: 'conflict'}

    update_project(dest, resolve=[SHELL + CONFLICT_SUFFIX], apply=True)
    assert not (dest / (SHELL + CONFLICT_SUFFIX)).exists()
    assert (dest / SHELL).read_text(encoding='utf-8') == mine
    assert update_project(dest).files == []


def test_edited_file_unchanged_upstream_is_left_alone(tmp_path: Path) -> None:
    dest = _init(tmp_path)
    (dest / SHELL).write_text('mine', encoding='utf-8')
    assert update_project(dest, apply=True).files == []
    assert (dest / SHELL).read_text(encoding='utf-8') == 'mine'


def test_theirs_replaces_conflicts(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    (dest / SHELL).write_text('mine', encoding='utf-8')
    new = _upstream(monkeypatch, SHELL_SRC)
    report = update_project(dest, theirs=True, apply=True)
    assert _actions(report) == {SHELL: 'replaced'}
    assert (dest / SHELL).read_bytes() == new


def test_deleted_file_stays_deleted(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    (dest / SHELL).unlink()
    _upstream(monkeypatch, SHELL_SRC)
    report = update_project(dest, apply=True)
    assert _actions(report) == {SHELL: 'deleted'}
    assert not (dest / SHELL).exists()


def test_opm_toml_is_never_replaced(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    before = (dest / 'opm.toml').read_bytes()
    original = scaffold.jinks.Environment.get_template

    def get_template(self, name):
        template = original(self, name)
        if name != 'opm.toml.tpl':
            return template

        class Changed:
            def render(self, **kw):
                return template.render(**kw) + '# new in opm\n'

        return Changed()

    monkeypatch.setattr(scaffold.jinks.Environment, 'get_template', get_template)
    report = update_project(dest, theirs=True, apply=True)
    assert _actions(report) == {'opm.toml': 'conflict'}
    assert (dest / 'opm.toml').read_bytes() == before
    assert (dest / ('opm.toml' + CONFLICT_SUFFIX)).read_text(encoding='utf-8').endswith('# new in opm\n')


def test_new_and_dropped_files(tmp_path: Path) -> None:
    dest = _init(tmp_path)
    path = dest / MANIFEST_PATH
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['files'][SHELL]
    data['files']['gone.txt'] = 'x'
    path.write_text(json.dumps(data), encoding='utf-8')
    (dest / SHELL).unlink()

    report = update_project(dest, apply=True)
    assert _actions(report) == {SHELL: 'added', 'gone.txt': 'removed'}
    assert (dest / SHELL).is_file()
    assert 'gone.txt' not in read_manifest(dest).files


def test_profile_major_bump_is_flagged(tmp_path: Path) -> None:
    dest = _init(tmp_path, '--profile', 'registers')
    path = dest / MANIFEST_PATH
    data = json.loads(path.read_text(encoding='utf-8'))
    current = data['profiles']['registers']
    data['profiles']['registers'] = '0.1.0'
    path.write_text(json.dumps(data), encoding='utf-8')

    report = update_project(dest, apply=True)
    [change] = report.profiles
    assert (change.name, change.recorded, change.available) == ('registers', '0.1.0', current)
    assert change.breaking == (int(current.split('.')[0]) > 0)
    assert read_manifest(dest).profiles['registers'] == current
    assert update_project(dest).profiles == []


def test_profile_commands_record_versions(tmp_path: Path, monkeypatch) -> None:
    dest = _init(tmp_path)
    monkeypatch.chdir(dest)
    assert main(['profile', 'add', 'registers']) == 0
    assert 'registers' in read_manifest(dest).profiles
    assert main(['profile', 'remove', 'registers']) == 0
    assert 'registers' not in read_manifest(dest).profiles


def test_example_project_round_trip(tmp_path: Path) -> None:
    dest = tmp_path / 'project'
    assert main(['init', str(dest), '--example', 'docbook', '--templates']) == 0
    assert update_project(dest).files == []


def test_missing_manifest(tmp_path: Path) -> None:
    dest = _init(tmp_path)
    (dest / MANIFEST_PATH).unlink()
    with pytest.raises(UpdateError, match='no .opm/init.json'):
        update_project(dest)


def test_update_command(tmp_path: Path, monkeypatch, capsys) -> None:
    dest = _init(tmp_path)
    _upstream(monkeypatch, SHELL_SRC)
    capsys.readouterr()
    assert main(['update', str(dest)]) == 0
    out = capsys.readouterr().out
    assert 'Would update' in out and 'handbook.html.tpl' in out
    assert main(['update', str(dest), '--apply']) == 0
    assert main(['update', str(dest)]) == 0
    assert 'Up to date.' in capsys.readouterr().out
