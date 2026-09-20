"""Reporting XPath expressions opm cannot evaluate: at compile time and at run time."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from opm.cli import main
from opm.odd_compiler import compile_odd
from opm.odd_compiler.expression_check import static_problem
from opm.resources import packaged_odd
from opm.runtime.xpath_diagnostics import collect_xpath_errors
from opm.transform import load_transform_module, run_transform

TEI = 'http://www.tei-c.org/ns/1.0'


def _odd(tmp_path: Path, specs: str, *, name: str = 'tiny.odd') -> Path:
    """Write an ODD for no-namespace documents whose schemaSpec contains *specs*."""
    path = tmp_path / name
    path.write_text(
        '<?xml version="1.0"?>\n'
        f'<TEI xmlns="{TEI}" xmlns:util="http://exist-db.org/xquery/util"><text><body>'
        f'<schemaSpec ident="tiny" ns="">{specs}</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    return path


def _module(tmp_path: Path, odd: Path):
    path = tmp_path / f'{odd.stem}_web.py'
    path.write_text(compile_odd(str(odd)), encoding='utf-8')
    return load_transform_module(path)


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch) -> None:
    """Compile into the test's own directory, not the user cache."""
    cache = tmp_path / 'cache'
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)


# ── the static check ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(('expr', 'reason'), [
    ('util:document-name(.)', 'eXist function util:document-name()'),
    ('no-such-function(.)', 'unknown function no-such-function()'),
])
def test_static_problem_names_what_opm_cannot_run(expr: str, reason: str) -> None:
    assert static_problem(expr, {}) == reason


@pytest.mark.parametrize('expr', [
    "try { xs:date(@when) } catch * { string(@when) }",
    'head((ref, <ref type="previous"/>))',
    'let $a := 1 let $b := 2 return $a + $b',
    'for $r in ref return $r/@target',
])
def test_static_problem_accepts_xquery(expr: str) -> None:
    """The constructs the ODDs are written in, which opm parses as XQuery 3.1.

    These were reported as unsupported for as long as opm parsed XPath 3.1
    only; the vendored elementpath fork adds the XQuery parser, so they now
    compile like any other expression. `describe` still knows how to name them,
    for an elementpath that raises on one.
    """
    assert static_problem(expr, {}) is None


@pytest.mark.parametrize('expr', [
    # Supplied by the project, which a module cached per ODD cannot know.
    "tp:format_date(@when, 'en')",
    '$global:register-root',
    "collection('/db/registers')//person",
    "@type = 'toc'",
])
def test_static_problem_leaves_project_configuration_alone(expr: str) -> None:
    assert static_problem(expr, {}) is None


# ── compiling ────────────────────────────────────────────────────────────────

def test_unsupported_predicate_compiles_to_false_and_is_recorded(tmp_path: Path) -> None:
    odd = _odd(
        tmp_path,
        '<elementSpec ident="p">'
        '<model predicate="util:document-name(.) = \'x\'" behaviour="inline"/>'
        '<model behaviour="paragraph"/>'
        '</elementSpec>',
    )
    found: list = []
    src = compile_odd(str(odd), diagnostics=found)

    assert 'if False:' in src
    assert [(e.element, e.where, e.model) for e in found] == [('p', 'predicate', 'tei-p1')]
    assert 'eXist function' in found[0].reason
    assert found[0].odd == 'tiny.odd'
    assert found[0].line is not None

    # Same output as before: the predicate still counts as false.
    out = run_transform(_module(tmp_path, odd), etree.fromstring('<p>hi</p>'), apply_template=False)
    assert 'tei-p2' in out and 'hi' in out


def test_unsupported_param_falls_back_and_is_recorded(tmp_path: Path) -> None:
    odd = _odd(
        tmp_path,
        '<elementSpec ident="date"><model behaviour="inline">'
        '<param name="content" value="no-such-function(.)"/>'
        '</model></elementSpec>',
    )
    found: list = []
    compile_odd(str(odd), diagnostics=found)
    assert [(e.where, e.reason) for e in found] == [
        ('param content', 'unknown function no-such-function()'),
    ]

    mod = _module(tmp_path, odd)
    assert mod.ODD_UNSUPPORTED[0]['where'] == 'param content'
    out = run_transform(mod, etree.fromstring('<date when="1850-03-14">14.3.</date>'), apply_template=False)
    # The failing expression gave an empty sequence before, and still does.
    assert '<span' in out and '14.3.' not in out and '1850' not in out


def test_xquery_param_is_compiled_not_reported(tmp_path: Path) -> None:
    """A `try`/`catch` param runs, where it used to be skipped as unsupported."""
    odd = _odd(
        tmp_path,
        '<elementSpec ident="date"><model behaviour="inline">'
        '<param name="content" value="try { format-date(xs:date(@when), \'[D1] [MNn] [Y]\') }'
        ' catch * { string(@when) }"/>'
        '</model></elementSpec>',
    )
    found: list = []
    compile_odd(str(odd), diagnostics=found)
    assert found == []

    mod = _module(tmp_path, odd)
    assert mod.ODD_UNSUPPORTED == []
    out = run_transform(mod, etree.fromstring('<date when="1850-03-14">14.3.</date>'), apply_template=False)
    assert '14 3 1850' in out
    # The catch arm is what the ODD falls back to, and it is reachable.
    out = run_transform(mod, etree.fromstring('<date when="not-a-date">x</date>'), apply_template=False)
    assert 'not-a-date' in out


def test_names_supplied_by_the_project_are_compiled_not_reported(tmp_path: Path) -> None:
    odd = _odd(
        tmp_path,
        '<elementSpec ident="name">'
        '<model predicate="tp:is-person(.)" behaviour="inline">'
        '<param name="content" value="($global:register//person[@xml:id = tp:key(.)], .)[1]"/>'
        '</model>'
        '<model behaviour="inline"/>'
        '</elementSpec>',
    )
    found: list = []
    src = compile_odd(str(odd), diagnostics=found)

    assert found == []
    # A config-dependent param that calls a tp: function is evaluated rather
    # than replaced by the context node.
    assert "config.xpath.select_or_node(node, '($global:register" in src


def test_stock_odd_reports_only_exist_functions() -> None:
    """Nothing in teipublisher.odd is beyond opm now except eXist's own modules.

    Its XQuery — the `try`/`catch` around `format-date`, the `<ref/>` placeholder
    constructors of the correspContext models — compiles since opm parses XQuery
    3.1. What is left needs a database opm does not have.
    """
    found: list = []
    compile_odd(str(packaged_odd('teipublisher')), diagnostics=found)

    reasons = [e.reason for e in found]
    assert reasons, 'the stock ODD still calls eXist functions'
    assert all(r.startswith('eXist function ') for r in reasons), reasons
    assert not any('tp:' in r for r in reasons)
    assert {e.odd for e in found} == {'teipublisher.odd'}


# ── at run time ──────────────────────────────────────────────────────────────

def _dates_odd(tmp_path: Path) -> Path:
    return _odd(
        tmp_path,
        '<elementSpec ident="date">'
        '<model predicate="xs:date(@when) lt xs:date(\'1900-01-01\')" behaviour="inline"'
        ' cssClass="old"/>'
        '<model behaviour="inline"/>'
        '</elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>',
    )


def test_runtime_failures_are_counted_once_per_expression(tmp_path: Path) -> None:
    mod = _module(tmp_path, _dates_odd(tmp_path))
    doc = etree.fromstring(
        '<p><date when="circa">a</date> <date when="1850-01-01">b</date>'
        ' <date when="later">c</date></p>'
    )
    with collect_xpath_errors() as log:
        out = run_transform(mod, doc, apply_template=False)

    [failure] = log.ordered_failures()
    assert failure.code == 'FORG0001'
    assert failure.count == 2
    assert failure.element == 'date'
    assert failure.line == 1
    assert log.hints == {}
    assert 'old' in out  # the valid date still matched

    # Outside a collection block nothing is recorded.
    run_transform(mod, doc, apply_template=False)
    assert failure.count == 2


def test_missing_extension_function_is_a_hint_not_a_failure(tmp_path: Path) -> None:
    odd = _odd(
        tmp_path,
        '<elementSpec ident="p">'
        '<model predicate="tp:missing(.)" behaviour="inline"/>'
        '<model behaviour="paragraph"/>'
        '</elementSpec>',
    )
    with collect_xpath_errors() as log:
        run_transform(_module(tmp_path, odd), etree.fromstring('<p>x</p>'), apply_template=False)

    assert log.failures == {}
    assert list(log.hints) == ['function:tp:missing']
    assert 'xpath_extensions' in log.hints['function:tp:missing']


# ── the CLI ──────────────────────────────────────────────────────────────────

def _project(tmp_path: Path) -> Path:
    """A project whose ODD has one unsupported predicate and one that fails on bad data."""
    _odd(
        tmp_path,
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="p">'
        '<model predicate="util:document-name(.) = \'x\'" behaviour="inline"/>'
        '<model predicate="xs:integer(@n) gt 1" behaviour="inline" cssClass="late"/>'
        '<model behaviour="paragraph"/>'
        '</elementSpec>',
    )
    (tmp_path / 'opm.toml').write_text('[transform.web]\nodd = "tiny.odd"\n', encoding='utf-8')
    xml = tmp_path / 'in.xml'
    xml.write_text('<doc>\n<p n="one">a</p>\n<p n="2">b</p>\n</doc>', encoding='utf-8')
    return xml


def test_cli_reports_compile_time_skips_once(tmp_path: Path, monkeypatch, capsys) -> None:
    xml = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(['transform', str(xml), '-o', 'out.html']) == 0
    assert '1 ODD expression uses features opm does not support' in capsys.readouterr().err

    assert main(['transform', str(xml), '-o', 'out.html']) == 0
    assert 'does not support' not in capsys.readouterr().err


def test_cli_summarises_runtime_failures(tmp_path: Path, monkeypatch, capsys) -> None:
    xml = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(['transform', str(xml), '-o', 'out.html']) == 0
    err = capsys.readouterr().err
    assert '1 XPath expression failed at run time and was treated as false or empty' in err
    assert 'xs:integer(@n) gt 1' in err
    assert 'FORG0001' in err
    assert 'first at <p> in.xml:2' in err


def test_cli_strict_fails_on_runtime_failures(tmp_path: Path, monkeypatch, capsys) -> None:
    xml = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(['transform', str(xml), '--strict', '-o', 'out.html']) == 1
    assert '--strict: 1 XPath expression failed at run time.' in capsys.readouterr().err


def test_cli_strict_passes_without_runtime_failures(tmp_path: Path, monkeypatch) -> None:
    xml = _project(tmp_path)
    xml.write_text('<doc>\n<p n="1">a</p>\n</doc>', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    # The unsupported predicate was dealt with at compile time and does not count.
    assert main(['transform', str(xml), '--strict', '-o', 'out.html']) == 0


def test_coverage_lists_unsupported_expressions(tmp_path: Path, monkeypatch, capsys) -> None:
    xml = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage', str(xml), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['summary']['unsupported_expressions'] == 1
    assert report['unsupported'][0]['where'] == 'predicate'

    assert main(['odd', 'coverage', str(xml)]) == 0
    assert 'Expressions opm cannot run' in capsys.readouterr().out
