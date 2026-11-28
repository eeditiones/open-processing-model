# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The XPath parser opm evaluates ODD expressions with.

XPath 3.1 as elementpath implements it, with three changes: ``fn:id()`` answers
from a per-document index instead of walking the whole document on every call,
a lookup may start a path (``$parameters?root/ancestor::TEI``), and paths
return their nodes in document order (see
[`_PathOperatorMixin`][opm.runtime.xpath_parser._PathOperatorMixin]).
elementpath visits every node of the target document for each lookup, which on
register-heavy editions — ``id($key, collection(...))`` in a predicate or param
— dominated whole runs. ODDs are shared with TEI Publisher, so the fix has to
live in the standard function rather than in a ``tp:`` alternative.

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

from elementpath.datatypes import Id
from elementpath.xpath31.xpath31_parser import XPath31Parser
from elementpath.xpath_context import XPathSchemaContext
from elementpath.xpath_nodes import DocumentNode, ElementNode, EtreeElementNode, XPathNode

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


class OpmXPathParser(XPath31Parser):
    """XPath 3.1 with an indexed ``fn:id()``; see the module docstring."""


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


# A subclass holds its own copy of the symbol table, so the stock XPath31Parser
# keeps elementpath's implementation.
OpmXPathParser.symbol_table['id'] = _IndexedIdFunction


def _document_order(nodes: list) -> list:
    """*nodes* sorted in document order; trees in the order they first appear."""
    trees: dict[int, int] = {}
    for node in nodes:
        trees.setdefault(id(getattr(node, 'tree', None)), len(trees))
    return sorted(nodes, key=lambda n: (trees[id(getattr(n, 'tree', None))], n.position))


class _PathOperatorMixin:
    """``/`` and ``//`` as XPath 3.1 defines them, where elementpath 5 does not.

    Two differences:

    - A lookup may stand on the left. XPath 3.1 allows any postfix expression
      before ``/``, so ``$parameters?root/ancestor::TEI`` is a path starting at
      the node the lookup returns; TEI Publisher ODDs use exactly that.
      elementpath only accepts a fixed list of left operands and rejects a
      lookup with ``XPST0003``.
    - The result is in document order. elementpath yields the step results
      context node by context node, so when the context nodes are nested the
      order breaks: in ``note//persName`` a name directly in the note comes
      before one inside an earlier ``bibl``, and ``head(note//persName)``
      picks the wrong one. A path ending in atomic values (``…/string()``)
      keeps its order, as the specification says.
    """

    def led(self, left: Any) -> Any:
        if left.symbol == '?' and len(left) in (1, 2):
            if self.parser.next_token.label not in self.parser.PATH_STEP_LABELS:  # type: ignore[attr-defined]
                self.parser.expected_next(*self.parser.PATH_STEP_SYMBOLS)  # type: ignore[attr-defined]
            self[:] = left, self.parser.expression(75)  # type: ignore[attr-defined]
            return self
        return super().led(left)  # type: ignore[misc]

    def select(self, context: Any = None) -> Iterator[Any]:
        results = super().select(context)  # type: ignore[misc]
        if len(self) != 2:  # type: ignore[arg-type]
            yield from results
            return
        items = list(results)
        if len(items) > 1 and all(isinstance(item, XPathNode) for item in items):
            items = _document_order(items)
        yield from items


for _symbol in ('/', '//'):
    _base = OpmXPathParser.symbol_table[_symbol]
    OpmXPathParser.symbol_table[_symbol] = type(
        _base.__name__, (_PathOperatorMixin, _base), {'__module__': __name__},
    )
del _symbol, _base
OpmXPathParser.build()
