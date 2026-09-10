# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Python code generator for ODD compilation."""

from __future__ import annotations

import inspect
import keyword
import re
import textwrap
from pathlib import Path

from . import (
    CodeGenerator,
    _filter_by_output_mode,
    _gather_params,
    _local,
    _model_children,
    _model_desc,
    _model_matches_output_mode,
    _model_ordinal,
    _pb_template,
    _sanitize_ident,
    _serialize_template_content,
    _top_level_models,
    is_json_mode,
    model_key,
)
from ..behaviour_map import BEHAVIOUR_METHOD, method_for_behaviour
from ..css_generator import collect_odd_generated_css
from ..expression_check import UnsupportedExpression, static_problem
from ..typst_generator import collect_odd_generated_typst
from ..parse_odd import ParsedOdd, iter_element_specs, spec_origin

# When combining @behaviour with pb:template, default ``content`` for [[content]] substitution:
# use ``.`` (process children) only if the template references that placeholder; otherwise ``()``.
_TEMPLATE_HAS_CONTENT_PLACEHOLDER = re.compile(r'\[\[\s*content\s*\]\]')

_RESERVED_PARAM_ALIASES: dict[str, str] = {}

# A prefixed variable reference ($ns:name) — its value comes from project config,
# never from the document.
_EXTERNAL_VAR_RE = re.compile(r'\$[A-Za-z_][\w.-]*:')


def _inherited_source(spec_el, primary: Path) -> str | None:
    """The ODD file *spec_el* came from, when that is not *primary*.

    Returning ``None`` for the ODD under compilation keeps the models table
    quiet about the common case: a ``source`` entry means "this model came from
    an ODD I extend", which is what tells an author whether editing the local
    ODD can change it.
    """
    origin = spec_origin(spec_el)
    if origin is None:
        return None
    return None if origin == primary else origin.name


class PythonGenerator(CodeGenerator):
    """Generate Python source from a parsed ODD."""

    def __init__(self) -> None:
        #: Set per :meth:`generate_module` call from the ODD root's namespace map.
        self._odd_nsmap: dict[str, str] = {}
        #: The schemaSpec namespace, i.e. the default element namespace at run time.
        self._schema_ns = ''
        #: Expressions compiled out, keyed so each is recorded once.
        self._unsupported: dict[tuple, UnsupportedExpression] = {}
        self._problems: dict[str, str | None] = {}

    @property
    def unsupported(self) -> list[UnsupportedExpression]:
        """Expressions the last :meth:`generate_module` call compiled out.

        Each is one opm can never evaluate (see
        :mod:`~opm.odd_compiler.expression_check`). It was replaced by what a
        failing evaluation returns, so the output is unchanged; the difference
        is that it is now known and reported instead of failing on every node.
        """
        return list(self._unsupported.values())

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
        base_css: str | None = None,
    ) -> str:
        return self._generate_python_module(parsed, module_name, output_mode, base_css)

    @staticmethod
    def _docstring_safe(text: str) -> str:
        """Neutralise anything in ODD-supplied text that could break out of the docstring.

        A quote run would close it and a trailing backslash would escape the
        closing quotes; neither loses anything that matters in a licence line.
        """
        return text.replace('\\', '/').replace('"', "'")

    @classmethod
    def _rights_block(cls, parsed: ParsedOdd) -> str:
        """The rights statements of the compiled ODDs, for the module docstring.

        A generated module outlives the reading of any README: it gets committed,
        baked into images, copied between projects. The stock processing models
        are CC BY, so the credit they ask for has to travel with the code rather
        than sit in a file the next person never opens. Empty when no ODD in the
        chain declares anything — silence is not a licence to invent one.
        """
        licences = getattr(parsed, 'licences', None)
        if not licences:
            return ''
        lines = [
            '',
            'Rights in the processing models, as the ODDs they came from declare them.',
            'Reproduced so the attribution they ask for travels with the compiled code;',
            'it says nothing about the ODD you wrote or about opm itself, which grants',
            'generated modules separately (LICENSING.md, Part A §2).',
            '',
        ]
        for licence in licences:
            head = licence.odd
            if licence.title:
                head += f' — {licence.title}'
            lines.append(f'  {head}')
            for detail in (licence.publisher, licence.licence, licence.target):
                if detail:
                    lines.append(f'      {detail}')
            for note in licence.notes:
                # Wrapped, not truncated: a rights statement is not ours to shorten.
                lines.append(textwrap.fill(note, width=88, initial_indent='      ',
                                           subsequent_indent='        '))
        return cls._docstring_safe('\n'.join(lines) + '\n')

    def _generate_python_module(
        self,
        parsed: ParsedOdd,
        module_name: str,
        output_mode: str,
        base_css: str | None = None,
    ) -> str:
        schema_ns = parsed.schema_ns
        odd_path = parsed.odd_path
        odd_name = Path(odd_path).stem if odd_path else ''
        odd_typst_literal = ''
        transform_config_extra = ''
        if output_mode == 'typst':
            odd_typst, typst_fn_names = collect_odd_generated_typst(parsed, output_mode=output_mode)
            typst_fn_literal = self._python_frozenset_literal(typst_fn_names)
            odd_typst_literal = (
                f'\n\nODD_GENERATED_TYPST = {self._python_triple_quoted(odd_typst)}'
                f'\n\nTYPST_RENDITION_FUNCTIONS = {typst_fn_literal}'
            )
            odd_generated_constants = odd_typst_literal
            odd_css_config = "''"
            transform_config_extra = (
                "\n        'normalize_text': normalize_markdown_xml_text,"
                "\n        'typst_functions': TYPST_RENDITION_FUNCTIONS,"
            )
        else:
            odd_css = collect_odd_generated_css(
                parsed, output_mode=output_mode, base_css=base_css
            )
            odd_generated_constants = (
                f'\n\nODD_GENERATED_CSS = {self._python_triple_quoted(odd_css)}'
                f'{odd_typst_literal}'
            )
            odd_css_config = 'ODD_GENERATED_CSS'
        # Generate NSMAP from ODD namespace declarations for XPath expressions
        nsmap_literal = self._python_nsmap_literal(parsed.nsmap)
        self._odd_nsmap = dict(parsed.nsmap or {})
        self._schema_ns = schema_ns or ''
        self._unsupported = {}
        self._problems = {}

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

        # JSON output routes unmatched elements through the PMF so they appear
        # in the record tree; every other mode recurses inline exactly as
        # before, so their generated dispatch is unchanged.
        if is_json_mode(output_mode):
            fallthrough = 'return pmf.unmatched(config, node)'
        else:
            fallthrough = 'return apply(config, child_nodes(node))'

        if cases:
            dispatch_body = (
                '    match _tag(node):\n'
                + '\n'.join(cases) + '\n'
                '        case _:\n'
                f'            {fallthrough}'
            )
        else:
            # No web-output specs — skip the match entirely; a bare `match` with no
            # `case` is a SyntaxError, and a match followed by a stray `return` is
            # also invalid.
            dispatch_body = f'    {fallthrough}'

        if output_mode == 'markdown':
            pmf_import = (
                'from opm.runtime.markdown_output_functions import (\n'
                '    MarkdownOutputFunctions,\n'
                '    normalize_markdown_xml_text,\n'
                ')'
            )
            pmf_ctor = 'MarkdownOutputFunctions()'
            transform_config_extra = "\n        'normalize_text': normalize_markdown_xml_text,"
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            webcomponents_init = "runtime_options.get('webcomponents', False)"
        elif output_mode == 'docx':
            pmf_import = (
                'from opm.runtime.docx_output_functions import (\n'
                '    DocxOutputFunctions,\n'
                '    docx_apply_children,\n'
                ')\n'
                'from opm.runtime.markdown_output_functions import normalize_markdown_xml_text'
            )
            pmf_ctor = 'DocxOutputFunctions()'
            transform_config_extra = (
                "\n        'docx_template': runtime_options.get('docx_template'),"
                "\n        'apply_children': docx_apply_children,"
                "\n        'normalize_text': normalize_markdown_xml_text,"
                "\n        'input_path': runtime_options.get('input_path'),"
            )
            transform_opts_exclude = "('xpath_extensions', 'webcomponents', 'docx_template')"
            webcomponents_init = "runtime_options.get('webcomponents', False)"
        elif output_mode == 'typst':
            pmf_import = (
                'from opm.runtime.typst_output_functions import (\n'
                '    TypstOutputFunctions,\n'
                '    escape_typst_text_node,\n'
                ')\n'
                'from opm.runtime.markdown_output_functions import normalize_markdown_xml_text'
            )
            pmf_ctor = 'TypstOutputFunctions()'
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            transform_config_extra += "\n        'text_escape': escape_typst_text_node,"
            webcomponents_init = "runtime_options.get('webcomponents', False)"
        elif output_mode == 'print':
            pmf_import = (
                'from opm.runtime.print_output_functions import PrintOutputFunctions'
            )
            pmf_ctor = 'PrintOutputFunctions()'
            # Paged media has no interactive UI; never enable web components.
            transform_config_extra = ''
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            webcomponents_init = 'False'
        elif output_mode == 'epub':
            pmf_import = (
                'from opm.runtime.epub_output_functions import EpubOutputFunctions'
            )
            pmf_ctor = 'EpubOutputFunctions()'
            # EPUB readers have no tei-publisher web-component runtime.
            transform_config_extra = (
                "\n        'input_path': runtime_options.get('input_path'),"
            )
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            webcomponents_init = 'False'
        elif is_json_mode(output_mode):
            pmf_import = (
                'from opm.runtime.json_output_functions import JsonOutputFunctions\n'
                'from opm.runtime.markdown_output_functions import normalize_markdown_xml_text'
            )
            pmf_ctor = 'JsonOutputFunctions()'
            # ODD_MODELS lets a record name not just *which* model won but what
            # it was, and lets `finish` list the models that did not win. `root`
            # is what it prunes that list against; normalize_text keeps XML
            # pretty-printing out of the text runs.
            transform_config_extra = (
                "\n        'models': ODD_MODELS,"
                "\n        'root': root,"
                "\n        'input_path': runtime_options.get('input_path'),"
                "\n        'normalize_text': normalize_markdown_xml_text,"
            )
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            webcomponents_init = 'False'
        else:
            pmf_import = 'from opm.runtime.html_output_functions import HtmlOutputFunctions'
            pmf_ctor = 'HtmlOutputFunctions()'
            transform_config_extra = ''
            transform_opts_exclude = "('xpath_extensions', 'webcomponents')"
            webcomponents_init = "runtime_options.get('webcomponents', False)"

        if is_json_mode(output_mode):
            odd_generated_constants += (
                f'\n\nODD_MODELS = {self._python_models_literal(parsed, output_mode)}'
            )

        template_helpers_block = helpers.functions_block
        unsupported_literal = self._python_unsupported_literal()

        return f'''#!/usr/bin/env python3
"""Auto-generated TEI processing model ({output_mode} output).

Source ODD: {odd_path}
schema namespace: {schema_ns}
{self._rights_block(parsed)}"""

from lxml import etree

# Namespace mappings from ODD root element (for XPath expressions)
NSMAP = {nsmap_literal}

from opm.runtime.output_functions import (
    XML_ID,
    map_rend_to_class,
    child_nodes,
    normalize,
    reset_counters,
)
{pmf_import}
from opm.runtime.pm_runtime import (
    apply as _apply_impl,
    apply_children as apply_children_impl,
    apply_template_param_value,
    inject_cached_footnotes,
    template_config,
    tag as _tag,
    ns as _ns,
    xpath_test,
    xpath_select_nodes,
    xpath_select_nodes_or_node,
)

def xpath_content_or_node(node, expr, params=None, xpath_extensions=None):
    """collection()/external-variable params: fall back to the node if unconfigured."""
    return xpath_select_nodes_or_node(
        node,
        expr,
        params,
        xpath_extensions=xpath_extensions,
        namespaces=NSMAP,
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


# Name of the ODD this module was generated from (stem, no extension).
ODD_NAME = {odd_name!r}

# ODD expressions opm can never evaluate (eXist functions, XQuery syntax). Each
# was compiled to the result a failing evaluation returns; see
# opm.odd_compiler.expression_check. `opm coverage` lists them.
ODD_UNSUPPORTED = {unsupported_literal}


def transform_output_channels():
    """Return ODD processing-model output channel(s) for this module.

    Same values as ``opm transform --type`` / ODD compile ``output_mode`` and the ``output`` key in ``transform()`` config.
    """
    return ['{output_mode}']


{odd_generated_constants}


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
    webcomponents = {webcomponents_init}
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
        'odd_css':       {odd_css_config},
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
        # Escape backslashes first so Typst ``\[`` etc. are not invalid Python escapes.
        escaped = s.replace('\\', '\\\\').replace('"""', '\\"""')
        return '"""' + escaped + '"""'

    @staticmethod
    def _python_frozenset_literal(names: frozenset[str]) -> str:
        if not names:
            return 'frozenset()'
        items = ', '.join(repr(n) for n in sorted(names))
        return f'frozenset(({items}))'

    @staticmethod
    def _python_nsmap_literal(nsmap: dict[str, str]) -> str:
        """Return namespace mappings as a Python dict literal for generated code."""
        if not nsmap:
            return '{}'
        items = ', '.join(f'{k!r}: {v!r}' for k, v in sorted(nsmap.items()))
        return '{' + items + '}'

    def _python_unsupported_literal(self) -> str:
        """``ODD_UNSUPPORTED`` as a Python list literal, one record per line."""
        if not self._unsupported:
            return '[]'
        rows = ''.join(f'    {entry.to_dict()!r},\n' for entry in self._unsupported.values())
        return f'[\n{rows}]'

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

    def _param_tier_ok(self, value: str) -> bool:
        v = value.strip()
        if not v or v == '.':
            return True
        # util:* is eXist-specific with no Python equivalent — always rejected.
        if 'util:' in v:
            return False
        # ``collection()`` and ``$global:*`` need two things to compile:
        #
        # 1. The ODD must declare the ``global`` prefix on its root element.
        #    That declaration binds the prefix in NSMAP (without it
        #    ``$global:register-root`` could not resolve anyway) and marks the
        #    ODD as opting in. An ODD that has not opted in keeps the historical
        #    fallback to the context node, which the bundled teipublisher.odd
        #    relies on for its in-document listPerson register.
        # 2. The expression must parse as XPath 3.1. Many eXist models are
        #    XQuery, not XPath — chained ``let $a := ... let $b := ...`` clauses
        #    are the common case, legal in XQuery but XPST0003 here. Those keep
        #    the fallback too, rather than compiling into something that throws
        #    (and is swallowed) at transform time.
        #
        # Opting in also means supplying [[transform.collections]] and
        # [transform.variables.<ns>] in opm.toml.
        if self._needs_external_context(v):
            return self._parses_as_xpath(v)
        return True

    @staticmethod
    def _needs_external_context(expr: str) -> bool:
        """True if *expr* depends on project config (a collection or a variable)."""
        return 'collection(' in expr or _EXTERNAL_VAR_RE.search(expr) is not None

    def _parses_as_xpath(self, expr: str) -> bool:
        """True if *expr* is XPath 3.1 opm can evaluate, rather than XQuery.

        See :func:`~opm.odd_compiler.expression_check.static_problem`: prefixes
        the ODD does not declare are bound to placeholders and ``tp:`` calls are
        stubbed, since both are project config the cached module cannot know.
        It catches the common eXist idiom of chained ``let $a := ... let $b :=
        ...`` clauses, legal XQuery but XPST0003 here.
        """
        return self._static_problem(expr) is None

    def _static_problem(self, expr: str) -> str | None:
        """Why opm can never evaluate *expr*, or ``None``; parsed once per expression."""
        if expr not in self._problems:
            self._problems[expr] = static_problem(expr, self._odd_nsmap, self._schema_ns)
        return self._problems[expr]

    def _record_unsupported(self, site, where: str, expr: str, reason: str) -> None:
        """Remember an expression compiled out, for ``ODD_UNSUPPORTED`` and the CLI.

        *site* is ``(ident, spec_el, el)``: *el* carries the predicate or, for a
        param, is the model that owns it. ``None`` records nothing.
        """
        if site is None:
            return
        ident, spec_el, el = site
        located = el
        if where.startswith('param '):
            name = where.removeprefix('param ')
            located = next(
                (p for p in el.findall(f'{{{self._TEI_NS}}}param') if p.get('name') == name),
                el,
            )
        origin = spec_origin(spec_el)
        entry = UnsupportedExpression(
            element=ident,
            where=where,
            expression=' '.join(expr.split()),
            reason=reason,
            model=model_key(ident, spec_el, el) if _local(el.tag) == 'model' else None,
            odd=origin.name if origin is not None else None,
            line=located.sourceline,
        )
        self._unsupported.setdefault(
            (entry.odd, entry.line, entry.where, entry.expression), entry,
        )

    def _predicate_test(self, pred: str, el, ident: str, spec_el) -> str:
        """The Python condition for ``@predicate`` *pred* on *el*.

        A predicate opm can never evaluate compiles to ``False``, which is what
        ``xpath_test`` returned for it on every node, and is recorded instead.
        """
        problem = self._static_problem(pred)
        if problem is not None:
            self._record_unsupported((ident, spec_el, el), 'predicate', pred, problem)
            return 'False'
        return (
            f'xpath_test(node, {pred!r}, params, '
            'xpath_extensions=config.get("xpath_extensions"), namespaces=NSMAP)'
        )

    def _param_to_expr(self, value: str, *, site=None, name: str = 'content') -> str:
        v = (value or '').strip()
        # $get(x) is tei-publisher-lib's "same node in the stored document". On a whole
        # document that is identity, but a chunk is a detached rebuild of one
        # region, so dropping it would confine preceding::/following:: to the
        # chunk — every page reporting itself as page 1. tp:source-node() is
        # registered on every parser and is identity when nothing was copied.
        v = re.sub(r'\$get\(([^()]+)\)', r'tp:source-node(\1)', v)
        if not v or v == '.':
            return 'node'
        if not self._param_tier_ok(v):
            self._record_unsupported(
                site, f'param {name}', value,
                self._static_problem(v) or 'util: functions are eXist-specific',
            )
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
        problem = self._static_problem(v)
        if problem is not None:
            # Fails on every node, where xpath_content returned an empty sequence.
            self._record_unsupported(site, f'param {name}', value, problem)
            return '[]'
        fn = 'xpath_content_or_node' if self._needs_external_context(v) else 'xpath_content'
        return (
            f'{fn}(node, '
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
            from opm.runtime.markdown_output_functions import MarkdownOutputFunctions

            return MarkdownOutputFunctions
        if output_mode == 'docx':
            from opm.runtime.docx_output_functions import DocxOutputFunctions

            return DocxOutputFunctions
        if output_mode == 'typst':
            from opm.runtime.typst_output_functions import TypstOutputFunctions

            return TypstOutputFunctions
        if output_mode == 'print':
            from opm.runtime.print_output_functions import PrintOutputFunctions

            return PrintOutputFunctions
        if is_json_mode(output_mode):
            from opm.runtime.json_output_functions import JsonOutputFunctions
            return JsonOutputFunctions
        if output_mode == 'epub':
            from opm.runtime.epub_output_functions import EpubOutputFunctions

            return EpubOutputFunctions
        from opm.runtime.html_output_functions import HtmlOutputFunctions

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

    def _python_models_literal(self, parsed: ParsedOdd, output_mode: str) -> str:
        """Emit the ``ODD_MODELS`` table keyed by the model class in ``cls[1]``.

        JSON records name the model that won (``tei-div11``); on its own that
        says *which* model matched but not *what* it was, which is the question
        an ODD author is actually asking. This side table carries the predicate
        and ``<desc>`` so the output explains itself, and ``source`` when the
        model was inherited rather than written in the ODD being compiled.
        """
        primary = Path(parsed.odd_path).resolve()
        models: dict[str, dict] = {}
        for spec in iter_element_specs(parsed):
            ident = spec.get('ident')
            if not ident or ident in ('*', 'text()'):
                continue
            inherited_from = _inherited_source(spec, primary)
            for model_el in spec.findall(f'.//{{{self._TEI_NS}}}model'):
                if not _model_matches_output_mode(model_el, output_mode):
                    continue
                key = model_key(ident, spec, model_el)
                if key in models:
                    continue
                behaviour = model_el.get('behaviour')
                entry: dict = {
                    'element': ident,
                    'behaviour': (
                        method_for_behaviour(behaviour) if behaviour else None
                    ),
                }
                if _pb_template(model_el) is not None:
                    # A template-only model has no @behaviour yet still emits a
                    # record; without this flag it is indistinguishable from a
                    # model that produces no output at all.
                    entry['template'] = True
                if inherited_from:
                    entry['source'] = inherited_from
                predicate = model_el.get('predicate')
                if predicate:
                    entry['predicate'] = predicate
                output = model_el.get('output')
                if output:
                    entry['output'] = output
                desc = _model_desc(model_el)
                if desc:
                    entry['desc'] = desc
                models[key] = entry

        lines = ['{']
        for key in sorted(models):
            lines.append(f'    {key!r}: {models[key]!r},')
        lines.append('}')
        return '\n'.join(lines)

    def _classes_expr(self, ident: str, model_el, spec_el) -> str:
        san = _sanitize_ident(ident)
        parts = [f"'tei-{san}'", repr(model_key(ident, spec_el, model_el)), 'r']
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
        config_expr: str = 'config',
    ) -> str:
        method = method_for_behaviour(behaviour)
        cls_e = self._classes_expr(ident, model_el, spec_el)
        site = (ident, spec_el, model_el)
        if content_expr is not None:
            c = content_expr
        else:
            c = self._param_to_expr(pm.get('content', '.'), site=site)

        allowed, allows_var_kw = self._accepted_method_kwargs(output_mode, method)
        emitted: set[str] = set()
        kw_parts: list[str] = []
        # ``webcomponent`` turns every model param other than ``name`` into an
        # attribute on the generated element; they are collected here and passed
        # through the method's ``optional`` mapping. Keys keep their ODD spelling
        # (``highlight-self``, not ``highlight_self``) because they become
        # attribute names verbatim.
        attribute_params: dict[str, str] = {}
        for name, value in pm.items():
            if name == 'content':
                continue
            py_name = self._normalize_param_name(name)
            if not allows_var_kw and py_name not in allowed:
                if method == 'webcomponent':
                    attribute_params[name] = self._param_to_expr(value, site=site, name=name)
                continue
            kw_parts.append(f'{py_name}={self._param_to_expr(value, site=site, name=name)}')
            emitted.add(py_name)
        if attribute_params and 'optional' not in emitted:
            items = ', '.join(f'{k!r}: {v}' for k, v in attribute_params.items())
            kw_parts.append('optional={' + items + '}')
            emitted.add('optional')
        # Keep legacy behaviour: for required kwargs not provided by the ODD model,
        # pass None explicitly (old emitter always provided defaults via P(..., None)).
        for name, param in allowed.items():
            if name in emitted:
                continue
            if param.default is inspect.Parameter.empty:
                kw_parts.append(f'{name}=None')
        kwargs_src = ', ' + ', '.join(kw_parts) if kw_parts else ''
        return f'pmf.{method}({config_expr}, node, {cls_e}, {c}{kwargs_src})'

    def _emit_template_params_dict_expr(
        self, pm: dict[str, str], *, pretty: bool = False, site=None,
    ) -> str:
        """Build the Python dict expression for ``pb:template`` ``[[param]]`` substitution."""
        param_items = []
        for name, val in pm.items():
            expr = self._param_to_expr(val, site=site, name=name)
            if expr == 'node':
                # Literal context node (``param value="."``): never pass raw TEI into
                # templates — same as XPath selecting ``.`` (see apply_template_param_value).
                param_items.append(
                    f"{name!r}: apply_template_param_value(config, node, node)"
                )
            elif expr.startswith(('xpath_content(', 'xpath_content_or_node(')):
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
            # The enclosing behaviour already puts these classes on its own
            # element, and no backend reads `cls` in `template` — but passing
            # them keeps the model attributable, which the JSON view needs to
            # say which model a template came from.
            cls_e = self._classes_expr(ident, model_el, spec_el)
            params_line = self._emit_template_params_dict_expr(
                pm, pretty=True, site=(ident, spec_el, model_el),
            )
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
        # Both forms take `r` (the @rend classes) because both build their
        # class list with _classes_expr, which references it.
        if combo:
            return (
                f'{name}(config, node, pmf, params, '
                f'xpath_extensions=config.get("xpath_extensions"), r=r)'
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
            # The template nodes are finished output; the behaviour must not
            # dispatch them again (``pm_runtime.template_config``).
            config_expr='template_config(config)',
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
                    part = f'(({part}) if {self._predicate_test(pred, child, ident, spec_el)} else [])'
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
            lines.append(f'{indent}{kw} {self._predicate_test(pred, m, ident, spec_el)}:')
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
