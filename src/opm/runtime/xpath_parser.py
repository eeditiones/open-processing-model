# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The XPath parser opm evaluates ODD expressions with.

XQuery 3.1 as the vendored elementpath implements it
([`opm._vendor.elementpath`][opm._vendor]), with one change: ``fn:id()`` answers
from a per-document index instead of walking the whole document on every call.
elementpath visits every node of the target document for each lookup, which on
register-heavy editions — ``id($key, collection(...))`` in a predicate or param
— dominated whole runs. ODDs are shared with TEI Publisher, so the fix has to
live in the standard function rather than in a ``tp:`` alternative.

XQuery rather than XPath because the ODDs are TEI Publisher's, and eXist
evaluates them as XQuery: element constructors, ``let`` chains and
``try``/``catch`` all appear in the stock models. XQuery 3.1 is a superset of
XPath 3.1, so every expression that parsed before parses the same way — ``<``
keeps its comparison meaning and gains a constructor reading only where an
operand cannot follow.

The index is built from the same node tree with the same ``is_id`` test, and
the first element in document order wins for each value, exactly as in
elementpath: the same nodes come back in the same order, only faster. It is
built once per document and run and kept in the running
[`XPathEnvironment`][opm.runtime.xpath_env.XPathEnvironment]'s cache. Finding which
document a lookup targets is done by [`root_of`][opm.runtime.xpath_parser.root_of] rather than by scanning
the documents for the node.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from opm._vendor.elementpath.datatypes import Id
from opm._vendor.elementpath.xpath31.xpath31_parser import XPath31Parser
from opm._vendor.elementpath.xpath_context import XPathSchemaContext
from opm._vendor.elementpath.xpath_nodes import DocumentNode, ElementNode, EtreeElementNode, XPathNode
from opm._vendor.elementpath.xquery31 import XQuery31Parser

IdIndex = dict[str, tuple[int, EtreeElementNode]]


def build_id_index(root: XPathNode) -> IdIndex:
    """``{id: (document position, element)}`` for the node tree under *root*.

    The test is elementpath's: an attribute is an ID when its ``is_id`` holds
    (``xml:id``, or an attribute a schema types as ID), and for each value the
    first element in document order wins.
    """
    index: IdIndex = {}
    for position, element in enumerate(root.iter_descendants()):
        if not isinstance(element, EtreeElementNode):
            continue
        for attr in element.attributes:
            if isinstance(attr.value, str) and attr.is_id:
                index.setdefault(attr.value, (position, element))
    return index


def root_of(context: Any, node: XPathNode) -> XPathNode | None:
    """What ``context.get_root(node)`` returns, found without scanning.

    elementpath answers by iterating every node of the context tree, then of
    each registered document, until it meets *node* — a whole-document walk per
    ``fn:id()`` call, and on a register lookup the main document is walked in
    full before the register is. A tree contains *node* exactly when its root
    is among *node*'s ancestors-or-self, which the parent chain gives directly;
    the candidates are tried in the same order.
    """
    chain = set()
    current: Any = node
    while current is not None:
        chain.add(id(current))
        current = current.parent
    root = context.root
    if isinstance(root, (DocumentNode, ElementNode)) and id(root) in chain:
        return root
    if context.documents is not None:
        for doc in context.documents.values():
            if doc is not None and id(doc) in chain:
                return doc
    return None


def _id_index(root: XPathNode) -> IdIndex:
    """The index for *root*, from the running environment's cache when there is one."""
    from .xpath_env import current_environment  # noqa: PLC0415 — xpath_env imports this module

    env = current_environment()
    return env.id_index(root) if env is not None else build_id_index(root)


class OpmXPathParser(XQuery31Parser):
    """XQuery 3.1 with an indexed ``fn:id()``; see the module docstring."""


class _IndexedIdFunction(XPath31Parser.symbol_table['id']):  # type: ignore[misc,valid-type]
    """``fn:id()`` over `build_id_index`; argument handling as in elementpath."""

    def select(self, context: Any = None) -> Iterator[EtreeElementNode]:
        if self.context is not None:
            context = self.context

        idrefs = {
            x for item in self[0].select(context)
            for x in self.string_value(item).split() if Id.is_valid(x)
        }

        if context is None:
            raise self.missing_context()

        if len(self) == 1:
            node = context.item
            if node is None:
                node = context.root
        else:
            node = self.get_argument(context, index=1)

        if not isinstance(node, XPathNode):
            raise self.error('XPTY0004')

        if isinstance(context, XPathSchemaContext):
            return

        root = root_of(context, node)
        if root is None:
            return

        index = _id_index(root)
        hits = sorted((index[ref] for ref in idrefs if ref in index), key=lambda hit: hit[0])
        for _, element in hits:
            yield element


# A subclass holds its own copy of the symbol table, so neither the stock
# XPath31Parser nor XQuery31Parser loses elementpath's implementation.
OpmXPathParser.symbol_table['id'] = _IndexedIdFunction
OpmXPathParser.build()
