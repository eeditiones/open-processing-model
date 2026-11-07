# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tokenize and parse jinks templates into a tree of nodes.

A port of ``tmpl:tokenize`` and ``tmpl:parse`` from jinks-templates
(``content/templates.xqm``). The tokenizer uses the same regular expressions;
the parser builds Python nodes instead of an XML syntax tree.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .errors import TemplateSyntaxError

# ── nodes ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Pos:
    """Where a node comes from: template name and 1-based line."""

    name: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class Text:
    """Literal template text."""

    text: str


@dataclass(frozen=True, slots=True)
class Value:
    """``[[ expr ]]``: insert the value of *expr*."""

    expr: str
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class CondAttr:
    """``name="![[ expr ]]"``: an attribute written only if *expr* is true."""

    name: str
    expr: str
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class If:
    """``[% if %]``; ``orelse`` holds an ``elif`` as a nested ``If``, or the ``else`` body."""

    expr: str
    body: tuple
    orelse: tuple | None = None
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class For:
    """``[% for $var in expr %]``."""

    var: str
    expr: str
    body: tuple
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class Let:
    """``[% let $var = expr %]``."""

    var: str
    expr: str
    body: tuple
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class Include:
    """``[% include expr %]`` whose target is computed while rendering."""

    target: str
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class Block:
    """``[% block name %]``, with its default content."""

    name: str
    body: tuple
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class Template:
    """``[% template name order? %]`` or ``[% template! name %]``.

    ``unwrap`` is set on the ``content`` template built from a child whose
    frontmatter has ``templating.strip-root``.
    """

    name: str
    body: tuple
    order: str = ''
    overwrite: bool = False
    unwrap: bool = False
    pos: Pos = Pos()


@dataclass(frozen=True, slots=True)
class Content:
    """The ``content`` block filled from a child template (``tmpl:content``)."""

    body: tuple
    unwrap: bool = False


Node = Text | Value | CondAttr | If | For | Let | Include | Block | Template | Content

# ── tokenizer ────────────────────────────────────────────────────────────────

#: The regular expressions of ``tmpl:tokenize``, in the same order.
TOKEN_REGEX = [
    r'\[%\s*(raw)\s*%\](.*?)\[%\s*(endraw)\s*%\]',
    r'\[(#)(.*?)#\]',
    r'\[%\s*(end\w+)\s*%\]',
    r'\[%\s*(for)\s+(\$[\w-]+)\s+in\s+(.+?)%\]',
    r'\[%\s*(let)\s+(\$[\w-]+)\s+=\s+(.+?)%\]',
    r'\[%\s*(if)\s+(.+?)%\]',
    r'\[%\s*(elif)\s+(.+?)%\]',
    r'\[%\s*(else)\s*%\]',
    r'\[%\s*(include)\s+(.+?)%\]',
    r'\[%\s*(block)\s+(.+?)%\]',
    r'\[%\s*(template!?)\s+(\S+?)(?:\s+(.*?))?%\]',
    r'\[%\s*(import)\s+["\'](.+?)["\']\s+as\s+["\']([\w\-_]+)["\'](?:\s+at\s+["\'](.+?)["\'])?\s*%\]',
    r'(\s*([\w:.-]+)\s*=\s*"(!)\[\[(.+?)\]\]")',
    r'\[(\[)(.+?)\]\]',
]

_TOKENS = re.compile('(?:' + '|'.join(TOKEN_REGEX) + ')', re.IGNORECASE | re.DOTALL)
_COND_ATTR = re.compile(r'^\s*([\w:.-]+)\s*=\s*"(!)\[\[(.+?)\]\]"$', re.DOTALL)
_SHORT_FORM = re.compile(r'^[^$][\w_-]+$')
_STATIC_INCLUDE = re.compile(r'^"([^"]*)"$')
_END_TAGS = ('endfor', 'endlet', 'endif', 'endblock', 'endtemplate')


def _norm(s: str | None) -> str:
    return ' '.join((s or '').split())


@dataclass(slots=True)
class Token:
    """A directive found by the tokenizer."""

    kind: str
    offset: int
    attrs: dict[str, str] = field(default_factory=dict)


def tokenize(source: str) -> list[str | Token]:
    """Split *source* into text and directive tokens (``tmpl:tokenize``).

    Comments are dropped; ``[% raw %]`` content comes back as text, with its
    whitespace normalized as jinks does.
    """
    out: list[str | Token] = []
    last = 0
    for m in _TOKENS.finditer(source):
        if m.start() > last:
            out.append(source[last:m.start()])
        last = m.end()
        groups = [m.group(i) for i in range(1, (m.lastindex or 0) + 1) if m.start(i) != -1]
        kind = groups[0]
        g = groups + [''] * 4
        text = m.group(0)
        cond = _COND_ATTR.match(text)
        if cond and cond.group(2) == '!':
            out.append(Token('cond-attr', m.start(), {'name': _norm(cond.group(1)), 'expr': _norm(cond.group(3))}))
            continue
        tok: Token | str | None
        match kind:
            case 'for' | 'let':
                tok = Token(kind, m.start(), {'var': _norm(g[1]), 'expr': _norm(g[2])})
            case 'if' | 'elif':
                tok = Token(kind, m.start(), {'expr': _norm(g[1])})
            case 'else' | 'endfor' | 'endlet' | 'endif' | 'endblock' | 'endtemplate':
                tok = Token(kind, m.start())
            case 'include':
                tok = Token(kind, m.start(), {'target': _norm(g[1])})
            case 'template':
                tok = Token(kind, m.start(), {'name': _norm(g[1]), 'order': _norm(g[2])})
            case 'template!':
                tok = Token('template', m.start(), {'name': _norm(g[1]), 'overwrite': 'true'})
            case 'block':
                tok = Token(kind, m.start(), {'name': _norm(g[1])})
            case '#':
                tok = None
            case 'raw':
                tok = _norm(g[1])
            case 'import':
                tok = Token(kind, m.start(), {'uri': _norm(g[1]), 'as': _norm(g[2])})
            case '[':
                tok = Token('value', m.start(), {'expr': _norm(g[1])})
            case _:
                tok = Token('error', m.start(), {'text': text})
        if tok is not None and tok != '':
            out.append(tok)
    if last < len(source):
        out.append(source[last:])
    return out


# ── parser ───────────────────────────────────────────────────────────────────

#: Resolves a static ``[% include "path" %]`` to its parsed nodes.
StaticIncluder = Callable[[str, Pos], tuple]


class _Parser:
    def __init__(self, tokens: list[str | Token], name: str | None,
                 line_of: Callable[[int], int], include: StaticIncluder | None) -> None:
        self.tokens = tokens
        self.i = 0
        self.name = name
        self.line_of = line_of
        self.include = include

    def pos(self, tok: Token) -> Pos:
        return Pos(self.name, self.line_of(tok.offset))

    def error(self, msg: str, tok: Token | None) -> TemplateSyntaxError:
        return TemplateSyntaxError(msg, self.name, self.line_of(tok.offset) if tok else None)

    def parse(self, until: tuple[str, ...] = (), opener: Token | None = None) -> tuple[list, Token | None]:
        """Parse nodes up to one of the *until* tokens, returned as the second item."""
        nodes: list = []
        while self.i < len(self.tokens):
            tok = self.tokens[self.i]
            self.i += 1
            if isinstance(tok, str):
                nodes.append(Text(tok))
                continue
            kind = tok.kind
            if kind in until:
                return nodes, tok
            match kind:
                case 'error':
                    raise self.error(f'unknown directive {tok.attrs["text"]}', tok)
                case 'value':
                    expr = tok.attrs['expr']
                    if _SHORT_FORM.match(expr):
                        expr = '$' + expr
                    nodes.append(Value(expr, self.pos(tok)))
                case 'cond-attr':
                    expr = tok.attrs['expr']
                    if _SHORT_FORM.match(expr):
                        expr = '$' + expr
                    nodes.append(CondAttr(tok.attrs['name'], expr, self.pos(tok)))
                case 'if':
                    nodes.append(self.parse_if(tok))
                case 'for' | 'let':
                    body, _ = self.parse_body(tok, 'end' + kind)
                    cls = For if kind == 'for' else Let
                    nodes.append(cls(tok.attrs['var'].lstrip('$'), tok.attrs['expr'], body, self.pos(tok)))
                case 'block':
                    body, _ = self.parse_body(tok, 'endblock')
                    nodes.append(Block(tok.attrs['name'], body, self.pos(tok)))
                case 'template':
                    body, _ = self.parse_body(tok, 'endtemplate')
                    nodes.append(Template(
                        tok.attrs['name'], body, tok.attrs.get('order', ''),
                        tok.attrs.get('overwrite') == 'true', pos=self.pos(tok)))
                case 'include':
                    target = tok.attrs['target']
                    static = _STATIC_INCLUDE.match(target)
                    if static:
                        if self.include is None:
                            raise self.error('include is not available in this templating context', tok)
                        nodes.extend(self.include(static.group(1), self.pos(tok)))
                    else:
                        nodes.append(Include(target, self.pos(tok)))
                case 'import':
                    raise self.error(
                        f'[% import %] of XQuery module "{tok.attrs["uri"]}" is not supported: '
                        'XPath extension functions have to be registered with the environment '
                        '(in opm: xpath_extensions in opm.toml)', tok)
                case 'elif' | 'else':
                    raise self.error(f'[% {kind} %] outside of [% if %]', tok)
                case _ if kind in _END_TAGS:
                    raise self.error(f'unexpected [% {kind} %]', tok)
        if until:
            missing = 'endif' if 'endif' in until else until[0]
            raise self.error(f'Missing {missing}', opener)
        return nodes, None

    def parse_body(self, opener: Token, end: str) -> tuple[tuple, Token | None]:
        body, closer = self.parse((end,), opener)
        return tuple(body), closer

    def parse_if(self, opener: Token) -> If:
        body, closer = self.parse(('elif', 'else', 'endif'), opener)
        orelse: tuple | None = None
        assert closer is not None
        if closer.kind == 'elif':
            orelse = (self.parse_if(closer),)
        elif closer.kind == 'else':
            rest, _ = self.parse(('endif',), opener)
            orelse = tuple(rest)
        return If(opener.attrs['expr'], tuple(body), orelse, self.pos(opener))


def parse(source: str, name: str | None = None, *,
          line_of: Callable[[int], int] | None = None,
          include: StaticIncluder | None = None) -> tuple:
    """Parse *source* (without frontmatter) into a tuple of nodes.

    Args:
        source: The template text.
        name: Template name for error messages.
        line_of: Maps an offset in *source* to a line in the original file.
        include: Called for each static include; returns the included nodes.

    Raises:
        TemplateSyntaxError: The template is malformed.
    """
    if line_of is None:
        def line_of(offset: int) -> int:
            return source.count('\n', 0, offset) + 1
    nodes, _ = _Parser(tokenize(source), name, line_of, include).parse()
    return move_cond_attrs(tuple(nodes))


# ── conditional attributes ───────────────────────────────────────────────────

_CHILD_FIELDS = {If: ('body', 'orelse'), For: ('body',), Let: ('body',), Block: ('body',),
                 Template: ('body',), Content: ('body',)}


def map_children(node, fn: Callable[[tuple], tuple]):
    """*node* with *fn* applied to each of its child sequences."""
    fields = _CHILD_FIELDS.get(type(node))
    if not fields:
        return node
    changes = {}
    for f in fields:
        value = getattr(node, f)
        if value is not None:
            changes[f] = fn(value)
    return replace(node, **changes)


def move_cond_attrs(nodes: tuple) -> tuple:
    """Move conditional attributes inside the tag they belong to.

    The tokenizer takes ``attr="![[ … ]]"`` out of the text, so the tag's
    closing ``>`` follows later. Pending conditional attributes are placed
    right before the next ``>`` (or ``/>``) in the same sequence, as jinks'
    text mode does in ``tmpl:move-cond-attrs``.
    """
    nodes = tuple(map_children(n, move_cond_attrs) for n in nodes)
    out: list = []
    pending: list = []
    for node in nodes:
        if isinstance(node, CondAttr):
            pending.append(node)
        elif isinstance(node, Text) and pending and '>' in node.text:
            before, after = node.text.split('>', 1)
            selfclosing = re.search(r'/\s*$', before) is not None
            if selfclosing:
                before = re.sub(r'\s*/\s*$', '', before)
            out.append(Text(before))
            out.extend(pending)
            out.append(Text('/>' if selfclosing else '>'))
            if after:
                out.append(Text(after))
            pending = []
        else:
            out.append(node)
    out.extend(pending)
    return tuple(out)
