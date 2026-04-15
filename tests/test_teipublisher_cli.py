"""Tests for the unified ``teipublisher`` CLI."""

from __future__ import annotations

import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'


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


def test_compile_command_writes_stdout(tmp_path: Path, capsys) -> None:
    from tei_publisher_py.teipublisher_cli import main

    assert main(['compile', str(ODD)]) == 0
    out = capsys.readouterr().out
    assert 'def _dispatch' in out
    assert 'def transform' in out


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
