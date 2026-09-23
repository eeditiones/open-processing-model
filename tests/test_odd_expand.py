"""Expanding the documentation tree: relations, catalogs, numbers and links."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from opm import odd_expand
from opm.document_site import prepare_document_tree
from opm.odd_schema import compile_schema

MINI = Path(__file__).resolve().parent / 'fixtures' / 'mini_schema.odd'
NS = {'t': 'http://www.tei-c.org/ns/1.0'}
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


@pytest.fixture(scope='module')
def tree() -> etree._Element:
    return prepare_document_tree(compile_schema(MINI))


def _xml(el: etree._Element) -> str:
    return etree.tostring(el, encoding='unicode')


def _one(tree: etree._Element, path: str) -> etree._Element:
    hits = tree.xpath(path, namespaces=NS)
    assert len(hits) == 1, path
    return hits[0]


def test_relations_as_tei(tree: etree._Element) -> None:
    p = _one(tree, "//t:elementSpec[@xml:id='ref-p']")
    assert 'div' in _xml(_one(p, "t:list[@type='containedBy']"))
    may = _one(p, "t:list[@type='mayContain']")
    assert 'hi' in _xml(may)
    # Module is the group heading; inner items must not repeat it.
    assert may.findall('t:item/t:list[@type="specItems"]/t:item/t:seg[@type="module"]', NS) == []
    member = _one(p, "t:list[@type='memberOf']")
    # Model classes only: the attribute classes are the attribute tree's.
    assert 'model.pLike' in _xml(member) and 'att.global' not in _xml(member)
    assert member.findall('t:item/t:seg[@type="module"]', NS) == []
    assert p.xpath("t:list[@type='attTree']/t:item", namespaces=NS)
    phrase = _one(tree, "//t:classSpec[@xml:id='ref-model.phrase']")
    assert 'hi' in _xml(_one(phrase, "t:list[@type='members']"))
    assert phrase.xpath("t:list[@type='usedBy']", namespaces=NS)


def test_an_empty_relation_says_so() -> None:
    """A grouped relation with nothing in it is a list holding the empty marker."""
    empty = odd_expand._grouped_list([], 'containedBy')
    assert [el.get('type') for el in empty] == ['empty']


def test_counts_and_catalogs(tree: etree._Element) -> None:
    catalog = _one(tree, "//t:div[@xml:id='REF-ELEMENTS']/t:list[@type='catalog']")
    idents = [item.get('ident') for item in catalog.iter('{%s}item' % NS['t']) if item.get('ident')]
    assert idents == ['div', 'hi', 'p']


def test_the_composition_uses_only_public_primitives() -> None:
    """The relations derive from the index's public lookups, never its
    internals — what a later XQuery port of them needs."""
    import re

    source = Path(odd_expand.__file__).read_text(encoding='utf-8')
    assert re.findall(r'\bindex\._[a-z]\w*', source) == []


def test_each_spec_page_carries_its_relations(tree: etree._Element) -> None:
    p = _one(tree, "//t:elementSpec[@xml:id='ref-p']")
    kinds = [el.get('type') for el in p.findall('t:list', NS)]
    assert kinds == ['attTree', 'memberOf', 'mayContain', 'containedBy']
    assert p.xpath("t:list[@type='containedBy']//t:gi[.='div']", namespaces=NS)


def test_notes_and_examples_move_into_sections(tree: etree._Element) -> None:
    p = _one(tree, "//t:elementSpec[@xml:id='ref-p']")
    sections = {div.get('n'): div for div in p.findall("t:div[@type='spec-section']", NS)}
    assert {'ref-notes', 'ref-examples', 'ref-schema'} <= set(sections)
    assert sections['ref-notes'].findall('t:remarks', NS)
    assert sections['ref-examples'].findall('t:exemplum', NS)
    assert p.findall('t:remarks', NS) == [] and p.findall('t:content', NS) == []
    # Only what has something to show gets a section.
    assert all(len(div) > 1 for div in sections.values())
    assert 'ref-constraints' not in sections


def test_catalog_pages_and_home_are_filled(tree: etree._Element) -> None:
    elements = _one(tree, "//t:div[@xml:id='REF-ELEMENTS']")
    assert elements.xpath("t:list[@type='catalog']//t:item[@ident='p']", namespaces=NS)
    atts = _one(tree, "//t:div[@xml:id='REF-ATTS']")
    assert atts.findall("t:list[@type='attCatalog']", NS)


def test_spec_names_are_left_as_they_stand(tree: etree._Element) -> None:
    """The tree keeps the prose as written: which names link is the ODD's to
    decide, from the page copies (``ref-{ident}``) it can look up."""
    assert tree.xpath("//t:elementSpec[@xml:id='ref-p']//t:gi[.='hi']", namespaces=NS)
    assert not tree.xpath('//t:gi[@target]', namespaces=NS)


def test_the_prepared_tree_has_unique_ids(tree: etree._Element) -> None:
    """Copies the expansion adds (a spec's desc in a specDesc) drop their ids."""
    ids = tree.xpath('//@xml:id')
    assert len(ids) == len(set(ids))
