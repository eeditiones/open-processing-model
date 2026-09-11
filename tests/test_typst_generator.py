"""Tests for ODD → Typst prelude generation."""

from __future__ import annotations

from opm.odd_compiler.typst_generator import (
    collect_odd_generated_typst,
    css_body_to_typst_function,
    typst_ident_from_class,
)
from opm.resources import packaged_odd

ODD = packaged_odd('teipublisher')


def test_typst_ident_from_class_replaces_hyphens() -> None:
    assert typst_ident_from_class('tei-pb2') == 'tei_pb2'
    assert typst_ident_from_class('simple_bold') == 'simple_bold'


def test_typst_content_fragment_escapes_brackets() -> None:
    from opm.odd_compiler.typst_generator import _typst_content_fragment

    assert _typst_content_fragment(']') == r'[\]]'
    assert _typst_content_fragment('[') == r'[\[]'


def test_renditions_to_typst_expr_merges_before_and_after() -> None:
    from opm.odd_compiler.typst_generator import renditions_to_typst_expr

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
    from opm.odd_compiler.parse_odd import load_odd

    parsed = load_odd(ODD)
    typst, fn_names = collect_odd_generated_typst(parsed, output_mode='typst')
    assert 'tei_hi' not in fn_names
    assert 'tei_hi1' not in fn_names
    assert '#let tei_hi(body)' not in typst


def test_collect_odd_generated_typst_from_teipublisher_odd() -> None:
    from opm.odd_compiler.parse_odd import load_odd

    parsed = load_odd(ODD)
    typst, _fn_names = collect_odd_generated_typst(parsed, output_mode='web')
    assert 'Generated Typst prelude' in typst
    assert '#let simple_bold' in typst
    assert '#let tei_corr' in typst or '#let tei_corr2' in typst


def test_compile_typst_mode_emits_odd_generated_typst() -> None:
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(ODD), output_mode='typst')
    assert 'ODD_GENERATED_TYPST' in src
    assert 'ODD_GENERATED_CSS' not in src
    assert "OUTPUT_MODE = 'typst'" in src


def test_css_body_to_typst_function_font_size() -> None:
    fn = css_body_to_typst_function('small_text', 'font-size: 0.75em;')
    assert 'text(size: 0.75em)' in fn


def test_font_size_keyword_and_percentage() -> None:
    assert 'text(size: 0.83em)' in css_body_to_typst_function('kw', 'font-size: small;')
    assert 'text(size: 80%)' in css_body_to_typst_function('pct', 'font-size: 80%;')
    # Typst has no root size; rem means the same thing as em for a rendition.
    assert 'text(size: 1.5em)' in css_body_to_typst_function('rem', 'font-size: 1.5rem;')


def test_font_size_and_color_share_one_text_call() -> None:
    """Both land in a single text(), rather than nesting two wrappers."""
    fn = css_body_to_typst_function('marker', 'font-size: 0.75em; color: grey;')
    assert 'text(size: 0.75em, fill: gray)' in fn
    assert fn.count('text(') == 1


def test_unsupported_font_size_is_dropped() -> None:
    """An unmappable value must not emit a broken Typst size."""
    fn = css_body_to_typst_function('weird', 'font-size: calc(1em + 2px);')
    assert 'text(' not in fn


def test_teipublisher_pb_renders_inline_page_number_in_typst() -> None:
    """The typst <pb> model is a small inline |<n> marker, not a margin note.

    A margin note per page break is too loud in running text, and the number is
    only meaningful next to the break it marks.
    """
    from opm.odd_compiler import compile_odd

    src = compile_odd(str(packaged_odd('teipublisher.odd')), output_mode='typst')
    assert "'|' || @n" in src
    # The page number rides along with the marker instead of going to the margin.
    assert "'margin'" not in src
    assert 'text(size: 0.75em, fill: gray)' in src
