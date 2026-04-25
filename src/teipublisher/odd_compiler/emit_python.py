"""Generate Python source from a parsed ODD."""

from __future__ import annotations

import inspect
import keyword
import re
from pathlib import Path

from lxml import etree

from teipublisher.output_functions import XML_ID

from .behaviour_map import BEHAVIOUR_METHOD, method_for_behaviour
from .parse_odd import ParsedOdd, iter_element_specs, load_odd

TEI_NS = 'http://www.tei-c.org/ns/1.0'
PB_NS = 'http://teipublisher.com/1.0'

# When combining @behaviour with pb:template, default ``content`` for [[content]] substitution:
# use ``.`` (process children) only if the template references that placeholder; otherwise ``()``.
_TEMPLATE_HAS_CONTENT_PLACEHOLDER = re.compile(r'\[\[\s*content\s*\]\]')


def _default_content_for_template_combo(template_str: str) -> str:
    return '.' if _TEMPLATE_HAS_CONTENT_PLACEHOLDER.search(template_str) else '()'


def _local(tag: str) -> str:
    return etree.QName(tag).localname


def _sanitize_ident(ident: str) -> str:
    return ident.replace(':', '_')


def _pb_template(parent) -> etree._Element | None:
    for child in parent:
        if child.tag == f'{{{PB_NS}}}template':
            return child
    return None


def _serialize_template_content(tmpl_el) -> str:
    """Return the inner XML content of a pb:template element as a plain string.

    Namespace declarations from the ODD parent scope are stripped so the embedded
    string stays compact and readable; the template engine does not need them.
    """
    parts = []
    if tmpl_el.text:
        parts.append(tmpl_el.text)
    for child in tmpl_el:
        s = etree.tostring(child, encoding='unicode')
        # Strip all xmlns declarations lxml inherits from the ODD parent scope
        s = re.sub(r'\s*xmlns(?::\w+)?="[^"]*"', '', s)
        parts.append(s)
        if child.tail:
            parts.append(child.tail)
    return ''.join(parts)


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
    return o == output_mode


def _filter_by_output_mode(elements: list, output_mode: str) -> list:
    return [el for el in elements if _model_matches_output_mode(el, output_mode)]


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


def _python_triple_quoted(s: str) -> str:
    """Return *s* as a Python triple-quoted literal preserving line breaks."""
    return '"""' + s.replace('"""', '\\"""') + '"""'


def _top_level_models(spec_el, output_mode: str) -> list:
    kids = []
    for child in spec_el:
        if not isinstance(child.tag, str):
            continue  # skip XML comments / processing instructions
        loc = _local(child.tag)
        if loc in ('model', 'modelSequence', 'modelGrp'):
            kids.append(child)
    return _filter_by_output_mode(kids, output_mode)


def _model_children(seq_or_grp, output_mode: str) -> list:
    kids = []
    for child in seq_or_grp:
        if not isinstance(child.tag, str):
            continue  # skip XML comments / processing instructions
        loc = _local(child.tag)
        if loc in ('model', 'modelSequence', 'modelGrp'):
            kids.append(child)
    return _filter_by_output_mode(kids, output_mode)


def _param_tier_ok(value: str) -> bool:
    v = value.strip()
    if not v or v == '.':
        return True
    if v.startswith('let ') or 'util:' in v or '$global' in v or 'collection(' in v:
        return False
    if 'return ' in v and v.index('return ') < 8:
        return False
    return True


def _param_to_expr(value: str) -> str:
    v = (value or '').strip()
    if not v or v == '.':
        return 'node'
    if not _param_tier_ok(v):
        return 'node'
    if v.startswith('@'):
        attr = v[1:]
        if attr == 'xml:id':
            return 'node.get(XML_ID)'
        return f'node.get({attr!r})'
    # XPath string literals as used in ODD param @value (e.g. 'toc', 'column')
    m = re.match(r"^'([^']*)'$", v)
    if m:
        return repr(m.group(1))
    m = re.match(r'^"([^"]*)"$', v)
    if m:
        return repr(m.group(1))
    return (
        'xpath_content(node, '
        f'{repr(v)}, params, xpath_extensions=config.get("xpath_extensions"))'
    )


def _gather_params(model_el, *, default_content: str = '.') -> dict[str, str]:
    out: dict[str, str] = {}
    for p in model_el.findall(f'{{{TEI_NS}}}param'):
        name = p.get('name')
        if not name or list(p):
            continue
        val = p.get('value')
        if val is not None:
            out[name] = val
    if 'content' not in out:
        out['content'] = default_content
    return out


def _model_desc(model_el) -> str:
    """Normalized text content from optional child <desc>."""
    desc_el = model_el.find(f'{{{TEI_NS}}}desc')
    if desc_el is None:
        return ''
    text = ' '.join(' '.join(desc_el.itertext()).split())
    return text


def _desc_comment_lines(model_el, indent: str) -> list[str]:
    desc = _model_desc(model_el)
    if not desc:
        return []
    # Keep line lengths reasonable in generated sources.
    words = desc.split()
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur and cur_len + add > 96:
            lines.append(f"{indent}# {' '.join(cur)}")
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        lines.append(f"{indent}# {' '.join(cur)}")
    return lines


def _classes_expr(ident: str, model_el, spec_el) -> str:
    san = _sanitize_ident(ident)
    n = _model_ordinal(spec_el, model_el)
    parts = [f"'tei-{san}'", f"'tei-{san}{n}'", 'r']
    cc = model_el.get('cssClass')
    if cc:
        for tok in cc.split():
            if tok:
                parts.append(repr(tok))
    return '[' + ', '.join(parts) + ']'


_RESERVED_PARAM_ALIASES: dict[str, str] = {}


def _normalize_param_name(name: str) -> str:
    """Map ODD parameter names to Python-safe keyword names."""
    normalized = _RESERVED_PARAM_ALIASES.get(name, name).replace('-', '_')
    if keyword.iskeyword(normalized) or not normalized.isidentifier():
        return f'{normalized}_'
    return normalized


def _pmf_class_for_output_mode(output_mode: str):
    if output_mode == 'markdown':
        from teipublisher.markdown_output_functions import MarkdownOutputFunctions

        return MarkdownOutputFunctions
    from teipublisher.html_output_functions import HtmlOutputFunctions

    return HtmlOutputFunctions


def _accepted_method_kwargs(
    output_mode: str,
    method: str,
) -> tuple[dict[str, inspect.Parameter], bool]:
    """Return accepted keyword params for pmf.<method> after content."""
    cls = _pmf_class_for_output_mode(output_mode)
    fn = getattr(cls, method)
    sig = inspect.signature(fn)
    allowed: dict[str, inspect.Parameter] = {}
    allows_var_kw = False
    for p in sig.parameters.values():
        if p.name in ('self', 'config', 'node', 'cls', 'content'):
            continue
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            allows_var_kw = True
            continue
        if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            allowed[p.name] = p
    return allowed, allows_var_kw


def _emit_pmf_call(
    ident: str,
    behaviour: str,
    model_el,
    spec_el,
    pm: dict[str, str],
    output_mode: str,
    *,
    content_expr: str | None = None,
) -> str:
    method = method_for_behaviour(behaviour)
    cls_e = _classes_expr(ident, model_el, spec_el)
    if content_expr is not None:
        c = content_expr
    else:
        c = _param_to_expr(pm.get('content', '.'))

    allowed, allows_var_kw = _accepted_method_kwargs(output_mode, method)
    emitted: set[str] = set()
    kw_parts: list[str] = []
    for name, value in pm.items():
        if name == 'content':
            continue
        py_name = _normalize_param_name(name)
        if not allows_var_kw and py_name not in allowed:
            continue
        kw_parts.append(f'{py_name}={_param_to_expr(value)}')
        emitted.add(py_name)
    # Keep legacy behaviour: for required kwargs not provided by the ODD model,
    # pass None explicitly (old emitter always provided defaults via P(..., None)).
    for name, param in allowed.items():
        if name in emitted:
            continue
        if param.default is inspect.Parameter.empty:
            kw_parts.append(f'{name}=None')
    kwargs_src = ', ' + ', '.join(kw_parts) if kw_parts else ''
    return f'pmf.{method}(config, node, {cls_e}, {c}{kwargs_src})'


def _emit_template_params_dict_expr(pm: dict[str, str], *, pretty: bool = False) -> str:
    """Build the Python dict expression for ``pb:template`` ``[[param]]`` substitution."""
    param_items = []
    for name, val in pm.items():
        expr = _param_to_expr(val)
        if expr == 'node':
            # 'content' with default '.' processes children; other node-fallbacks pass raw.
            if name == 'content':
                param_items.append(f"'content': apply(config, child_nodes(node))")
            else:
                param_items.append(f"{name!r}: {expr}")
        elif expr.startswith('xpath_content('):
            # XPath may return elements or strings; wrap in apply() so elements are
            # dispatched through the ODD and strings pass through unchanged.
            param_items.append(f"{name!r}: apply(config, normalize({expr}))")
        else:
            # String literals and attribute accesses are already scalars.
            param_items.append(f"{name!r}: {expr}")
    inner = ', '.join(param_items)
    if not pretty:
        return '{' + inner + '}'
    return '{\n        ' + ',\n        '.join(param_items) + '\n    }'


class _TemplateHelperRegistry:
    """Collect ``def _odd_template_*`` helpers so ``pmf.template(...)`` is not inlined in ``_dispatch``."""

    def __init__(self) -> None:
        self._blocks: list[str] = []

    def register(
        self,
        ident: str,
        tmpl_el,
        model_el,
        spec_el,
        *,
        combo: bool,
    ) -> str:
        """Append helper source and return the function name."""
        name = _template_helper_name(ident, spec_el, model_el)
        block = _emit_template_helper_function(
            name, ident, tmpl_el, model_el, spec_el, combo=combo,
        )
        self._blocks.append(block)
        return name

    @property
    def functions_block(self) -> str:
        if not self._blocks:
            return ''
        return (
            '\n\n# pb:template helpers (keeps dispatch readable)\n'
            + '\n\n'.join(self._blocks)
        )


def _template_helper_name(ident: str, spec_el, model_el) -> str:
    san = _sanitize_ident(ident)
    n = _model_ordinal(spec_el, model_el)
    return f'_odd_template_{san}_{n}'


def _emit_template_helper_function(
    name: str,
    ident: str,
    tmpl_el,
    model_el,
    spec_el,
    *,
    combo: bool,
) -> str:
    """Full ``def name(...): return pmf.template(...)`` source for one model."""
    template_str = _serialize_template_content(tmpl_el)
    if combo:
        pm = _gather_params(
            model_el,
            default_content=_default_content_for_template_combo(template_str),
        )
        cls_e = '[]'
        params_line = _emit_template_params_dict_expr(pm, pretty=True)
        sig = f'def {name}(config, node, pmf, params, xpath_extensions)'
        tmpl_lit = _python_triple_quoted(template_str)
        return (
            f'{sig}:\n'
            f'    return pmf.template(\n'
            f'        config,\n'
            f'        node,\n'
            f'        {cls_e},\n'
            f'        {tmpl_lit},\n'
            f'        {params_line},\n'
            f'    )'
        )

    pm = _gather_params(model_el)
    cls_e = _classes_expr(ident, model_el, spec_el)
    params_line = _emit_template_params_dict_expr(pm, pretty=True)
    tmpl_lit = _python_triple_quoted(template_str)
    sig = f'def {name}(config, node, pmf, params, xpath_extensions, r)'
    return (
        f'{sig}:\n'
        f'    return pmf.template(\n'
        f'        config,\n'
        f'        node,\n'
        f'        {cls_e},\n'
        f'        {tmpl_lit},\n'
        f'        {params_line},\n'
        f'    )'
    )


def _template_helper_call(name: str, *, combo: bool) -> str:
    if combo:
        return (
            f'{name}(config, node, pmf, params, '
            f'xpath_extensions=config.get("xpath_extensions"))'
        )
    return (
        f'{name}(config, node, pmf, params, '
        f'xpath_extensions=config.get("xpath_extensions"), r=r)'
    )


def _emit_template_call(
    ident: str,
    tmpl_el,
    model_el,
    spec_el,
    helpers: _TemplateHelperRegistry,
) -> str:
    """Generate a call to a module-level helper that runs ``pmf.template`` (template-only model)."""
    name = helpers.register(ident, tmpl_el, model_el, spec_el, combo=False)
    return _template_helper_call(name, combo=False)


def _emit_behaviour_with_template(
    ident: str,
    tmpl_el,
    model_el,
    spec_el,
    behaviour: str,
    output_mode: str,
    helpers: _TemplateHelperRegistry,
) -> str:
    """Generate ``pmf.<behaviour>(..., _odd_template_*(...))`` using a registered helper.

    Used whenever a model has both ``@behaviour`` (other than ``template``) and ``pb:template``:
    the template is evaluated first; the resulting nodes are passed as ``content`` to the
    behaviour (e.g. ``pass-through`` forwards the fragment; ``listItem`` wraps it in ``<li>``).

    Default ``content`` for ``[[content]]`` is ``.`` only if the template text contains that
    placeholder; otherwise ``()`` so named placeholders (e.g. ``[[date]]``) do not also run
    ``apply`` on all element children.
    """
    name = helpers.register(ident, tmpl_el, model_el, spec_el, combo=True)
    inner = _template_helper_call(name, combo=True)
    pm = _gather_params(
        model_el,
        default_content=_default_content_for_template_combo(_serialize_template_content(tmpl_el)),
    )
    return _emit_pmf_call(
        ident,
        behaviour,
        model_el,
        spec_el,
        pm,
        output_mode,
        content_expr=inner,
    )


def _emit_leaf_model(
    ident: str,
    model_el,
    spec_el,
    output_mode: str,
    helpers: _TemplateHelperRegistry,
) -> str:
    tmpl = _pb_template(model_el)
    beh = model_el.get('behaviour')
    if tmpl is not None:
        if beh and beh != 'template':
            return _emit_behaviour_with_template(
                ident,
                tmpl,
                model_el,
                spec_el,
                beh,
                output_mode,
                helpers,
            )
        return _emit_template_call(ident, tmpl, model_el, spec_el, helpers)
    if not beh:
        return 'apply(config, child_nodes(node))'
    if beh not in BEHAVIOUR_METHOD:
        return 'apply(config, child_nodes(node))'
    pm = _gather_params(model_el)
    return _emit_pmf_call(ident, beh, model_el, spec_el, pm, output_mode)


def _emit_model_or_sequence(
    ident: str,
    el,
    spec_el,
    indent: str,
    output_mode: str,
    helpers: _TemplateHelperRegistry,
) -> str:
    loc = _local(el.tag)
    if loc == 'modelGrp':
        return _emit_process_models(
            ident,
            _model_children(el, output_mode),
            spec_el,
            indent,
            in_sequence=False,
            output_mode=output_mode,
            helpers=helpers,
        )
    if loc == 'modelSequence':
        parts = []
        for child in _model_children(el, output_mode):
            part = _emit_model_or_sequence(ident, child, spec_el, indent, output_mode, helpers)
            parts.append(f'({part})')
        if not parts:
            return f'{indent}apply(config, child_nodes(node))'
        if len(parts) == 1:
            return parts[0]
        return ' + '.join(parts)
    if loc == 'model':
        expr = _emit_leaf_model(ident, el, spec_el, output_mode, helpers)
        return expr
    return 'apply(config, child_nodes(node))'


def _emit_process_models(
    ident: str,
    models: list,
    spec_el,
    indent: str,
    *,
    in_sequence: bool,
    output_mode: str,
    helpers: _TemplateHelperRegistry,
) -> str:
    models = _filter_by_output_mode(models, output_mode)
    if not models:
        return f'{indent}return apply(config, child_nodes(node))'

    if not models[0].get('predicate'):
        inner = _emit_model_or_sequence(ident, models[0], spec_el, indent, output_mode, helpers)
        lines = []
        lines.extend(_desc_comment_lines(models[0], indent))
        if '\n' in inner:
            # Nested ``if``/``elif``/``else`` from modelGrp / modelSequence — must not prefix ``return``.
            lines.append(inner)
        else:
            lines.append(f'{indent}return {inner}')
        return '\n'.join(lines)

    conds = [m for m in models if m.get('predicate')]
    unconds = [m for m in models if not m.get('predicate')]

    lines = []
    for i, m in enumerate(conds):
        pred = m.get('predicate', '')
        inner = _emit_model_or_sequence(
            ident, m, spec_el, indent + '    ', output_mode, helpers,
        )
        kw = 'if' if i == 0 else 'elif'
        lines.append(
            f'{indent}{kw} xpath_test(node, {repr(pred)}, params, '
            'xpath_extensions=config.get("xpath_extensions")):'
        )
        lines.extend(_desc_comment_lines(m, indent + '    '))
        if '\n' in inner:
            lines.append(inner)
        else:
            lines.append(f'{indent}    return {inner}')
    if unconds:
        u = unconds[0] if len(unconds) > 1 and not in_sequence else unconds[0]
        inner = _emit_model_or_sequence(ident, u, spec_el, indent + '    ', output_mode, helpers)
        lines.append(f'{indent}else:')
        lines.extend(_desc_comment_lines(u, indent + '    '))
        if '\n' in inner:
            lines.append(inner)
        else:
            lines.append(f'{indent}    return {inner}')
    else:
        lines.append(f'{indent}else:')
        lines.append(f'{indent}    return apply(config, child_nodes(node))')
    return '\n'.join(lines)


def generate_python_module(
    parsed: ParsedOdd,
    module_name: str = 'generated_odd',
    *,
    output_mode: str = 'web',
) -> str:
    schema_ns = parsed.schema_ns
    odd_path = parsed.odd_path
    odd_css = collect_odd_generated_css(parsed, output_mode=output_mode)
    odd_css_literal = _python_triple_quoted(odd_css)

    helpers = _TemplateHelperRegistry()
    cases = []
    for spec in iter_element_specs(parsed):
        if not spec.findall(f'.//{{{TEI_NS}}}model'):
            continue
        ident = spec.get('ident')
        if not ident or ident in ('*', 'text()'):
            continue
        tops = _top_level_models(spec, output_mode)
        if not tops:
            continue  # spec has models but none target this output mode
        block = _emit_process_models(
            ident,
            tops,
            spec,
            '            ',
            in_sequence=False,
            output_mode=output_mode,
            helpers=helpers,
        )
        cases.append(f"        case {ident!r}:\n{block}")

    if cases:
        dispatch_body = (
            '    match _tag(node):\n'
            + '\n'.join(cases) + '\n'
            '        case _:\n'
            '            return apply(config, child_nodes(node))'
        )
    else:
        # No web-output specs — skip the match entirely; a bare `match` with no
        # `case` is a SyntaxError, and a match followed by a stray `return` is
        # also invalid.
        dispatch_body = '    return apply(config, child_nodes(node))'

    if output_mode == 'markdown':
        pmf_import = (
            'from teipublisher.markdown_output_functions import (\n'
            '    MarkdownOutputFunctions,\n'
            '    normalize_markdown_xml_text,\n'
            ')'
        )
        pmf_ctor = 'MarkdownOutputFunctions()'
        transform_config_extra = "\n        'normalize_text': normalize_markdown_xml_text,"
    else:
        pmf_import = 'from teipublisher.html_output_functions import HtmlOutputFunctions'
        pmf_ctor = 'HtmlOutputFunctions()'
        transform_config_extra = ''

    template_helpers_block = helpers.functions_block

    return f'''#!/usr/bin/env python3
"""Auto-generated TEI processing model ({output_mode} output).

Source ODD: {odd_path}
schema namespace: {schema_ns}
"""

from lxml import etree

from teipublisher.output_functions import (
    XML_ID,
    map_rend_to_class,
    child_nodes,
    normalize,
    reset_counters,
)
{pmf_import}
from teipublisher.pm_runtime import (
    apply as _apply_impl,
    apply_children as apply_children_impl,
    inject_cached_footnotes,
    tag as _tag,
    ns as _ns,
    xpath_test,
    xpath_select_nodes,
)


def xpath_content(node, expr, params=None, xpath_extensions=None):
    return xpath_select_nodes(
        node,
        expr,
        params,
        xpath_extensions=xpath_extensions,
    )
{template_helpers_block}


def transform_output_channels():
    """Return ODD processing-model output channel(s) for this module.

    Same values as ``teipublisher compile --mode`` and the ``output`` key in ``transform()`` config.
    """
    return ['{output_mode}']


ODD_GENERATED_CSS = {odd_css_literal}


def apply(config, nodes):
    return _apply_impl(config, nodes, config['dispatch'])


def _dispatch(config, node, params):
    pmf = config['pmf']
    r = map_rend_to_class(node)
    if _ns(node) != {schema_ns!r}:
        return [node]

{dispatch_body}


def transform(root, options=None):
    reset_counters()
    runtime_options = options or {{}}
    xpath_extensions = runtime_options.get('xpath_extensions')
    webcomponents = runtime_options.get('webcomponents', False)
    parameters = {{
        k: v for k, v in runtime_options.items() if k not in ('xpath_extensions', 'webcomponents')
    }}
    config = {{
        'output':         [{output_mode!r}],
        'parameters':    parameters,
        'xpath_extensions': xpath_extensions,
        'webcomponents': webcomponents,
        'pmf':           {pmf_ctor},
        'apply':         apply,
        'apply_children': apply_children_impl,
        'dispatch':      _dispatch,
        'odd_css':       ODD_GENERATED_CSS,
        'footnotes':     [],{transform_config_extra}
    }}
    result = apply(config, [root])
    result = config['pmf'].finish(config, result)
    return inject_cached_footnotes(result, config)
'''


def compile_odd_to_python(
    odd_path: str,
    module_name: str = 'generated_odd',
    *,
    output_mode: str = 'web',
) -> str:
    parsed = load_odd(odd_path)
    return generate_python_module(parsed, module_name=module_name, output_mode=output_mode)
