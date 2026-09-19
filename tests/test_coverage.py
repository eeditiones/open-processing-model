"""Tests for ``opm odd coverage`` — the ODD's own diagnostics."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree

from opm.cli import main
from opm.coverage import (
    CoverageReport,
    ModelInfo,
    Occurrence,
    _scan_records,
    _Seen,
    analyze,
    iter_element_paths,
    unreachable_models,
)
from opm.odd_compiler.parse_odd import load_odd

ROOT = Path(__file__).resolve().parents[1]
DEMO_TEI_TEST_XML = ROOT / 'examples' / 'tei-test.xml'
JATS_ODD = ROOT / 'src' / 'opm' / 'resources' / 'odd' / 'jats.odd'
TEI = 'http://www.tei-c.org/ns/1.0'


def _odd(tmp_path: Path, specs: str, *, name: str = 'tiny.odd', source: str = '') -> Path:
    """Write an ODD whose schemaSpec contains *specs* (no namespace)."""
    path = tmp_path / name
    attr = f' source="{source}"' if source else ''
    path.write_text(
        '<?xml version="1.0"?>\n'
        f'<TEI xmlns="{TEI}"><text><body>'
        f'<schemaSpec ident="tiny" ns=""{attr}>{specs}</schemaSpec>'
        '</body></text></TEI>',
        encoding='utf-8',
    )
    return path


def _isolate_cache(tmp_path: Path, monkeypatch) -> None:
    """Compile into the test's own directory, not the user cache."""
    cache = tmp_path / 'cache'
    # platformdirs on macOS ignores XDG_CACHE_HOME; redirect the dir instead.
    monkeypatch.setattr('opm.odd_cache.modules_cache_dir', lambda: cache / 'modules')
    monkeypatch.setattr('opm.resources.user_opm_cache_dir', lambda: cache)


# ── static analysis: models that can never fire ──────────────────────────────

def test_first_model_without_predicate_shadows_the_rest(tmp_path: Path) -> None:
    """The generator returns on the first unconditional model, ODD order wins."""
    odd = _odd(tmp_path, (
        '<elementSpec ident="p">'
        '<model behaviour="paragraph"/>'
        '<model behaviour="block" predicate="@rend"/>'
        '</elementSpec>'
    ))

    findings = unreachable_models(load_odd(odd))
    assert 'tei-p1' not in findings
    assert 'the paragraph model above it has no @predicate' in findings['tei-p2']


def test_only_the_first_unconditional_model_is_the_fallback(tmp_path: Path) -> None:
    """Predicated models are hoisted above an unconditional one — but only one
    unconditional model can be the ``else``."""
    odd = _odd(tmp_path, (
        '<elementSpec ident="p">'
        '<model behaviour="block" predicate="@rend"/>'
        '<model behaviour="paragraph"/>'
        '<model behaviour="inline" predicate="parent::cell"/>'
        '<model behaviour="block"/>'
        '</elementSpec>'
    ))

    findings = unreachable_models(load_odd(odd))
    # The third model keeps a predicate, so the compiler still tries it.
    assert set(findings) == {'tei-p4'}
    assert 'already the fallback' in findings['tei-p4']


def test_model_sequence_children_are_not_shadowed(tmp_path: Path) -> None:
    """Every child of a sequence contributes; none is an alternative to another."""
    odd = _odd(tmp_path, (
        '<elementSpec ident="p">'
        '<modelSequence>'
        '<model behaviour="anchor"/>'
        '<model behaviour="paragraph"/>'
        '</modelSequence>'
        '</elementSpec>'
    ))

    assert unreachable_models(load_odd(odd)) == {}


def test_model_group_is_its_own_shadowing_level(tmp_path: Path) -> None:
    odd = _odd(tmp_path, (
        '<elementSpec ident="p">'
        '<modelGrp predicate="@rend">'
        '<model behaviour="block"/>'
        '<model behaviour="inline"/>'
        '</modelGrp>'
        '<model behaviour="paragraph"/>'
        '</elementSpec>'
    ))

    findings = unreachable_models(load_odd(odd))
    # Inside the group the second model is dead; the group itself is guarded, so
    # the unconditional model after it stays reachable.
    assert set(findings) == {'tei-p2'}


def test_shipped_jats_odd_still_has_its_dead_ref_model() -> None:
    """A regression anchor on a real ODD: `ref` declares two fallbacks."""
    findings = unreachable_models(load_odd(JATS_ODD))
    assert findings.get('tei-ref2')


# ── source paths ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not DEMO_TEI_TEST_XML.is_file(), reason='Fixture examples/tei-test.xml not found',
)
def test_incremental_paths_match_the_paths_records_carry() -> None:
    """The set difference behind "dropped" only works if both sides agree."""
    from opm.runtime.json_output_functions import _element_path

    root = etree.parse(str(DEMO_TEI_TEST_XML)).getroot()
    walked = list(iter_element_paths(root))

    assert len(walked) == len([el for el in root.iter() if isinstance(el.tag, str)])
    assert all(_element_path(element) == path for element, path in walked)


def test_foreign_namespaces_keep_the_positional_step() -> None:
    root = etree.fromstring(
        f'<TEI xmlns="{TEI}"><text><svg xmlns="http://www.w3.org/2000/svg"/>'
        '<p/></text></TEI>'.encode(),
    )
    paths = [path for _, path in iter_element_paths(root)]

    # The svg has no prefix to name it with, so it keeps a positional step; the
    # p is indexed among its same-named siblings, exactly as records are.
    assert paths == ['/TEI', '/TEI/text[1]', '/TEI/text[1]/*[1]', '/TEI/text[1]/p[1]']


# ── record walking ───────────────────────────────────────────────────────────

def _report(**models) -> CoverageReport:
    return CoverageReport(
        odd=Path('x.odd'), channel='web',
        models={key: ModelInfo(key=key, **value) for key, value in models.items()},
    )


def test_records_are_counted_per_model_and_behaviour() -> None:
    report = _report(**{
        'tei-div1': {'element': 'div', 'behaviour': 'section'},
        'tei-p1': {'element': 'p', 'behaviour': 'paragraph'},
    })
    seen = _Seen()
    _scan_records([{
        'xpath': '/doc/div[1]', 'element': 'div', 'behaviour': 'section',
        'model': 'tei-div1',
        'children': [
            {'xpath': '/doc/div[1]/p[1]', 'element': 'p', 'behaviour': 'paragraph',
             'model': 'tei-p1', 'children': ['text']},
            {'xpath': '/doc/div[1]/p[2]', 'element': 'p', 'behaviour': 'paragraph',
             'model': 'tei-p1'},
        ],
    }], report, seen)

    assert report.records == 3
    assert report.models['tei-p1'].hits == 2
    assert report.behaviours == Counter({'paragraph': 2, 'section': 1})
    assert seen.recorded == {'/doc/div[1]', '/doc/div[1]/p[1]', '/doc/div[1]/p[2]'}


def test_suppressed_and_unmatched_records_are_kept_apart() -> None:
    report = _report()
    seen = _Seen()
    _scan_records([
        {'xpath': '/doc/head[1]', 'element': 'head', 'behaviour': 'omit',
         'model': 'tei-head1', 'suppressed': True},
        {'xpath': '/doc/foo[1]', 'element': 'foo', 'behaviour': None, 'model': None},
    ], report, seen)

    assert report.suppressed == 1
    assert seen.pruned == {'/doc/head[1]'}
    assert report.unmatched['foo'].count == 1
    assert report.unmatched['foo'].xpath == '/doc/foo[1]'


def test_unused_models_ignore_elements_the_corpus_never_contains() -> None:
    report = _report(**{
        'tei-p1': {'element': 'p', 'behaviour': 'paragraph'},
        'tei-castList1': {'element': 'castList', 'behaviour': 'list'},
        'tei-hi1': {'element': 'hi', 'behaviour': 'inline', 'source': 'base.odd'},
    })
    report.elements_seen.update({'p': 3, 'hi': 2})

    # `castList` is absent from the corpus and `hi` is inherited: neither is a
    # finding about a model the author wrote and this corpus could have hit.
    assert [m.key for m in report.unused_models()] == ['tei-p1']


def test_models_that_emit_nothing_are_not_reported_as_unused() -> None:
    report = _report(**{
        'tei-p1': {'element': 'p', 'behaviour': None},
        'tei-q1': {'element': 'q', 'behaviour': None, 'template': True},
    })
    report.elements_seen.update({'p': 1, 'q': 1})

    assert [m.key for m in report.silent_models()] == ['tei-p1']
    # The template model emits records, so a zero hit count really is a finding.
    assert [m.key for m in report.unused_models()] == ['tei-q1']


# ── end to end ───────────────────────────────────────────────────────────────

def _run(tmp_path: Path, odd: Path, xml: str, monkeypatch) -> CoverageReport:
    _isolate_cache(tmp_path, monkeypatch)
    document = tmp_path / 'in.xml'
    document.write_text(xml, encoding='utf-8')
    return analyze([document], odd=odd)


def test_element_whose_predicates_all_fail_is_reported_as_dropped(
    tmp_path: Path, monkeypatch,
) -> None:
    """The one finding records alone cannot show: no record is emitted at all."""
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
        '<elementSpec ident="hi"><model behaviour="inline" predicate="@rend"/>'
        '</elementSpec>'
    ))

    report = _run(tmp_path, odd, '<doc><p>a <hi>b</hi></p></doc>', monkeypatch)

    assert set(report.dropped) == {'hi'}
    assert report.dropped['hi'].count == 1
    assert report.dropped['hi'].line == 1
    assert not report.unmatched  # `hi` has a spec: this is a fall-through


def test_element_without_a_spec_is_unmatched_not_dropped(
    tmp_path: Path, monkeypatch,
) -> None:
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
    ))

    report = _run(tmp_path, odd, '<doc><p>a <foo>b</foo></p></doc>', monkeypatch)

    assert set(report.unmatched) == {'foo'}
    assert not report.dropped


def test_suppressed_subtree_is_not_reported_as_dropped(
    tmp_path: Path, monkeypatch,
) -> None:
    """`omit` means "I decided against this", not "I forgot about this"."""
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="head"><model behaviour="omit"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
    ))

    report = _run(
        tmp_path, odd, '<doc><head><title>t</title></head><p>a</p></doc>', monkeypatch,
    )

    assert not report.dropped
    assert not report.unmatched
    # It is still part of the document, so the spec counts as exercised.
    assert report.elements_seen['title'] == 1


def test_only_the_outermost_dropped_element_is_reported(
    tmp_path: Path, monkeypatch,
) -> None:
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="meta"><model behaviour="block" predicate="@show"/>'
        '</elementSpec>'
        '<elementSpec ident="name"><model behaviour="inline" predicate="@show"/>'
        '</elementSpec>'
    ))

    report = _run(
        tmp_path, odd, '<doc><meta><name>n</name><name>m</name></meta></doc>', monkeypatch,
    )

    assert set(report.dropped) == {'meta'}


def test_unused_specs_and_attribute_only_specs_are_separated(
    tmp_path: Path, monkeypatch,
) -> None:
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="castList"><model behaviour="list"/></elementSpec>'
        '<elementSpec ident="p" mode="change"><attList/></elementSpec>'
    ))

    report = _run(tmp_path, odd, '<doc/>', monkeypatch)

    assert report.unused_specs == [{'element': 'castList', 'models': 1}]
    assert report.attribute_only_specs == ['p']


def test_inherited_models_are_reported_apart_from_local_ones(
    tmp_path: Path, monkeypatch,
) -> None:
    base = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
        '<elementSpec ident="hi"><model behaviour="inline"/></elementSpec>'
    ), name='base.odd')
    child = _odd(
        tmp_path,
        '<elementSpec ident="hi"><model behaviour="block"/></elementSpec>',
        name='child.odd', source=base.name,
    )

    report = _run(tmp_path, child, '<doc><p>a <hi>b</hi></p></doc>', monkeypatch)

    local = {m.key for m in report.local_models()}
    assert local == {'tei-hi1'}
    assert {m.source for m in report.inherited_models()} == {'base.odd'}
    # An inherited model that never fired is not the author's finding to act on.
    assert not report.unused_models()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _tiny_project(tmp_path: Path) -> Path:
    odd = _odd(tmp_path, (
        '<elementSpec ident="doc"><model behaviour="document"/></elementSpec>'
        '<elementSpec ident="p"><model behaviour="paragraph"/></elementSpec>'
        '<elementSpec ident="castList"><model behaviour="list"/></elementSpec>'
    ))
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'in.xml').write_text('<doc><p>a <foo/></p></doc>', encoding='utf-8')
    return odd


def test_cli_prints_a_table(tmp_path: Path, monkeypatch, capsys) -> None:
    odd = _tiny_project(tmp_path)
    _isolate_cache(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage', 'data', '-d', str(odd)]) == 0
    out = capsys.readouterr().out
    assert 'ODD coverage' in out
    assert 'Elements with no model' in out
    assert 'foo' in out
    assert 'castList' in out  # never exercised spec


def test_cli_defaults_to_the_data_directory(tmp_path: Path, monkeypatch, capsys) -> None:
    odd = _tiny_project(tmp_path)
    _isolate_cache(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage', '-d', str(odd), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['documents'] == [str(Path('data') / 'in.xml')]


def test_cli_json_report_carries_every_section(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    odd = _tiny_project(tmp_path)
    _isolate_cache(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage', 'data', '-d', str(odd), '--json']) == 0
    report = json.loads(capsys.readouterr().out)

    assert report['channel'] == 'web'
    assert report['summary']['local_models'] == 3
    assert [entry['element'] for entry in report['unmatched']] == ['foo']
    assert [entry['element'] for entry in report['unused_specs']] == ['castList']
    assert {m['key'] for m in report['models']} == {'tei-doc1', 'tei-p1', 'tei-castList1'}


def test_cli_reports_a_missing_corpus(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage']) == 1
    assert 'input XML file or directory is required' in capsys.readouterr().err


def test_cli_rejects_an_unknown_channel(tmp_path: Path, monkeypatch, capsys) -> None:
    odd = _tiny_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(['odd', 'coverage', 'data', '-d', str(odd), '--channel', 'nope']) == 1
    assert '--channel must be one of' in capsys.readouterr().err


def test_cli_coverage_alias_still_works(tmp_path: Path, monkeypatch, capsys) -> None:
    odd = _tiny_project(tmp_path)
    _isolate_cache(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert main(['coverage', 'data', '-d', str(odd)]) == 0
    assert 'ODD coverage' in capsys.readouterr().out


def test_occurrence_location_falls_back_to_the_xpath() -> None:
    assert Occurrence('p', 1, '/doc/p[1]').location == '/doc/p[1]'
    assert Occurrence('p', 1, '/doc/p[1]', 'a.xml', 12).location == 'a.xml:12'
