"""SpecIndex: ODD membership / content-model graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from opm.spec_index import SpecIndex, TEXT_IDENT, serialize_spec_xml
from opm.runtime.common_xpath_functions import normalize_egxml, serialize_egxml

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'


@pytest.fixture
def index() -> SpecIndex:
    return SpecIndex.from_path(MINI)


def test_indexes_elements_classes_macros(index: SpecIndex) -> None:
    assert {s.ident for s in index.elements()} == {'div', 'hi', 'p'}
    assert {s.ident for s in index.model_classes()} == {'model.pLike', 'model.phrase'}
    assert {s.ident for s in index.att_classes()} == {'att.global'}
    assert {s.ident for s in index.macros()} == {'macro.paraContent'}
    assert index.element('p').module == 'core'
    assert index.element('p').gloss is not None
    assert index.element('p').gloss.text == 'paragraph'
    assert [m.behaviour for m in index.element('p').models] == ['paragraph']
    assert index.element('p').models[0].desc is not None


def test_language_filter_picks_english_desc(index: SpecIndex) -> None:
    desc = index.element('p').desc
    assert desc is not None
    assert 'marks paragraphs' in ''.join(desc.itertext())
    fr = SpecIndex.from_path(MINI, lang='fr')
    assert 'marque les paragraphes' in ''.join(fr.element('p').desc.itertext())


def test_may_contain_expands_macro_and_class(index: SpecIndex) -> None:
    children = index.element('p').may_contain
    idents = {c.ident for c in children}
    assert 'hi' in idents
    assert TEXT_IDENT in idents
    assert 'div' not in idents


def test_contained_by_via_model_class(index: SpecIndex) -> None:
    parents = {c.ident for c in index.element('p').contained_by}
    assert parents == {'div'}
    hi_parents = {c.ident for c in index.element('hi').contained_by}
    assert 'p' in hi_parents


def test_members_and_used_by(index: SpecIndex) -> None:
    p_like = index.require('model.pLike')
    assert {m.ident for m in p_like.members} == {'p'}
    assert {u.ident for u in p_like.used_by} == {'div'}
    phrase = index.require('model.phrase')
    assert {m.ident for m in phrase.members} == {'hi'}
    assert {u.ident for u in phrase.used_by} == {'macro.paraContent'}


def test_attribute_inheritance_marks_local_overrides(index: SpecIndex) -> None:
    p = index.element('p')
    assert {a.ident for a in p.local_atts} == {'rend'}
    assert len(p.attribute_tree) == 1
    att_global = p.attribute_tree[0]
    assert att_global.ident == 'att.global'
    names = {a.ident: a for a in att_global.attributes}
    assert 'xml:id' in names
    assert 'n' in names
    assert names['xml:id'].overridden is False


def test_skips_elementspec_inside_egxml(index: SpecIndex) -> None:
    # The exemplum contains a <p> instance, not an elementSpec; the index still
    # has exactly one p.
    assert index.element('p').kind == 'element'


def test_grouped_by_module(index: SpecIndex) -> None:
    groups = dict(index.element('p').grouped(index.element('p').may_contain))
    assert 'core' in groups
    assert any(r.ident == 'hi' for r in groups['core'])
    assert 'Character data' in groups


def test_serialize_spec_xml_drops_tail() -> None:
    from lxml import etree

    parent = etree.fromstring(
        '<egXML xmlns="http://www.tei-c.org/ns/Examples">'
        'before <add place="above">of these facts</add> after'
        '</egXML>'
    )
    child = parent[0]
    assert child.tail and 'after' in child.tail
    xml = serialize_spec_xml(child)
    assert 'of these facts' in xml
    assert 'after' not in xml
    body = serialize_egxml(parent)
    assert body.startswith('before')
    assert 'of these facts' in body
    assert body.endswith('after')


def test_serialize_egxml_dedents_odd_indentation() -> None:
    from lxml import etree

    parent = etree.fromstring(
        '<egXML xmlns="http://www.tei-c.org/ns/Examples">\n'
        '        <pb n="474"/>\n'
        '        <div type="chapter" n="38">\n'
        '          <p>Reader, I married him. A quiet wedding we had: he and I, the parson and clerk, were alone\n'
        '          present. When we got back from church.</p>\n'
        '        </div>\n'
        '      </egXML>'
    )
    body = serialize_egxml(parent)
    assert body.startswith('<pb')
    assert '\n        <div' not in body
    assert 'type="chapter"' in body
    assert '\n          present.' not in body
    assert 'alone\npresent.' in body
    assert 'present. When we got back' in body
    # Nested structure keeps relative indent from pretty-print.
    assert '\n  <p>' in body or '\n    <p>' in body


def test_serialize_egxml_preserves_element_nesting() -> None:
    from lxml import etree

    parent = etree.fromstring(
        '<egXML xmlns="http://www.tei-c.org/ns/Examples">\n'
        '    <lg xml:id="RAM609">\n'
        '      <note place="margin">The\n'
        '      curse is finally expiated</note>\n'
        '      <l>And now this spell was snapt: once more</l>\n'
        '      <l>I viewed\n'
        '      the ocean green,</l>\n'
        '    </lg>\n'
        '  </egXML>'
    )
    body = serialize_egxml(parent)
    assert body.startswith('<lg')
    assert '\n  <note' in body
    assert '\n  <l>' in body
    assert 'The\ncurse is finally expiated' in body
    assert 'I viewed\nthe ocean green,' in body


def test_normalize_egxml_dedents_plain_eg() -> None:
    raw = (
        '\n            CHAPTER 38\n            \n'
        '            READER, I married him. A quiet wedding we had: he and I, the par-\n'
        '            son and clerk, were alone present.\n        '
    )
    body = normalize_egxml(raw)
    assert body.startswith('CHAPTER 38')
    assert '\n            READER' not in body
    assert 'par-\nson and clerk' in body
