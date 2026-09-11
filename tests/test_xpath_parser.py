"""``fn:id()`` answered from a per-document index (:mod:`opm.runtime.xpath_parser`)."""

from __future__ import annotations

import pytest
from elementpath import XPathContext
from elementpath.tree_builders import get_node_tree
from elementpath.xpath31.xpath31_parser import XPath31Parser
from lxml import etree

from opm.runtime.xpath_env import XPathEnvironment
from opm.runtime.xpath_parser import OpmXPathParser

TEI = 'http://www.tei-c.org/ns/1.0'
DOC = (
    f'<TEI xmlns="{TEI}"><text><body>'
    '<div xml:id="a"><p xml:id="b">one</p><p id="c">plain @id</p></div>'
    '<div xml:id="d"><p xml:id="b">second b</p><p xml:id="e">two</p></div>'
    '</body></text></TEI>'
)


def _root():
    # collect_ids=False: lxml would otherwise reject the duplicate xml:id "b",
    # which real-world documents do contain.
    return etree.fromstring(DOC.encode(), etree.XMLParser(collect_ids=False))


def _stock(root, expr: str) -> list:
    """What elementpath's own fn:id() returns for *expr*."""
    tree = get_node_tree(root.getroottree())
    context = XPathContext(root=tree, item=tree.elements[root])
    token = XPath31Parser(default_namespace=TEI).parse(expr)
    return [getattr(item, 'value', item) for item in token.select(context)]


@pytest.mark.parametrize('expr', [
    "id('b')",                      # duplicate value: the first in document order
    "id('e b')",                    # several values: results in document order
    "id(('e', 'a', 'd'))",
    "id('missing')",
    "id('c')",                      # a plain @id is not an ID
    "id('1invalid e')",             # invalid NCName tokens are skipped
    "id('b', //p[@xml:id = 'e'])",  # second argument picks the document
    "count(id('a b d e'))",
])
def test_indexed_id_returns_what_elementpath_returns(expr: str) -> None:
    root = _root()
    assert XPathEnvironment().select_all(root, expr) == _stock(root, expr)


def test_id_resolves_in_a_registered_document() -> None:
    lookup_uri = 'file:///project/lookup.xml'
    lookup = get_node_tree(
        etree.fromstring('<list><item xml:id="x">X</item></list>').getroottree(),
        None, lookup_uri,
    )
    env = XPathEnvironment(
        base_uri='file:///project/main.xml', documents={lookup_uri: lookup},
    )
    found = env.select_all(_root(), "id('x', doc('lookup.xml'))")
    assert [el.text for el in found] == ['X']


def test_index_is_built_once_per_document_and_run(monkeypatch) -> None:
    import opm.runtime.xpath_env as xpath_env

    built: list = []
    real = xpath_env.build_id_index
    monkeypatch.setattr(
        xpath_env, 'build_id_index', lambda root: built.append(root) or real(root),
    )
    root = _root()
    env = XPathEnvironment()
    for ref in ('a', 'b', 'e', 'd'):
        env.select_all(root, f"id('{ref}')")
    assert len(built) == 1

    # A new run builds its own index.
    XPathEnvironment().select_all(root, "id('a')")
    assert len(built) == 2


def test_root_of_agrees_with_elementpaths_get_root() -> None:
    from opm.runtime.xpath_parser import root_of

    main = get_node_tree(_root().getroottree(), None, 'file:///project/main.xml')
    register = get_node_tree(
        etree.fromstring('<list><item xml:id="x">X</item></list>').getroottree(),
        None, 'file:///project/register.xml',
    )
    stray = get_node_tree(etree.fromstring('<other/>').getroottree())
    context = XPathContext(
        root=main, item=main, documents={'file:///project/register.xml': register},
    )

    main_p = next(n for n in main.iter_lazy() if getattr(n, 'name', None) == f'{{{TEI}}}p')
    item = next(n for n in register.iter_lazy() if getattr(n, 'name', None) == 'item')
    attribute = item.attributes[0]
    text = item.children[0]
    for node in (main, main_p, register, item, attribute, text, stray, stray.children[0]):
        assert root_of(context, node) is context.get_root(node)


def test_stock_parser_keeps_elementpaths_id() -> None:
    assert OpmXPathParser.symbol_table['id'] is not XPath31Parser.symbol_table['id']
    assert issubclass(OpmXPathParser.symbol_table['id'], XPath31Parser.symbol_table['id'])
