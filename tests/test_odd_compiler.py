"""Smoke tests for ODD → Python compilation."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'
SHAKESPEARE_ODD = ROOT / 'odd' / 'shakespeare.odd'


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


def test_modelGrp_as_unconditional_or_else_emits_valid_block(tmp_path: Path) -> None:
    """When a modelGrp sits next to a conditional model at top level (i.e. one
    conditional model plus an unconditional modelGrp), the modelGrp expands to
    an if/elif/else block with its own `return`s. Placing it after a bare
    `return ` produces `return         if xpath_test(...)` — invalid Python.

    Regression test derived from the `pb` elementSpec in real-world rqzh.odd."""
    import py_compile

    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python

    odd = tmp_path / 'grp.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="pb" mode="change">'
        '<model predicate="@foo" behaviour="inline"/>'
        '<modelGrp>'
        '<model predicate="@a" behaviour="inline"/>'
        '<model predicate="@b" behaviour="pass-through"/>'
        '<model behaviour="block"/>'
        '</modelGrp>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src = compile_odd_to_python(str(odd))
    out = tmp_path / 'gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)
    # No orphan "return " immediately followed by a conditional.
    assert 'return                 if' not in src
    assert 'return         if' not in src
    """Compiled module passes ODD CSS into ``odd_css``; HTML ``head`` gets a ``style`` block."""
    from lxml import etree

    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python
    from tei_publisher_py.pm_runtime import serialize

    path = tmp_path / 'teipublisher_web.py'
    path.write_text(compile_odd_to_python(str(ODD)), encoding='utf-8')
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


def test_compile_inherited_odd_loads_parent_then_overwrites_child() -> None:
    """Child ODD inherits elementSpec from source ODD and overwrites duplicate idents."""
    from tei_publisher_py.odd_compiler.emit_python import compile_odd_to_python

    src = compile_odd_to_python(str(SHAKESPEARE_ODD))

    # Inherited from teipublisher.odd (not declared in shakespeare.odd).
    assert "case 'ab':" in src

    # Overwritten by shakespeare.odd for ident='lb' (mode is ignored).
    assert "case 'lb':" in src
    assert "return pmf.omit(config, node, ['tei-lb', 'tei-lb1', r], node)" in src
    # Inherited + local tagsDecl rendition sources are included in generated CSS.
    assert 'external styles loaded from shakespeare.css' in src
    assert '.simple_bold { font-weight: bold; }' in src
    # <desc> from models is preserved as generated Python comments.
    assert "# for breadcrumbs, pick title/@type='statement'" in src
