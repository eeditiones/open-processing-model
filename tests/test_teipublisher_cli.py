"""Tests for the unified ``teipublisher`` CLI."""

from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'


def test_main_subcommand_missing_required_arg_usage_error(capsys) -> None:
    """Click ``UsageError`` (e.g. missing ODD) must not dump a traceback under ``standalone_mode=False``."""
    from tei_publisher_py.teipublisher_cli import main

    assert main(['compile']) == 2
    err = capsys.readouterr().err
    assert 'Missing argument' in err and 'ODD' in err
    assert 'Traceback' not in err


def test_main_no_command_shows_help_and_exits_zero(capsys) -> None:
    """``no_args_is_help`` raises :class:`click.exceptions.NoArgsIsHelpError` when not using Click's standalone mode; we must map that to exit 0."""
    from tei_publisher_py.teipublisher_cli import main

    assert main([]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert 'compile' in combined and 'transform' in combined


def test_load_transform_module(tmp_path: Path) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import load_transform_module

    src = compile_odd_to_python(str(ODD))
    out = tmp_path / 't.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)

    mod = load_transform_module(out)
    assert callable(mod.transform)


def test_transform_command_runs_minimal_xml(tmp_path: Path, capsys) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import main

    gen = tmp_path / 'gen.py'
    gen.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')

    xml = tmp_path / 'in.xml'
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        '<titleStmt><title>Hi</title></titleStmt></fileDesc></teiHeader>'
        '<text><body><p>x</p></body></text></TEI>\n',
        encoding='utf-8',
    )

    assert main(['transform', str(gen), str(xml)]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip()


def test_compile_command_writes_default_named_file(tmp_path: Path) -> None:
    """Without ``-o``, emit ``transform/<odd-stem>-<mode>.py`` under the current working directory."""
    import os
    import shutil

    from tei_publisher_py.teipublisher_cli import main

    odd_copy = tmp_path / 'teipublisher.odd'
    shutil.copy(ODD, odd_copy)
    prev = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert main(['compile', str(odd_copy)]) == 0
    finally:
        os.chdir(prev)
    dest = tmp_path / 'transform' / 'teipublisher-web.py'
    assert dest.is_file()
    text = dest.read_text(encoding='utf-8')
    assert 'def _dispatch' in text
    assert 'def transform' in text


def test_compile_command_writes_file(tmp_path: Path) -> None:
    from tei_publisher_py.teipublisher_cli import main

    dest = tmp_path / 'out.py'
    assert main(['compile', str(ODD), '-o', str(dest)]) == 0
    text = dest.read_text(encoding='utf-8')
    assert 'def transform' in text


def test_transform_accepts_param_pairs(tmp_path: Path, capsys) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import main

    gen = tmp_path / 'gen.py'
    gen.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>x</p></body></text></TEI>\n',
        encoding='utf-8',
    )

    assert main([
        'transform', str(gen), str(xml),
        '-p', 'mode=metadata',
        '--param', 'display=browse',
        '-p', 'a=b=c',
    ]) == 0
    assert capsys.readouterr().out.strip()


def test_transform_xpath_selects_subtree(tmp_path: Path, capsys) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import main

    gen = tmp_path / 'gen.py'
    gen.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        '<titleStmt><title>Hi</title></titleStmt></fileDesc></teiHeader>'
        '<text><body><p>x</p></body></text></TEI>\n',
        encoding='utf-8',
    )

    assert main([
        'transform', str(gen), str(xml),
        '--xpath', '//body',
    ]) == 0
    assert capsys.readouterr().out.strip()


def test_transform_writes_output_file(tmp_path: Path) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import main

    gen = tmp_path / 'gen.py'
    gen.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>x</p></body></text></TEI>\n',
        encoding='utf-8',
    )
    dest = tmp_path / 'out.html'

    assert main(['transform', str(gen), str(xml), '-o', str(dest)]) == 0
    text = dest.read_text(encoding='utf-8')
    assert text.strip()


def test_transform_param_requires_equals(tmp_path: Path, capsys) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.teipublisher_cli import main

    gen = tmp_path / 'gen.py'
    gen.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>x</p></body></text></TEI>\n',
        encoding='utf-8',
    )

    assert main(['transform', str(gen), str(xml), '-p', 'bad']) == 1
    err = capsys.readouterr().err
    assert 'KEY=VALUE' in err or 'error' in err.lower()
