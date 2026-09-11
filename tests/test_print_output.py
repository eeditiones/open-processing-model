"""Tests for print (paged-media HTML) output functions and mode aliases."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

from lxml import etree

from opm.odd_compiler.codegen import _model_matches_output_mode
from opm.runtime.context import RenderContext
from opm.runtime.print_output_functions import PrintOutputFunctions
from opm.runtime.pm_runtime import apply_children, serialize


def _apply_children(config, node, content, parent_el) -> None:
    apply_children(config, node, content, parent_el)


def _config() -> RenderContext:
    return RenderContext(
        apply_children=_apply_children,
        apply=lambda _c, nodes: list(nodes) if isinstance(nodes, list) else [nodes],
    )


def test_print_note_margin_place() -> None:
    """Port of ts-ext-printcss:tpc:note-margin-place."""
    pmf = PrintOutputFunctions()
    node = etree.Element('n')
    res = pmf.note(_config(), node, ['c'], 'X', place='margin', label=None)
    assert len(res) == 1
    el = res[0]
    assert el.tag == 'span'
    assert 'c' in el.get('class', '').split()
    assert 'margin-note' in el.get('class', '').split()
    assert serialize(res).find('X') >= 0


def test_print_note_footnote_place() -> None:
    """Port of ts-ext-printcss:tpc:note-footnote-place."""
    pmf = PrintOutputFunctions()
    node = etree.Element('n')
    res = pmf.note(_config(), node, ['c'], 'X', place='footnote', label=None)
    assert len(res) == 1
    el = res[0]
    assert el.tag == 'span'
    assert 'footnote' in el.get('class', '').split()
    assert 'margin-note' not in el.get('class', '').split()


def test_print_note_default_place_is_footnote() -> None:
    pmf = PrintOutputFunctions()
    node = etree.Element('n')
    res = pmf.note(_config(), node, ['c'], 'body', place=None, label=None)
    assert 'footnote' in res[0].get('class', '').split()


def test_print_note_does_not_collect_footnotes() -> None:
    """Print notes stay in-flow; nothing is queued for inject_cached_footnotes."""
    pmf = PrintOutputFunctions()
    config = _config()
    node = etree.Element('n')
    pmf.note(config, node, ['c'], 'X', place='footnote', label=None)
    assert config.state.footnotes == []


def test_print_alternate_nested_spans() -> None:
    """Port of ts-ext-printcss:tpc:alternate-nested-spans."""
    pmf = PrintOutputFunctions()
    node = etree.Element('n')
    res = pmf.alternate(_config(), node, ['c'], None, 'D', 'A')
    assert len(res) == 2
    assert res[0].tag == 'span'
    assert 'c' in res[0].get('class', '').split()
    assert res[1].tag == 'span'
    assert 'footnote' in res[1].get('class', '').split()


def test_print_alternate_ignores_webcomponents() -> None:
    pmf = PrintOutputFunctions()
    config = _config()
    config.webcomponents = True
    node = etree.Element('n')
    res = pmf.alternate(config, node, ['c'], None, 'D', 'A')
    assert all(isinstance(el, etree._Element) and el.tag == 'span' for el in res)
    assert not any(el.tag == 'pb-popover' for el in res)


def test_model_matches_print_accepts_web_and_print() -> None:
    web = etree.Element('model')
    web.set('output', 'web')
    print_el = etree.Element('model')
    print_el.set('output', 'print')
    docx = etree.Element('model')
    docx.set('output', 'docx')
    unscoped = etree.Element('model')

    assert _model_matches_output_mode(web, 'print')
    assert _model_matches_output_mode(print_el, 'print')
    assert _model_matches_output_mode(unscoped, 'print')
    assert not _model_matches_output_mode(docx, 'print')
    # web mode still ignores print-only models
    assert not _model_matches_output_mode(print_el, 'web')
    assert _model_matches_output_mode(web, 'web')


def test_model_matches_epub_accepts_web_and_epub() -> None:
    """Alias registered for phase 2; filter behaviour is already shared."""
    web = etree.Element('model')
    web.set('output', 'web')
    epub = etree.Element('model')
    epub.set('output', 'epub')
    assert _model_matches_output_mode(web, 'epub')
    assert _model_matches_output_mode(epub, 'epub')
    assert not _model_matches_output_mode(epub, 'web')


def test_model_matches_opm_prefix_with_aliases() -> None:
    opm_web = etree.Element('model')
    opm_web.set('output', 'opm-web')
    opm_print = etree.Element('model')
    opm_print.set('output', 'opm-print')
    assert _model_matches_output_mode(opm_web, 'print')
    assert _model_matches_output_mode(opm_print, 'print')
    assert not _model_matches_output_mode(opm_print, 'web')


def test_compile_print_mode_imports_print_output_functions(tmp_path: Path) -> None:
    from opm.odd_compiler import compile_odd
    from opm.resources import packaged_odd

    src = compile_odd(str(packaged_odd('teipublisher')), output_mode='print')
    assert 'PrintOutputFunctions' in src
    assert 'PrintOutputFunctions()' in src
    assert 'webcomponents_allowed=False' in src
    assert "return ['print']" in src
    # print also matches web models — dispatch should still have cases
    assert 'match _tag(node):' in src

    out = tmp_path / 'print_gen.py'
    out.write_text(src, encoding='utf-8')
    py_compile.compile(str(out), doraise=True)


def test_print_compile_includes_web_models_excludes_docx(tmp_path: Path) -> None:
    """Compiling print keeps @output=web models and drops unrelated channels."""
    from opm.odd_compiler import compile_odd
    from opm.odd_compiler.codegen import _top_level_models
    from opm.odd_compiler.parse_odd import load_odd

    odd = tmp_path / 'mixed.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="note" mode="change">'
        '<model output="print" behaviour="note"/>'
        '<model output="web" behaviour="inline"/>'
        '<model output="docx" behaviour="omit"/>'
        '</elementSpec>'
        '<elementSpec ident="p" mode="change">'
        '<model behaviour="paragraph"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    parsed = load_odd(str(odd))
    note_spec = next(
        s for s in parsed.tree.iter('{http://www.tei-c.org/ns/1.0}elementSpec')
        if s.get('ident') == 'note'
    )
    print_models = _top_level_models(note_spec, 'print')
    outputs = [m.get('output') for m in print_models]
    assert outputs == ['print', 'web']

    web_models = _top_level_models(note_spec, 'web')
    assert [m.get('output') for m in web_models] == ['web']

    src = compile_odd(str(odd), output_mode='print')
    # First matching model wins (print note); docx omit must not appear.
    assert 'pmf.note(' in src
    assert 'pmf.omit(' not in src
    assert 'pmf.paragraph(' in src

    # Web-only ODD still participates under print via the alias.
    web_only = tmp_path / 'web_only.odd'
    web_only.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="hi" mode="change">'
        '<model output="web" behaviour="inline"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    src_web = compile_odd(str(web_only), output_mode='print')
    assert "case 'hi':" in src_web
    assert 'pmf.inline(' in src_web


def test_print_transform_note_is_inline_span(tmp_path: Path) -> None:
    """End-to-end: -t print emits span.footnote, not dl.footnote."""
    from opm.odd_compiler import compile_odd
    from opm.transform import load_transform_module, run_transform

    odd = tmp_path / 'note.odd'
    odd.write_text(
        '<?xml version="1.0"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        '<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        '<publicationStmt><p>p</p></publicationStmt>'
        '<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>'
        '<text><body>'
        '<schemaSpec ident="x" ns="http://www.tei-c.org/ns/1.0">'
        '<elementSpec ident="note" mode="change">'
        '<model behaviour="note">'
        '<param name="place" value="@place"/>'
        '<param name="label" value="@n"/>'
        '</model>'
        '</elementSpec>'
        '<elementSpec ident="p" mode="change">'
        '<model behaviour="paragraph"/>'
        '</elementSpec>'
        '</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    mod_path = tmp_path / 'note_print.py'
    mod_path.write_text(compile_odd(str(odd), output_mode='print'), encoding='utf-8')
    mod = load_transform_module(mod_path)

    xml = etree.fromstring(
        b'<p xmlns="http://www.tei-c.org/ns/1.0">'
        b'Text <note place="foot">A note</note> here.</p>'
    )
    out = run_transform(mod, xml, apply_template=False)
    assert 'class="tei-note1 footnote"' in out or 'footnote' in out
    assert 'dl' not in out
    assert 'fnref_' not in out


def test_print_transform_injects_footnote_float_baseline(tmp_path: Path) -> None:
    """-t print prepends the packaged baseline ahead of the ODD's own CSS.

    PrintOutputFunctions.note()/alternate() emit footnotes as inline spans —
    without ``float: footnote`` somewhere in the stylesheet, a paged-media
    renderer (Prince, Paged.js) leaves them sitting in the running text
    instead of moving them to the page-bottom footnote area. teipublisher.odd
    (unlike e.g. the docbook example) does not declare that rule itself, so
    the packaged baseline is what has to supply it.
    """
    from opm.odd_cache import ensure_compiled_module
    from opm.resources import packaged_odd
    from opm.transform import load_transform_module, run_transform

    odd_path, _ = ensure_compiled_module(packaged_odd('teipublisher'), output_mode='print')
    mod = load_transform_module(odd_path)
    xml = etree.fromstring(
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
        b'<p>Text <note>A note</note> here.</p>'
        b'</body></text></TEI>'
    )
    html = run_transform(mod, xml, apply_template=True)
    assert 'float: footnote' in html
    assert '::footnote-call' in html
    assert 'class="tei-note1 footnote"' in html or 'footnote' in html
    # Baseline precedes the ODD's own (generated) rules.
    assert html.index('float: footnote') < html.index('/* Generated stylesheet')


def test_docbook_print_uses_print_template_not_handbook(tmp_path: Path, monkeypatch) -> None:
    """DocBook example: -t print wraps with print.html.j2, not handbook chrome."""
    from opm.cli import main

    root = Path(__file__).resolve().parents[1] / 'examples' / 'docbook'
    out = tmp_path / 'print.html'
    monkeypatch.chdir(root)
    assert main([
        'transform',
        'data/doc/quickstart.xml',
        '-t', 'print',
        '-o', str(out),
    ]) == 0
    html = out.read_text(encoding='utf-8')
    assert 'class="content print"' in html
    assert 'handbook' not in html
    assert 'hb-sidebar' not in html
    assert 'pb-components' not in html
    assert 'float: footnote' in html or '@page' in html
