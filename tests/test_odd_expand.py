"""Expanding the documentation tree: relations, catalogs, numbers and links."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from opm import odd_expand
from opm.document_site import prepare_document_tree
from opm.odd_schema import compile_schema
from opm.spec_index import SpecIndex

MINI = Path(__file__).resolve().parent / 'fixtures' / 'mini_schema.odd'
NS = {'t': 'http://www.tei-c.org/ns/1.0'}
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'


@pytest.fixture(scope='module')
def index() -> SpecIndex:
    return SpecIndex.from_path(MINI)


@pytest.fixture(scope='module')
def tree() -> etree._Element:
    return prepare_document_tree(compile_schema(MINI))


def _xml(el: etree._Element) -> str:
    return etree.tostring(el, encoding='unicode')


def _one(tree: etree._Element, path: str) -> etree._Element:
    hits = tree.xpath(path, namespaces=NS)
    assert len(hits) == 1, path
    return hits[0]


def test_relations_as_tei(index: SpecIndex) -> None:
    p = index.element('p')
    assert 'div' in _xml(odd_expand.contained_by(index, p))
    may = odd_expand.may_contain(index, p)
    assert 'hi' in _xml(may)
    # Module is the group heading; inner items must not repeat it.
    assert may.findall('t:item/t:list[@type="specItems"]/t:item/t:seg[@type="module"]', NS) == []
    member = odd_expand.member_of(index, p)
    assert 'model.pLike' in _xml(member) and 'att.global' in _xml(member)
    assert member.findall('t:item/t:seg[@type="module"]', NS) == []
    phrase = index.get('model.phrase')
    assert 'hi' in _xml(odd_expand.members(index, phrase))
    assert odd_expand.used_by(index, phrase).get('type') == 'usedBy'
    assert odd_expand.attribute_tree(index, p).findall('t:item', NS)


def test_an_empty_relation_says_so(index: SpecIndex) -> None:
    """A grouped relation with nothing in it is a list holding the empty marker."""
    macro = index.get('macro.paraContent')
    empty = odd_expand.contained_by(index, macro)
    assert [el.get('type') for el in empty] == ['empty']


def test_counts_and_catalogs(index: SpecIndex) -> None:
    assert odd_expand.spec_count(index, 'element') == 3
    catalog = odd_expand.spec_catalog(index, 'element')
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
    assert kinds == ['listRef', 'attTree', 'memberOf', 'mayContain', 'containedBy']
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
    home = _one(tree, "//t:div[@xml:id='index']")
    reference = home.find("t:list[@type='reference']", NS)
    rows = [(item.find('t:ref', NS).get('target'), item.find('t:num', NS).text) for item in reference]
    assert rows[0] == ('REF-ELEMENTS.html', '3')


def test_headings_open_with_their_number(tree: etree._Element) -> None:
    head = _one(tree, "//t:div[@xml:id='REF-ELEMENTS']/t:head")
    seg = head[0]
    assert (seg.get('type'), seg.get('n'), seg.text, seg.tail) == (
        'headingNumber', 'Appendix A', 'Appendix A ', 'Elements',
    )


def test_names_of_specs_link_to_their_page(tree: etree._Element) -> None:
    gis = tree.xpath("//t:elementSpec[@xml:id='ref-p']//t:gi[.='hi']", namespaces=NS)
    assert gis and all(gi.get('target') == 'ref-hi.html' for gi in gis)
    assert not tree.xpath("//t:gi[.='no-such-element'][@target]", namespaces=NS)
