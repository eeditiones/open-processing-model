"""Python code generator for ODD compilation."""

from __future__ import annotations

import inspect
import keyword
import re

from . import (
    CodeGenerator,
    _filter_by_output_mode,
    _gather_params,
    _local,
    _model_children,
    _model_desc,
    _model_ordinal,
    _pb_template,
    _sanitize_ident,
    _serialize_template_content,
    _top_level_models,
)
from ..behaviour_map import BEHAVIOUR_METHOD, method_for_behaviour
from ..css_generator import collect_odd_generated_css
from ..parse_odd import ParsedOdd, iter_element_specs

# When combining @behaviour with pb:template, default ``content`` for [[content]] substitution:
# use ``.`` (process children) only if the template references that placeholder; otherwise ``()``.
_TEMPLATE_HAS_CONTENT_PLACEHOLDER = re.compile(r'\[\[\s*content\s*\]\]')

_RESERVED_PARAM_ALIASES: dict[str, str] = {}


class PythonGenerator(CodeGenerator):
    """Generate Python source from a parsed ODD."""

    @property
    def target_name(self) -> str:
        return 'python'

    @property
    def file_extension(self) -> str:
        return '.py'

    def generate_module(
        self,
        parsed: ParsedOdd,
        module_name: str = 'generated_odd',
        *,
        output_mode: str = 'web',
    ) -> str:
        return self._generate_python_module(parsed, module_name, output_mode)

    def _generate_python_module(
        self,
        parsed: ParsedOdd,
        module_name: str,
        output_mode: str,
    ) -> str:
        schema_ns = parsed.schema_ns
        odd_path = parsed.odd_path
        odd_css = collect_odd_generated_css(parsed, output_mode=output_mode)
        odd_css_literal = self._python_triple_quoted(odd_css)
        # Generate NSMAP from ODD namespace declarations for XPath expressions
        nsmap_literal = self._python_nsmap_literal(parsed.nsmap)

        helpers = self._TemplateHelperRegistry()
        cases = []
        for spec in iter_element_specs(parsed):
            if not spec.findall(f'.//{{{self._TEI_NS}}}model'):
                continue
            ident = spec.get('ident')
            if not ident or ident in ('*', 'text()'):
                continue
            tops = _top_level_models(spec, output_mode)
            if not tops:
                continue  # spec has models but none target this output mode
            block = self._emit_process_models(
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
                'from teipublisher.runtime.markdown_output_functions import (\n'
                '    MarkdownOutputFunctions,\n'
                '    normalize_markdown_xml_text,\n'
                ')'
            )
            pmf_ctor = 'MarkdownOutputFunctions()'
            transform_config_extra = "\n        'normalize_text': normalize_markdown_xml_text,"
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
        elif output_mode == 'docx':
            pmf_import = (
                'from teipublisher.runtime.docx_output_functions import (\n'
                '    DocxOutputFunctions,\n'
                '    docx_apply_children,\n'
                ')\n'
                'from teipublisher.runtime.markdown_output_functions import normalize_markdown_xml_text'
            )
            pmf_ctor = 'DocxOutputFunctions()'
            transform_config_extra = (
                "\n        'docx_template': runtime_options.get('docx_template'),"
                "\n        'apply_children': docx_apply_children,"
                "\n        'normalize_text': normalize_markdown_xml_text,"
                "\n        'input_path': runtime_options.get('input_path'),"
            )
            transform_opts_exclude = "('xpath_extensions', 'webcomponents', 'docx_template')"
        else:
            pmf_import = 'from teipublisher.runtime.html_output_functions import HtmlOutputFunctions'
            pmf_ctor = 'HtmlOutputFunctions()'
            transform_config_extra = ''
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"

        template_helpers_block = helpers.functions_block

        return f'''#!/usr/bin/env python3
"""Auto-generated TEI processing model ({output_mode} output).

Source ODD: {odd_path}
schema namespace: {schema_ns}
"""

from lxml import etree

# Namespace mappings from ODD root element (for XPath expressions)
NSMAP = {nsmap_literal}

from teipublisher.runtime.output_functions import (
    XML_ID,
    map_rend_to_class,
    child_nodes,
    normalize,
    reset_counters,
)
{pmf_import}
from teipublisher.runtime.pm_runtime import (
    apply as _apply_impl,
    apply_children as apply_children_impl,
    apply_template_param_value,
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
        namespaces=NSMAP,
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
        k: v for k, v in runtime_options.items() if k not in {transform_opts_exclude}
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

    _TEI_NS = 'http://www.tei-c.org/ns/1.0'

    @staticmethod
    def _python_triple_quoted(s: str) -> str:
        """Return *s* as a Python triple-quoted literal preserving line breaks."""
        return '"""' + s.replace('"""', '\\"""') + '"""'

    @staticmethod
    def _python_nsmap_literal(nsmap: dict[str, str]) -> str:
        """Return namespace mappings as a Python dict literal for generated code."""
        if not nsmap:
            return '{}'
        items = ', '.join(f'{k!r}: {v!r}' for k, v in sorted(nsmap.items()))
        return '{' + items + '}'

    @staticmethod
    def _python_ident_fragment_for_helpers(ident: str) -> str:
        """Sanitize elementSpec @ident for generated ``def _odd_template_*`` names.

        TEI idents may contain ``-`` (e.g. ``ref-cell``); Python identifiers may not.
        CSS classes still use :func:`_sanitize_ident` only, so ``tei-ref-cell`` is unchanged.
        """
        s = ident.replace(':', '_').replace('-', '_')
        s = re.sub(r'[^0-9a-zA-Z_]+', '_', s)
        s = re.sub(r'_+', '_', s).strip('_')
        if not s:
            return 'el'
        if s[0].isdigit():
            s = f't_{s}'
        if keyword.iskeyword(s):
            s = f'{s}_'
        return s

    @staticmethod
    def _param_tier_ok(value: str) -> bool:
        v = value.strip()
        if not v or v == '.':
            return True
        # Reject legacy XQuery util: and eXist-db specific functions
        if 'util:' in v or '$global' in v or 'collection(' in v:
            return False
        return True

    def _param_to_expr(self, value: str) -> str:
        v = (value or '').strip()
        # $get(x) is an XQuery indirection that is always identity in Python
        v = re.sub(r'\$get\(([^()]+)\)', r'\1', v)
        if not v or v == '.':
            return 'node'
        if not self._param_tier_ok(v):
            return 'node'
        if v.startswith('@'):
            attr = v[1:]
            if attr == 'xml:id':
                return 'node.get(XML_ID)'
            # Handle namespaced attributes (e.g., @xlink:href -> node.get('{http://...}href'))
            if ':' in attr:
                prefix, local = attr.split(':', 1)
                return f"node.get('{{' + NSMAP.get({prefix!r}, '') + '}}{local}')"
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

    @staticmethod
    def _normalize_param_name(name: str) -> str:
        """Map ODD parameter names to Python-safe keyword names."""
        normalized = _RESERVED_PARAM_ALIASES.get(name, name).replace('-', '_')
        if keyword.iskeyword(normalized) or not normalized.isidentifier():
            return f'{normalized}_'
        return normalized

    @staticmethod
    def _pmf_class_for_output_mode(output_mode: str):
        if output_mode == 'markdown':
            from teipublisher.runtime.markdown_output_functions import MarkdownOutputFunctions

            return MarkdownOutputFunctions
        if output_mode == 'docx':
            from teipublisher.runtime.docx_output_functions import DocxOutputFunctions

            return DocxOutputFunctions
        from teipublisher.runtime.html_output_functions import HtmlOutputFunctions

        return HtmlOutputFunctions

    def _accepted_method_kwargs(
        self,
        output_mode: str,
        method: str,
    ) -> tuple[dict[str, inspect.Parameter], bool]:
        """Return accepted keyword params for pmf.<method> after content."""
        cls = self._pmf_class_for_output_mode(output_mode)
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

    def _classes_expr(self, ident: str, model_el, spec_el) -> str:
        san = _sanitize_ident(ident)
        n = _model_ordinal(spec_el, model_el)
        parts = [f"'tei-{san}'", f"'tei-{san}{n}'", 'r']
        cc = model_el.get('cssClass')
        if cc:
            for tok in cc.split():
                if tok:
                    parts.append(repr(tok))
        return '[' + ', '.join(parts) + ']'

    def _desc_comment_lines(self, model_el, indent: str) -> list[str]:
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

    def _default_content_for_template_combo(self, template_str: str) -> str:
        return '.' if _TEMPLATE_HAS_CONTENT_PLACEHOLDER.search(template_str) else '()'

    def _emit_pmf_call(
        self,
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
        cls_e = self._classes_expr(ident, model_el, spec_el)
        if content_expr is not None:
            c = content_expr
        else:
            c = self._param_to_expr(pm.get('content', '.'))

        allowed, allows_var_kw = self._accepted_method_kwargs(output_mode, method)
        emitted: set[str] = set()
        kw_parts: list[str] = []
        for name, value in pm.items():
            if name == 'content':
                continue
            py_name = self._normalize_param_name(name)
            if not allows_var_kw and py_name not in allowed:
                continue
            kw_parts.append(f'{py_name}={self._param_to_expr(value)}')
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

    def _emit_template_params_dict_expr(self, pm: dict[str, str], *, pretty: bool = False) -> str:
        """Build the Python dict expression for ``pb:template`` ``[[param]]`` substitution."""
        param_items = []
        for name, val in pm.items():
            expr = self._param_to_expr(val)
            if expr == 'node':
                # Literal context node (``param value="."``): never pass raw TEI into
                # templates — same as XPath selecting ``.`` (see apply_template_param_value).
                param_items.append(
                    f"{name!r}: apply_template_param_value(config, node, node)"
                )
            elif expr.startswith('xpath_content('):
                # XPath may return the context element; expand that via children, not raw node.
                param_items.append(
                    f"{name!r}: apply_template_param_value(config, node, {expr})"
                )
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
            generator: 'PythonGenerator',
        ) -> str:
            """Append helper source and return the function name."""
            name = generator._template_helper_name(ident, spec_el, model_el)
            block = generator._emit_template_helper_function(
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

    def _template_helper_name(self, ident: str, spec_el, model_el) -> str:
        san = self._python_ident_fragment_for_helpers(ident)
        n = _model_ordinal(spec_el, model_el)
        return f'_odd_template_{san}_{n}'

    def _emit_template_helper_function(
        self,
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
                default_content=self._default_content_for_template_combo(template_str),
            )
            cls_e = '[]'
            params_line = self._emit_template_params_dict_expr(pm, pretty=True)
            tmpl_lit = self._python_triple_quoted(template_str)
            sig = f'def {name}(config, node, pmf, params, xpath_extensions)'
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
        cls_e = self._classes_expr(ident, model_el, spec_el)
        params_line = self._emit_template_params_dict_expr(pm, pretty=True)
        tmpl_lit = self._python_triple_quoted(template_str)
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

    def _template_helper_call(self, name: str, *, combo: bool) -> str:
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
        self,
        ident: str,
        tmpl_el,
        model_el,
        spec_el,
        helpers: '_TemplateHelperRegistry',
    ) -> str:
        """Generate a call to a module-level helper that runs ``pmf.template`` (template-only model)."""
        name = helpers.register(ident, tmpl_el, model_el, spec_el, combo=False, generator=self)
        return self._template_helper_call(name, combo=False)

    def _emit_behaviour_with_template(
        self,
        ident: str,
        tmpl_el,
        model_el,
        spec_el,
        behaviour: str,
        output_mode: str,
        helpers: '_TemplateHelperRegistry',
    ) -> str:
        """Generate ``pmf.<behaviour>(..., _odd_template_*(...))`` using a registered helper.

        Used whenever a model has both ``@behaviour`` (other than ``template``) and ``pb:template``:
        the template is evaluated first; the resulting nodes are passed as ``content`` to the
        behaviour (e.g. ``pass-through`` forwards the fragment; ``listItem`` wraps it in ``<li>``).

        Default ``content`` for ``[[content]]`` is ``.`` only if the template text contains that
        placeholder; otherwise ``()`` so named placeholders (e.g. ``[[date]]``) do not also run
        ``apply`` on all element children.
        """
        name = helpers.register(ident, tmpl_el, model_el, spec_el, combo=True, generator=self)
        inner = self._template_helper_call(name, combo=True)
        pm = _gather_params(
            model_el,
            default_content=self._default_content_for_template_combo(_serialize_template_content(tmpl_el)),
        )
        return self._emit_pmf_call(
            ident,
            behaviour,
            model_el,
            spec_el,
            pm,
            output_mode,
            content_expr=inner,
        )

    def _emit_leaf_model(
        self,
        ident: str,
        model_el,
        spec_el,
        output_mode: str,
        helpers: '_TemplateHelperRegistry',
    ) -> str:
        tmpl = _pb_template(model_el)
        beh = model_el.get('behaviour')
        if tmpl is not None:
            if beh and beh != 'template':
                return self._emit_behaviour_with_template(
                    ident,
                    tmpl,
                    model_el,
                    spec_el,
                    beh,
                    output_mode,
                    helpers,
                )
            return self._emit_template_call(ident, tmpl, model_el, spec_el, helpers)
        if not beh:
            return 'apply(config, child_nodes(node))'
        if beh not in BEHAVIOUR_METHOD:
            return 'apply(config, child_nodes(node))'
        pm = _gather_params(model_el)
        return self._emit_pmf_call(ident, beh, model_el, spec_el, pm, output_mode)

    def _emit_model_or_sequence(
        self,
        ident: str,
        el,
        spec_el,
        indent: str,
        output_mode: str,
        helpers: '_TemplateHelperRegistry',
    ) -> str:
        loc = _local(el.tag)
        if loc == 'modelGrp':
            return self._emit_process_models(
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
                part = self._emit_model_or_sequence(ident, child, spec_el, indent, output_mode, helpers)
                pred = child.get('predicate')
                if pred:
                    # In modelSequence, each nested model can be guarded by its own predicate.
                    # False predicate means: contribute no output for this sequence slot.
                    part = (
                        f'(({part}) if xpath_test(node, {repr(pred)}, params, '
                        'xpath_extensions=config.get("xpath_extensions"), namespaces=NSMAP) else [])'
                    )
                parts.append(f'({part})')
            if not parts:
                return f'{indent}apply(config, child_nodes(node))'
            if len(parts) == 1:
                return parts[0]
            return ' + '.join(parts)
        if loc == 'model':
            expr = self._emit_leaf_model(ident, el, spec_el, output_mode, helpers)
            return expr
        return 'apply(config, child_nodes(node))'

    def _emit_process_models(
        self,
        ident: str,
        models: list,
        spec_el,
        indent: str,
        *,
        in_sequence: bool,
        output_mode: str,
        helpers: '_TemplateHelperRegistry',
    ) -> str:
        models = _filter_by_output_mode(models, output_mode)
        if not models:
            return f'{indent}return apply(config, child_nodes(node))'

        if not models[0].get('predicate'):
            inner = self._emit_model_or_sequence(ident, models[0], spec_el, indent, output_mode, helpers)
            lines = []
            lines.extend(self._desc_comment_lines(models[0], indent))
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
            inner = self._emit_model_or_sequence(
                ident, m, spec_el, indent + '    ', output_mode, helpers,
            )
            kw = 'if' if i == 0 else 'elif'
            lines.append(
                f'{indent}{kw} xpath_test(node, {repr(pred)}, params, '
                'xpath_extensions=config.get("xpath_extensions"), namespaces=NSMAP):'
            )
            lines.extend(self._desc_comment_lines(m, indent + '    '))
            if '\n' in inner:
                lines.append(inner)
            else:
                lines.append(f'{indent}    return {inner}')
        if unconds:
            u = unconds[0] if len(unconds) > 1 and not in_sequence else unconds[0]
            inner = self._emit_model_or_sequence(ident, u, spec_el, indent + '    ', output_mode, helpers)
            lines.append(f'{indent}else:')
            lines.extend(self._desc_comment_lines(u, indent + '    '))
            if '\n' in inner:
                lines.append(inner)
            else:
                lines.append(f'{indent}    return {inner}')
        else:
            lines.append(f'{indent}else:')
            lines.append(f'{indent}    return apply(config, child_nodes(node))')
        return '\n'.join(lines)
