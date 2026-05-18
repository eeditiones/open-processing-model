"""CSS generation from ODD (language-agnostic)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from teipublisher.runtime.output_functions import XML_ID

from .parse_odd import ParsedOdd, iter_element_specs

TEI_NS = 'http://www.tei-c.org/ns/1.0'


def _local(tag: str) -> str:
    return etree.QName(tag).localname


def _sanitize_ident(ident: str) -> str:
    return ident.replace(':', '_')


def _all_models_in_spec(spec_el) -> list:
    return list(spec_el.iter(f'{{{TEI_NS}}}model'))


def _model_ordinal(spec_el, model_el) -> int:
    models = _all_models_in_spec(spec_el)
    for i, m in enumerate(models):
        if m is model_el:
            return i + 1
    return 1


def _model_matches_output_mode(el, output_mode: str) -> bool:
    """Whether *el* participates in the given ODD output channel (``@output`` on models)."""
    o = el.get('output')
    if output_mode == 'web':
        return o is None or o == 'web'
    if output_mode == 'markdown':
        return o is None or o == 'markdown'
    if output_mode == 'typst':
        return o is None or o == 'typst'
    return o == output_mode


def _normalize_css_body(text: str) -> str:
    return ' '.join(text.split())


def _collect_tagsdecl_renditions(parsed: ParsedOdd) -> tuple[dict[str, str], list[str]]:
    """Collect inherited tagsDecl renditions: parent ODDs first, child overwrites by xml:id."""
    simple_rules: dict[str, str] = {}
    sources: list[str] = []

    for odd_file in parsed.odd_chain:
        root = etree.parse(odd_file, etree.XMLParser(collect_ids=False)).getroot()
        for rend in root.iter(f'{{{TEI_NS}}}rendition'):
            par = rend.getparent()
            if par is None or _local(par.tag) != 'tagsDecl':
                continue
            rid = rend.get(XML_ID)
            body = _normalize_css_body(''.join(rend.itertext()))
            if rid and body:
                simple_rules[rid] = body
            src = (rend.get('source') or '').strip()
            if src and src not in sources:
                sources.append(src)
    return simple_rules, sources


def collect_odd_generated_css(parsed: ParsedOdd, output_mode: str = 'web') -> str:
    """Build CSS from the ODD, matching ``css:generate-css`` in ``css.xql`` (web).

    Emits ``.simple_{xml:id}`` rules from ``tagsDecl/tei:rendition`` and
    ``.tei-{ident}{n}`` / ``.tei-{ident}{n}:{scope}`` from model ``outputRendition``.
    """
    chunks: list[str] = ['/* Generated stylesheet. Do not edit. */', '']

    # tagsDecl rendition (class names simple_* — see css:get-rendition / html output)
    root = parsed.tree.getroot()
    odd_dir = Path(parsed.odd_path).parent
    simple_rules, sources = _collect_tagsdecl_renditions(parsed)
    for rid, body in simple_rules.items():
        chunks.append(f'.simple_{rid} {{ {body} }}')
    for src in sources:
        path = odd_dir / src
        if path.is_file():
            chunks.append(f'/* external styles loaded from {src} */')
            chunks.append(path.read_text(encoding='utf-8'))
        else:
            chunks.append(f'/* external styles not found: {src} */')

    chunks.append('')
    chunks.append('/* Model rendition styles */')

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
            base = f'tei-{san}{n}'
            for rend in rends:
                body = _normalize_css_body(''.join(rend.itertext()))
                if not body:
                    continue
                scope = rend.get('scope')
                if scope:
                    sel = f'.{base}:{scope}'
                else:
                    sel = f'.{base}'
                chunks.append(f'{sel} {{ {body} }}')

    return '\n'.join(chunks).strip() + '\n'
