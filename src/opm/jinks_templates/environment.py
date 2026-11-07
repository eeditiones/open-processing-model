# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load and render jinks templates.

An [`Environment`][opm.jinks_templates.environment.Environment] finds templates
through a resolver, parses each once, and compiles each XPath expression once.
[`Template.render`][opm.jinks_templates.environment.Template.render] then only
evaluates. Everything outside the template language — where templates live,
which namespaces and functions XPath sees, how application objects become
XPath values — is passed to the environment, so the engine depends on
nothing but elementpath and lxml.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from pathlib import Path, PurePath
from typing import Any

import elementpath
from elementpath import XPathContext
from elementpath.tree_builders import get_node_tree
from elementpath.xpath31 import XPath31Parser
from elementpath.xpath_nodes import (
    AttributeNode,
    CommentNode,
    DocumentNode,
    ElementNode,
    NamespaceNode,
    ProcessingInstructionNode,
    XPathNode,
)
from elementpath.xpath_tokens import XPathArray, XPathMap
from lxml import etree

from .errors import TemplateNotFound, TemplateRuntimeError, TemplateSyntaxError
from .frontmatter import Frontmatter, split_frontmatter
from .inherit import collect_templates, expand_blocks, expand_default_blocks, get_content
from .merge import merge_deep
from .parser import (
    Block,
    CondAttr,
    Content,
    For,
    If,
    Include,
    Let,
    Pos,
    Template as TemplateNode,
    Text,
    Value,
    parse,
)

#: The frontmatter key holding templating settings.
CONFIG_PROPERTY = 'templating'

HTML = 'html'
TEXT = 'text'

_HTML_SUFFIXES = {'.html', '.htm', '.xhtml', '.xml', '.svg'}
_IGNORED_SUFFIXES = {'.tpl', '.jinks'}
_NCNAME = re.compile(r'^[A-Za-z_][\w.\-]*$')


class Markup(str):
    """A string holding markup that html mode writes without escaping.

    Use it for HTML the application already rendered. It survives being passed
    through a variable or looked up in a map; a string computed from it by an
    XPath function is an ordinary string again and is escaped.
    """


#: Finds a template by name. Returns an identifier (e.g. a path) and the
#: template's source, or ``None`` when there is no such template.
Resolver = Callable[[str], 'tuple[str, str] | None']

#: Builds an XPath parser for a set of namespace bindings.
ParserFactory = Callable[[dict[str, str]], XPath31Parser]


class FileSystemResolver:
    """Resolve template names against one or more directories, in order.

    Names are relative paths using ``/``. A name that is absolute or leads
    outside the directory it is looked up in is never resolved.
    """

    def __init__(self, searchpath: str | Path | Iterable[str | Path]) -> None:
        if isinstance(searchpath, (str, PurePath)):
            searchpath = [searchpath]
        self.searchpath = [Path(p) for p in searchpath]

    def __call__(self, name: str) -> tuple[str, str] | None:
        rel = PurePath(name)
        if rel.is_absolute() or name.startswith(('/', '\\')):
            return None
        for root in self.searchpath:
            base = root.resolve()
            path = (base / rel).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                continue
            return str(path), path.read_text(encoding='utf-8')
        return None


def mode_for(name: str | None) -> str | None:
    """The output mode a template name implies, ``None`` without a suffix.

    HTML, XML and SVG files are html, any other suffix (``.typ``, ``.css``,
    ``.md``) is text. A trailing ``.tpl`` or ``.jinks`` is ignored.
    """
    if not name or name.startswith('<'):
        return None
    suffixes = [s.lower() for s in PurePath(name).suffixes]
    while suffixes and suffixes[-1] in _IGNORED_SUFFIXES:
        suffixes.pop()
    if not suffixes:
        return None
    return HTML if suffixes[-1] in _HTML_SUFFIXES else TEXT


@dataclasses.dataclass(frozen=True, slots=True)
class _Loaded:
    """A parsed template file: its frontmatter and nodes, static includes inlined."""

    name: str
    frontmatter: Frontmatter
    nodes: tuple

    @property
    def templating(self) -> dict[str, Any]:
        value = self.frontmatter.data.get(CONFIG_PROPERTY)
        return value if isinstance(value, dict) else {}


def _templating(context: Mapping[str, Any]) -> dict[str, Any]:
    value = context.get(CONFIG_PROPERTY)
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


class Environment:
    """Shared configuration and caches for a set of templates.

    Args:
        resolver: Finds templates by name, for ``get_template``, ``extends``,
            ``use`` and includes. A directory or list of directories is
            wrapped in a
            [`FileSystemResolver`][opm.jinks_templates.environment.FileSystemResolver].
        namespaces: Prefixes available to every expression; a template adds
            more under ``templating.namespaces`` in its frontmatter.
        functions: Extension functions by ``prefix:name``; the prefix must be
            bound in *namespaces*. Ignored when *parser_factory* is given.
        parser_factory: Builds the XPath parser for a set of namespaces, for
            callers that register functions their own way.
        convert: Turns an application value that is not a map, list, string,
            number, boolean, node or dataclass into an XPath value.
        mode: Output mode (``"html"`` or ``"text"``) for templates whose name
            and frontmatter do not decide it.
    """

    def __init__(
        self,
        resolver: Resolver | str | Path | Iterable[str | Path] | None = None,
        *,
        namespaces: Mapping[str, str] | None = None,
        functions: Mapping[str, Callable[..., Any]] | None = None,
        parser_factory: ParserFactory | None = None,
        convert: Callable[[Any], Any] | None = None,
        mode: str = TEXT,
    ) -> None:
        if resolver is not None and not callable(resolver):
            resolver = FileSystemResolver(resolver)
        self.resolver: Resolver | None = resolver  # type: ignore[assignment]
        self.namespaces = dict(namespaces or {})
        self.functions = dict(functions or {})
        self.parser_factory = parser_factory or self._default_parser
        self.convert = convert
        self.mode = mode
        self._loaded: dict[str, _Loaded] = {}
        self._templates: dict[str, Template] = {}
        self._parsers: dict[frozenset, XPath31Parser] = {}
        self._compiled: dict[tuple[str, frozenset], Any] = {}
        #: Number of expressions compiled so far; tests use it to check caching.
        self.compile_count = 0

    # ── loading ─────────────────────────────────────────────────────────────

    def _default_parser(self, namespaces: dict[str, str]) -> XPath31Parser:
        parser = XPath31Parser(namespaces=namespaces)
        for qname, fn in self.functions.items():
            prefix, _, local = qname.rpartition(':')
            parser.external_function(convert_results(fn, parser, self.convert),
                                     name=local, prefix=prefix or None)
        return parser

    def resolve(self, name: str, needed_by: Pos | None = None) -> tuple[str, str]:
        """The identifier and source of *name*; raises ``TemplateNotFound``."""
        found = self.resolver(name) if self.resolver is not None else None
        if found is None:
            where = needed_by or Pos()
            if self.resolver is None:
                raise TemplateNotFound(
                    f'cannot load "{name}": no resolver in this templating context',
                    where.name, where.line)
            raise TemplateNotFound(f'template "{name}" not found', where.name, where.line)
        return found

    def _load(self, name: str, needed_by: Pos | None = None,
              stack: tuple[str, ...] = ()) -> _Loaded:
        hit = self._loaded.get(name)
        if hit is not None:
            return hit
        _, source = self.resolve(name, needed_by)
        loaded = self._parse(source, name, stack)
        self._loaded[name] = loaded
        return loaded

    def _parse(self, source: str, name: str, stack: tuple[str, ...] = ()) -> _Loaded:
        fm = split_frontmatter(source, name)
        stack = stack + (name,)

        def include(target: str, pos: Pos) -> tuple:
            if target in stack:
                raise TemplateSyntaxError(
                    f'"{target}" includes itself: {" → ".join(stack + (target,))}',
                    pos.name, pos.line)
            return self._load(target, pos, stack).nodes

        nodes = parse(fm.source, name, line_of=fm.line_of, include=include)
        return _Loaded(name, fm, nodes)

    def get_template(self, name: str) -> Template:
        """The template called *name*, parsed once and cached."""
        tpl = self._templates.get(name)
        if tpl is None:
            tpl = Template(self, self._load(name))
            self._templates[name] = tpl
        return tpl

    def from_string(self, source: str, name: str = '<string>') -> Template:
        """A template from *source*; *name* is used for messages and the mode."""
        return Template(self, self._parse(source, name))

    # ── XPath ───────────────────────────────────────────────────────────────

    def parser(self, namespaces: frozenset) -> XPath31Parser:
        parser = self._parsers.get(namespaces)
        if parser is None:
            parser = self.parser_factory(dict(namespaces))
            self._parsers[namespaces] = parser
        return parser

    def compile(self, expr: str, namespaces: frozenset, pos: Pos) -> Any:
        key = (expr, namespaces)
        token = self._compiled.get(key)
        if token is None:
            try:
                token = self.parser(namespaces).parse(expr)
            except elementpath.ElementPathError as e:
                raise TemplateRuntimeError(
                    f'invalid expression "{expr}": {e}', pos.name, pos.line, expr) from e
            self._compiled[key] = token
            self.compile_count += 1
        return token


# ── values ───────────────────────────────────────────────────────────────────


class _Converter:
    """Python values to XPath values, for one render."""

    def __init__(self, parser: XPath31Parser, hook: Callable[[Any], Any] | None) -> None:
        self.parser = parser
        self.hook = hook
        self._trees: dict[int, DocumentNode] = {}

    def __call__(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, bool, int, float, Decimal, XPathNode, XPathMap, XPathArray)):
            return value
        if isinstance(value, Mapping):
            return XPathMap(self.parser, {str(k): self(v) for k, v in value.items()})
        if isinstance(value, (list, tuple)):
            return XPathArray(self.parser, [self(v) for v in value])
        if isinstance(value, (set, frozenset)):
            return XPathArray(self.parser, [self(v) for v in sorted(value, key=str)])
        if isinstance(value, etree._Element):
            return self.node(value)
        if isinstance(value, etree._ElementTree):
            return self.document(value)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return self({f.name: getattr(value, f.name) for f in dataclasses.fields(value)})
        if isinstance(value, PurePath):
            return str(value)
        if self.hook is not None:
            return self.hook(value)
        return str(value)

    def document(self, tree: etree._ElementTree) -> DocumentNode:
        key = id(tree.getroot())
        doc = self._trees.get(key)
        if doc is None:
            doc = get_node_tree(tree)  # type: ignore[arg-type]
            self._trees[key] = doc  # type: ignore[assignment]
        return doc  # type: ignore[return-value]

    def node(self, el: etree._Element) -> XPathNode:
        doc = self.document(el.getroottree())
        try:
            return doc.elements[el]  # type: ignore[index,union-attr]
        except (KeyError, TypeError, AttributeError):
            return get_node_tree(el)  # type: ignore[arg-type,return-value]


def convert_results(fn: Callable[..., Any], parser: XPath31Parser,
                    hook: Callable[[Any], Any] | None = None) -> Callable[..., Any]:
    """*fn* with its results turned into XPath values, for registering it.

    elementpath takes an lxml element or tree returned by an extension
    function for an atomic value; wrapped, it becomes a node that paths can
    step into. Maps, lists and dataclasses are converted as context values are.
    """
    @functools.wraps(fn)
    def call(*args: Any) -> Any:
        result = fn(*args)
        convert = _Converter(parser, hook)
        if isinstance(result, (list, tuple)):
            return [convert(item) for item in result]
        return convert(result)
    # elementpath takes the arity from the argument spec, which ignores
    # __wrapped__ but honours an explicit signature.
    call.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    call.__dict__.pop('__wrapped__', None)
    return call


_DUMMY_ROOT = get_node_tree(etree.ElementTree(etree.Element('jinks')))


def _escape(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _escape_attribute(s: str) -> str:
    return s.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')


def _serialize_node(node: XPathNode) -> str:
    value = node.value
    if isinstance(node, DocumentNode):
        value = value.getroot() if hasattr(value, 'getroot') else value
    if isinstance(node, (ElementNode, DocumentNode, CommentNode, ProcessingInstructionNode)) \
            and isinstance(value, etree._Element):
        return etree.tostring(value, encoding='unicode', with_tail=False)
    if isinstance(node, (ElementNode, DocumentNode)):
        from xml.etree import ElementTree as ET  # an ElementTree-based node
        return ET.tostring(value, encoding='unicode')  # type: ignore[arg-type]
    return _escape(node.string_value)


def _unwrap_single(s: str, force: bool) -> str:
    """The children of *s* if it is a single element to unwrap (``tmpl:content``)."""
    st = s.strip()
    m = re.match(r'<([\w:.-]+)\b[^>]*>', st)
    if m is None:
        return s
    tag = m.group(1)
    if not force and tag != 'template':
        return s
    if m.group(0).endswith('/>') or not st.endswith(f'</{tag}>'):
        return s
    depth = 0
    pattern = re.compile(rf'<(/?){re.escape(tag)}\b[^>]*?(/?)>')
    for t in pattern.finditer(st):
        if t.group(2):
            continue
        depth += -1 if t.group(1) else 1
        if depth == 0 and t.end() != len(st):
            return s
    return st[m.end():len(st) - len(f'</{tag}>')]


# ── templates ────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class _Built:
    nodes: tuple
    blocks: tuple  # templates passed on to dynamic includes


class Template:
    """A loaded template, ready to render.

    Get one from [`Environment.get_template`][opm.jinks_templates.environment.Environment.get_template]
    or [`Environment.from_string`][opm.jinks_templates.environment.Environment.from_string].
    """

    def __init__(self, env: Environment, loaded: _Loaded) -> None:
        self.env = env
        self.name = loaded.name
        self._levels = self._chain(loaded)
        self._built: dict[tuple, _Built] = {}

    def _chain(self, loaded: _Loaded) -> list[_Loaded]:
        levels = [loaded]
        names = [loaded.name]
        while (parent := levels[-1].templating.get('extends')):
            parent = str(parent)
            if parent in names:
                raise TemplateSyntaxError(
                    f'extends cycle: {" → ".join(names + [parent])}', loaded.name)
            names.append(parent)
            levels.append(self.env._load(parent, Pos(levels[-1].name)))
        return levels

    @property
    def frontmatter(self) -> list[dict[str, Any]]:
        """The frontmatter of the template and its parents, the root layout first."""
        return [level.frontmatter.data for level in reversed(self._levels)]

    def context(self, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """*base* with the frontmatter of the ``extends`` chain merged over it.

        The root layout's frontmatter comes first and the template's own last,
        so a child overrides its parent, and frontmatter overrides *base*.
        """
        return merge_deep(base, *self.frontmatter)

    def _use_templates(self, files: list[str], pos: Pos) -> list[TemplateNode]:
        found: list[TemplateNode] = []
        for file in files:
            found.extend(collect_templates(self.env._load(file, pos).nodes))
        return found

    def _build(self, use: tuple[str, ...], blocks: tuple) -> _Built:
        key = (use, blocks)
        hit = self._built.get(key)
        if hit is not None:
            return hit
        passed = list(blocks)
        for i, level in enumerate(self._levels):
            files = list(use) if i == 0 else _as_list(level.templating.get('use'))
            incoming = passed + self._use_templates(files, Pos(level.name))
            ast = expand_blocks(level.nodes, incoming)
            if i + 1 < len(self._levels):
                passed = ([t for t in incoming if t.name != 'content']
                          + collect_templates(ast))
                body = get_content(ast)
                # Unlike jinks, a child holding nothing but templates and
                # whitespace leaves the parent's default content in place.
                if not all(isinstance(n, Text) and not n.text.strip() for n in body):
                    passed.append(TemplateNode(
                        'content', body,
                        unwrap=bool(level.templating.get('strip-root')), pos=Pos(level.name)))
            else:
                built = _Built(expand_default_blocks(ast),
                               tuple(t for t in passed if t.name != 'content'))
        self._built[key] = built
        return built

    def render(self, context: Mapping[str, Any] | None = None, /, **variables: Any) -> str:
        """Render the template.

        Args:
            context: The context map. The frontmatter of the template and its
                parents is merged over it (see
                [`context`][opm.jinks_templates.environment.Template.context]).
                The result is ``$context`` in expressions, and each top-level
                key is also a variable of its own.
            **variables: Further top-level entries, set after the merge so no
                frontmatter can change them.

        Raises:
            TemplateSyntaxError: A template in the chain is malformed.
            TemplateNotFound: A parent, include or ``use`` file is missing.
            TemplateRuntimeError: An expression failed.
        """
        # As in jinks, `use` files come from the context and the template's
        # own frontmatter; each parent adds those its own frontmatter names.
        use = _as_list(_templating(context or {}).get('use'))
        use += [f for f in _as_list(self._levels[0].templating.get('use')) if f not in use]
        merged = self.context(context)
        if variables:
            merged = {**merged, **variables}
        return self._render(merged, tuple(use), ())

    def _render(self, merged: dict[str, Any], use: tuple[str, ...], blocks: tuple,
                mode: str | None = None) -> str:
        built = self._build(use, blocks)
        templating = _templating(merged)
        ns = {**self.env.namespaces, **(templating.get('namespaces') or {})}
        nskey = frozenset(ns.items())
        if mode is None:
            setting = str(templating.get('mode') or '').lower()
            mode = HTML if setting in (HTML, 'xml') else TEXT if setting == TEXT else None
        mode = mode or mode_for(self.name) or self.env.mode
        renderer = _Renderer(self, merged, nskey, mode, built.blocks)
        out: list[str] = []
        renderer.emit(built.nodes, out)
        return ''.join(out)


class _Renderer:
    def __init__(self, template: Template, merged: dict[str, Any], nskey: frozenset,
                 mode: str, blocks: tuple) -> None:
        self.template = template
        self.env = template.env
        self.merged = merged
        self.nskey = nskey
        self.mode = mode
        self.blocks = blocks
        parser = self.env.parser(nskey)
        self.helper = parser.parse('()')
        convert = _Converter(parser, self.env.convert)
        variables: dict[str, Any] = {}
        for key, value in merged.items():
            if key != '$schema' and _NCNAME.match(key):
                variables[key] = convert(value)
        variables['context'] = XPathMap(
            parser, {k: variables[k] if k in variables else convert(v) for k, v in merged.items()})
        self.ctx = XPathContext(root=_DUMMY_ROOT, variables={})
        self.ctx.variables.update(variables)

    # ── evaluation ──────────────────────────────────────────────────────────

    def evaluate(self, expr: str, pos: Pos) -> list:
        token = self.env.compile(expr, self.nskey, pos)
        try:
            return list(token.select(self.ctx))
        except elementpath.ElementPathError as e:
            raise TemplateRuntimeError(
                f'error evaluating "{expr}": {e}', pos.name, pos.line, expr) from e

    def boolean(self, items: list, expr: str, pos: Pos) -> bool:
        try:
            return bool(self.helper.boolean_value(items))
        except elementpath.ElementPathError as e:
            raise TemplateRuntimeError(
                f'error evaluating "{expr}": {e}', pos.name, pos.line, expr) from e

    def bind(self, var: str, value: Any) -> Any:
        old = self.ctx.variables.get(var, _MISSING)
        self.ctx.variables[var] = value
        return old

    def unbind(self, var: str, old: Any) -> None:
        if old is _MISSING:
            self.ctx.variables.pop(var, None)
        else:
            self.ctx.variables[var] = old

    # ── values ──────────────────────────────────────────────────────────────

    def flatten(self, items: Iterable) -> Iterable:
        """``tmpl:valueOf``: arrays flattened, maps as JSON."""
        for item in items:
            if isinstance(item, XPathArray):
                for member in item.items():
                    yield from self.flatten(member if isinstance(member, list) else [member])
            elif isinstance(item, XPathMap):
                yield self.json(item)
            else:
                yield item

    def json(self, item: XPathMap) -> str:
        token = self.env.compile("serialize($m, map{'method': 'json'})", self.nskey, Pos())
        ctx = XPathContext(root=_DUMMY_ROOT, variables={'m': item})
        return str(token.evaluate(ctx))

    def string(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, bool):
            return 'true' if item else 'false'
        return self.helper.string_value(item)

    def write(self, items: list, out: list[str]) -> None:
        prev_atomic = False
        for item in self.flatten(items):
            if isinstance(item, (XPathNode, etree._Element)):
                if isinstance(item, etree._Element):
                    text = (etree.tostring(item, encoding='unicode', with_tail=False)
                            if self.mode == HTML else ''.join(item.itertext()))
                elif self.mode == HTML:
                    text = _serialize_node(item)
                else:
                    text = item.string_value
                out.append(text)
                prev_atomic = False
                continue
            if prev_atomic:
                out.append(' ')
            text = self.string(item)
            if self.mode == HTML and not isinstance(item, Markup):
                text = _escape(text)
            out.append(text)
            prev_atomic = True

    # ── nodes ───────────────────────────────────────────────────────────────

    def emit(self, nodes: tuple, out: list[str]) -> None:
        for node in nodes:
            match node:
                case Text():
                    out.append(node.text)
                case Value():
                    self.write(self.evaluate(node.expr, node.pos), out)
                case CondAttr():
                    self.cond_attr(node, out)
                case If():
                    self.emit_if(node, out)
                case For():
                    items = self.evaluate(node.expr, node.pos)
                    old = self.ctx.variables.get(node.var, _MISSING)
                    try:
                        for item in items:
                            self.ctx.variables[node.var] = item
                            self.emit(node.body, out)
                    finally:
                        self.unbind(node.var, old)
                case Let():
                    items = self.evaluate(node.expr, node.pos)
                    old = self.bind(node.var, items[0] if len(items) == 1 else items)
                    try:
                        self.emit(node.body, out)
                    finally:
                        self.unbind(node.var, old)
                case Include():
                    self.include(node, out)
                case Content():
                    inner: list[str] = []
                    self.emit(node.body, inner)
                    text = ''.join(inner)
                    if self.mode == HTML:
                        text = _unwrap_single(text, node.unwrap)
                    out.append(text)
                case TemplateNode():
                    # Outside of inheritance a template's content stays in place.
                    self.emit(node.body, out)
                case Block():
                    self.emit(node.body, out)

    def emit_if(self, node: If, out: list[str]) -> None:
        if self.boolean(self.evaluate(node.expr, node.pos), node.expr, node.pos):
            self.emit(node.body, out)
        elif node.orelse is not None:
            self.emit(node.orelse, out)

    def cond_attr(self, node: CondAttr, out: list[str]) -> None:
        items = list(self.flatten(self.evaluate(node.expr, node.pos)))
        if not items:
            return
        if len(items) == 1 and not self.boolean(items, node.expr, node.pos):
            return
        value = ' '.join(
            item.string_value if isinstance(item, XPathNode) else self.string(item)
            for item in items)
        out.append(f' {node.name}="{_escape_attribute(value)}"')

    def include(self, node: Include, out: list[str]) -> None:
        items = self.evaluate(node.target, node.pos)
        if len(items) != 1:
            raise TemplateRuntimeError(
                f'include target "{node.target}" must be a single string', node.pos.name,
                node.pos.line, node.target)
        target = self.string(items[0])
        included = self.env._templates.get(target)
        if included is None:
            included = Template(self.env, self.env._load(target, node.pos))
            self.env._templates[target] = included
        # The includer's context, without the settings that already shaped it.
        base = dict(self.merged)
        settings = {k: v for k, v in _templating(base).items() if k not in ('extends', 'use')}
        base[CONFIG_PROPERTY] = settings
        merged = included.context(base)
        out.append(included._render(merged, (), self.blocks, self.mode))


_MISSING = object()
