"""Typst prelude generation from ODD (language-agnostic)."""

from __future__ import annotations

import re

from lxml import etree

from opm.runtime.output_functions import XML_ID

from .css_generator import (
    _all_models_in_spec,
    _collect_tagsdecl_renditions,
    _model_matches_output_mode,
    _model_ordinal,
    _normalize_css_body,
    _sanitize_ident,
)
from .parse_odd import ParsedOdd, iter_element_specs

TEI_NS = 'http://www.tei-c.org/ns/1.0'

_CONTENT_RE = re.compile(
    r"""content\s*:\s*(['"])(.*?)\1""",
    re.IGNORECASE | re.DOTALL,
)


def typst_ident_from_class(class_name: str) -> str:
    """Map a CSS class name (e.g. ``tei-pb2``) to a valid Typst identifier."""
    return class_name.replace('-', '_').replace(':', '_')


def _parse_css_properties(css_body: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for pm in re.finditer(r'([\w-]+)\s*:\s*([^;]+)', css_body):
        props[pm.group(1).strip().lower()] = pm.group(2).strip()
    return props


def _extract_content_literal(css_body: str) -> str | None:
    m = _CONTENT_RE.search(css_body)
    if m:
        return m.group(2)
    return None


def _typst_escape_content(s: str) -> str:
    """Escape text for Typst content blocks ``[...]``."""
    for ch in ('\\', '[', ']', '#'):
        s = s.replace(ch, '\\' + ch)
    return s


def _typst_content_fragment(literal: str) -> str:
    """Typst content fragment for a fixed string literal."""
    if not literal:
        return '[]'
    return f'[{_typst_escape_content(literal)}]'


_CSS_NAMED_COLORS = {
    'grey': 'gray',
    'gray': 'gray',
    'black': 'black',
    'white': 'white',
    'red': 'red',
    'green': 'green',
    'blue': 'blue',
}


def _css_color_to_typst(css_color: str) -> str | None:
    """Map a CSS color value to a Typst color expression, or None if unsupported."""
    c = css_color.strip().lower()
    if c in _CSS_NAMED_COLORS:
        return _CSS_NAMED_COLORS[c]
    if re.match(r'^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$', c, re.IGNORECASE):
        return f'rgb("{c}")'
    return None


def _wrap_typst_styling(expr: str, props: dict[str, str]) -> str:
    """Wrap *expr* (Typst identifier ``body``) with styling from CSS properties."""
    result = expr
    fw = props.get('font-weight', '').lower()
    if 'bold' in fw or fw in ('700', '800', '900'):
        result = f'strong({result})'
    fs = props.get('font-style', '').lower()
    if 'italic' in fs or fs == 'oblique':
        result = f'emph({result})'
    td = props.get('text-decoration', '').lower()
    if 'line-through' in td:
        result = f'strike({result})'
    color = props.get('color', '').strip()
    if color:
        typst_color = _css_color_to_typst(color)
        if typst_color:
            result = f'text(fill: {typst_color})[#{result}]'
    return result


def renditions_to_typst_expr(renditions: list[tuple[str, str | None]]) -> str:
    """Convert one or more ``outputRendition`` bodies to a Typst expression."""
    before_frags: list[str] = []
    after_frags: list[str] = []
    combined_props: dict[str, str] = {}

    for css_body, scope in renditions:
        combined_props.update(_parse_css_properties(css_body))
        content_lit = _extract_content_literal(css_body)
        if content_lit is None:
            continue
        frag = _typst_content_fragment(content_lit)
        if scope == 'before':
            before_frags.append(frag)
        else:
            after_frags.append(frag)

    parts = before_frags + ['body'] + after_frags
    expr = ' + '.join(parts) if len(parts) > 1 else 'body'
    return _wrap_typst_styling(expr, combined_props)


def css_body_to_typst_expr(css_body: str, scope: str | None = None) -> str:
    """Convert a single CSS rule body to a Typst expression using the ``body`` parameter."""
    return renditions_to_typst_expr([(css_body, scope)])


def css_body_to_typst_function(name: str, css_body: str, scope: str | None = None) -> str:
    """Convert a CSS rule body to ``#let name(body) = …``."""
    expr = css_body_to_typst_expr(css_body, scope=scope)
    return f'#let {name}(body) = {expr}\n'


def collect_odd_generated_typst(
    parsed: ParsedOdd,
    output_mode: str = 'typst',
) -> tuple[str, frozenset[str]]:
    """Build Typst prelude from ``outputRendition`` / tagsDecl and the function names emitted.

    Returns ``(prelude_source, function_names)``.  Runtime wrapping uses
    *function_names* so only models with a generated ``#let`` are wrapped.
    """
    chunks: list[str] = ['// Generated Typst prelude. Do not edit.', '']
    fn_names: set[str] = set()

    simple_rules, _sources = _collect_tagsdecl_renditions(parsed)
    for rid, body in simple_rules.items():
        fn_name = typst_ident_from_class(f'simple_{rid}')
        fn_names.add(fn_name)
        chunks.append(css_body_to_typst_function(fn_name, body))

    chunks.append('')
    chunks.append('// Model rendition functions')

    model_exprs: dict[str, str] = {}

    for spec in iter_element_specs(parsed):
        ident = spec.get('ident')
        if not ident or ident in ('*', 'text()'):
            continue
        san = _sanitize_ident(ident)
        for model_el in _all_models_in_spec(spec):
            if not _model_matches_output_mode(model_el, output_mode):
                continue
            rends = model_el.findall(f'{{{TEI_NS}}}outputRendition')
            if not rends:
                continue
            n = _model_ordinal(spec, model_el)
            fn_name = typst_ident_from_class(f'tei-{san}{n}')
            rend_pairs: list[tuple[str, str | None]] = []
            for rend in rends:
                body = _normalize_css_body(''.join(rend.itertext()))
                if body:
                    rend_pairs.append((body, rend.get('scope')))
            if rend_pairs:
                model_exprs[fn_name] = renditions_to_typst_expr(rend_pairs)
                fn_names.add(fn_name)

    for fn_name in sorted(model_exprs):
        chunks.append(f'#let {fn_name}(body) = {model_exprs[fn_name]}\n')

    return '\n'.join(chunks).strip() + '\n', frozenset(fn_names)
