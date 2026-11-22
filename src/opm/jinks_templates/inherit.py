# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template inheritance: ``extends``, ``use``, blocks and templates.

A port of ``tmpl:to-ast`` and its helpers from jinks-templates. Each level of
the ``extends`` chain fills its own blocks from the templates collected so
far, hands its remaining content up as the ``content`` template, and adds its
own templates to the ones passed on. Blocks still empty at the top of the
chain show their default content.
"""

from __future__ import annotations

from collections.abc import Iterable

from .errors import TemplateSyntaxError
from .parser import Block, Content, Template, map_children


def expand_blocks(nodes: tuple, templates: list[Template]) -> tuple:
    """Fill each block in *nodes* with the templates of the same name.

    ``template!`` templates replace all others. Templates with an ``order``
    come first, sorted by it; the others follow in reverse order of
    collection, which puts a parent's templates before its child's, as in
    jinks. A block without templates is left for a later level.
    """
    out: list = []
    for node in nodes:
        if isinstance(node, Block):
            matching = [t for t in templates if t.name == node.name]
            if not matching:
                out.append(node)
                continue
            selected = [t for t in matching if t.overwrite] or matching
            ordered = sorted((t for t in selected if t.order), key=_order_key)
            unordered = [t for t in selected if not t.order]
            for tpl in ordered + unordered[::-1]:
                if tpl.unwrap:
                    out.append(Content(tpl.body, unwrap=True))
                elif tpl.name == 'content':
                    out.append(Content(tpl.body))
                else:
                    out.extend(tpl.body)
        else:
            out.append(map_children(node, lambda c: expand_blocks(c, templates)))
    return tuple(out)


def _order_key(tpl: Template) -> int:
    try:
        return int(tpl.order)
    except ValueError:
        raise TemplateSyntaxError(
            f'order of template "{tpl.name}" must be an integer, not "{tpl.order}"',
            tpl.pos.name, tpl.pos.line) from None


def expand_default_blocks(nodes: tuple) -> tuple:
    """Replace each remaining block by its default content."""
    out: list = []
    for node in nodes:
        if isinstance(node, Block):
            out.extend(expand_default_blocks(node.body))
        else:
            out.append(map_children(node, expand_default_blocks))
    return tuple(out)


def get_content(nodes: tuple) -> tuple:
    """*nodes* without their templates: what a child adds to ``content``."""
    return tuple(
        map_children(n, get_content) for n in nodes if not isinstance(n, Template)
    )


def collect_templates(nodes: Iterable) -> list[Template]:
    """All templates in *nodes*, in document order, nested ones included."""
    found: list[Template] = []

    def walk(seq: Iterable) -> None:
        for node in seq:
            if isinstance(node, Template):
                found.append(node)
            for child in _children(node):
                walk(child)

    walk(nodes)
    return found


def _children(node) -> list[tuple]:
    seqs = []
    for name in ('body', 'orelse'):
        value = getattr(node, name, None)
        if isinstance(value, tuple):
            seqs.append(value)
    return seqs
