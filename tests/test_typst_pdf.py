"""Typst output compiled to PDF: ``opm.typst_compile`` and ``opm transform -t typst``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opm.output_modes import output_mode
from opm.typst_compile import compile_pdf, typst_executable

REPO = Path(__file__).resolve().parents[1]


def _fake_typst(monkeypatch) -> list[list[str]]:
    """Stand in for the typst command; returns the commands it was given."""
    import opm.typst_compile as typst_compile

    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        target = command[command.index('-') + 1]
        if target == '-':
            return subprocess.CompletedProcess(command, 0, stdout=b'%PDF-fake')
        Path(target).write_bytes(b'%PDF-fake')
        return subprocess.CompletedProcess(command, 0, stdout=b'')

    monkeypatch.setattr(typst_compile.shutil, 'which', lambda name: '/usr/bin/typst')
    monkeypatch.setattr(typst_compile.subprocess, 'run', fake_run)
    return commands


@pytest.mark.skipif(shutil.which('typst') is None, reason='typst is not installed')
def test_compile_pdf_runs_typst(tmp_path: Path) -> None:
    assert compile_pdf('Hello from opm', root=tmp_path).startswith(b'%PDF')


def test_open_viewer_passes_open_and_the_root(tmp_path: Path, monkeypatch) -> None:
    commands = _fake_typst(monkeypatch)
    assert compile_pdf('Hello', root=tmp_path, open_viewer=True) == b'%PDF-fake'
    [command] = commands
    assert '--open' in command
    assert command[command.index('--root') + 1] == str(tmp_path)


def test_missing_typst_is_reported(monkeypatch) -> None:
    import opm.typst_compile as typst_compile

    monkeypatch.setattr(typst_compile.shutil, 'which', lambda name: None)
    with pytest.raises(FileNotFoundError, match='typst command on PATH'):
        typst_executable()


@pytest.mark.parametrize(('mode', 'output', 'preview', 'installed', 'expected'), [
    ('typst', 'out.pdf', False, True, (True, False)),
    ('typst', 'OUT.PDF', True, True, (True, False)),     # --output wins over --preview
    ('typst', 'out.typ', False, True, (False, False)),
    ('typst', None, False, True, (False, False)),        # source to stdout
    ('typst', None, True, True, (True, True)),           # typst opens the PDF
    ('typst', None, True, False, (False, False)),        # no typst: source preview
    ('web', 'out.pdf', False, True, (False, False)),
])
def test_cli_asks_for_a_pdf_from_output_and_preview(
    monkeypatch, mode, output, preview, installed, expected,
) -> None:
    import opm.cli as cli

    monkeypatch.setattr(cli, 'typst_available', lambda: installed)
    assert cli._pdf_request(
        output_mode(mode), Path(output) if output else None, preview,
    ) == expected


@pytest.mark.parametrize(('args', 'opened'), [
    (['-o', 'out.pdf'], False),
    (['--preview'], True),
])
def test_transform_command_compiles_typst_output(
    tmp_path: Path, monkeypatch, capsys, args: list[str], opened: bool,
) -> None:
    import opm.cli as cli

    xml = tmp_path / 'doc.xml'
    shutil.copy(REPO / 'examples' / 'tei-test.xml', xml)
    monkeypatch.chdir(tmp_path)
    calls: list[tuple] = []
    monkeypatch.setattr(cli, 'typst_available', lambda: True)
    monkeypatch.setattr(cli, 'typst_executable', lambda: '/usr/bin/typst')
    monkeypatch.setattr(
        cli, 'compile_pdf',
        lambda source, *, root, open_viewer: calls.append((source, root, open_viewer)) or b'%PDF-fake',
    )

    rc = cli.main(['transform', str(xml), '-t', 'typst', *args])

    assert rc in (0, None)
    [(source, root, open_viewer)] = calls
    assert isinstance(source, str) and source.strip()
    # Image paths in the output are the XML's own, so they resolve next to it.
    assert root == xml.resolve().parent
    assert open_viewer is opened
    # The PDF goes to the viewer or the output file, never to the terminal.
    assert '%PDF' not in capsys.readouterr().out
    if not opened:
        assert (tmp_path / 'out.pdf').read_bytes() == b'%PDF-fake'
