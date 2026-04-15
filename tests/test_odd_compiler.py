"""Smoke tests for ODD → Python compilation."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'


def test_compile_teipublisher_odd_emits_valid_python(tmp_path: Path) -> None:
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python

    src = compile_odd_to_python(str(ODD))
    assert 'def _dispatch' in src
    assert 'def transform' in src
    assert 'pass_through' in src
    assert 'ODD_GENERATED_CSS' in src
    assert 'odd_css' in src
    # tagsDecl rendition → .simple_* (css.xql); model outputRendition → .tei-{ident}{n}[:scope]
    assert '.simple_bold' in src
    assert '.tei-corr2:before' in src
    assert '.tei-del1 {' in src

    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)

    spec = importlib.util.spec_from_file_location('teipublisher_gen', str(out))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.transform)
    assert 'def main()' not in src


def test_teipublisher_web_injects_generated_css_in_head() -> None:
    """Compiled module passes ODD CSS into ``odd_css``; HTML ``head`` gets a ``style`` block."""
    from lxml import etree

    from tei_publisher_py.pm_runtime import serialize

    path = ROOT / 'teipublisher_web.py'
    spec = importlib.util.spec_from_file_location('teipublisher_web', str(path))
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    xml = b"""<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="en">
<teiHeader><fileDesc><titleStmt><title>T</title></titleStmt></fileDesc></teiHeader>
<text><body><p>x</p></body></text></TEI>"""
    root = etree.fromstring(xml)
    out = serialize(m.transform(root))
    assert '<style' in out
    assert 'Model rendition styles' in m.ODD_GENERATED_CSS
    assert '.tei-del1' in out
