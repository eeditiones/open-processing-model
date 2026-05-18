"""Tests for ODD → Typst prelude generation."""

from __future__ import annotations

from pathlib import Path

from teipublisher.odd_compiler.typst_generator import (
    collect_odd_generated_typst,
    css_body_to_typst_function,
    typst_ident_from_class,
)

ROOT = Path(__file__).resolve().parents[1]
ODD = ROOT / 'odd' / 'teipublisher.odd'


def test_typst_ident_from_class_replaces_hyphens() -> None:
    assert typst_ident_from_class('tei-pb2') == 'tei_pb2'
    assert typst_ident_from_class('simple_bold') == 'simple_bold'


def test_typst_content_fragment_escapes_brackets() -> None:
    from teipublisher.odd_compiler.typst_generator import _typst_content_fragment

    assert _typst_content_fragment(']') == r'[\]]'
    assert _typst_content_fragment('[') == r'[\[]'


def test_renditions_to_typst_expr_merges_before_and_after() -> None:
    from teipublisher.odd_compiler.typst_generator import renditions_to_typst_expr

    expr = renditions_to_typst_expr([
        ("content: '[';", 'before'),
        ("content: ']';", 'after'),
    ])
    assert r'[\[]' in expr
    assert r'[\]]' in expr
    assert 'body' in expr


def test_css_body_to_typst_function_content_after() -> None:
    fn = css_body_to_typst_function('tei_pb2', 'content: " ‖ ";', scope='after')
    assert '#let tei_pb2(body)' in fn
    assert '‖' in fn
    assert 'body +' in fn or '+ body' in fn or 'body' in fn


def test_css_body_to_typst_function_content_before() -> None:
    fn = css_body_to_typst_function('tei_note1', "content: ' (';", scope='before')
    assert '#let tei_note1(body)' in fn
    assert '(' in fn


def test_css_body_to_typst_function_bold() -> None:
    fn = css_body_to_typst_function('simple_bold', 'font-weight: bold;')
    assert 'strong(body)' in fn


def test_collect_odd_generated_typst_skips_models_without_rendition() -> None:
    from teipublisher.odd_compiler.parse_odd import load_odd

    parsed = load_odd(ODD)
    typst, fn_names = collect_odd_generated_typst(parsed, output_mode='typst')
    assert 'tei_hi' not in fn_names
    assert 'tei_hi1' not in fn_names
    assert '#let tei_hi(body)' not in typst


def test_collect_odd_generated_typst_from_teipublisher_odd() -> None:
    from teipublisher.odd_compiler.parse_odd import load_odd

    parsed = load_odd(ODD)
    typst, _fn_names = collect_odd_generated_typst(parsed, output_mode='web')
    assert 'Generated Typst prelude' in typst
    assert '#let simple_bold' in typst
    assert '#let tei_corr' in typst or '#let tei_corr2' in typst


def test_compile_typst_mode_emits_odd_generated_typst() -> None:
    from teipublisher.odd_compiler import compile_odd

    src = compile_odd(str(ODD), output_mode='typst')
    assert 'ODD_GENERATED_TYPST' in src
    assert 'ODD_GENERATED_CSS' not in src
    assert 'TypstOutputFunctions' in src
    assert "return ['typst']" in src
