"""SpecIndex: ODD membership / content-model graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from lxml import etree

from opm import odd_expand
from opm.spec_index import SpecIndex, TEXT_IDENT, qn, serialize_spec_xml
from opm.runtime.common_xpath_functions import normalize_egxml, serialize_egxml

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'
NS = {'t': 'http://www.tei-c.org/ns/1.0'}


@pytest.fixture
def index() -> SpecIndex:
    return SpecIndex.from_path(MINI)


def test_indexes_elements_classes_macros(index: SpecIndex) -> None:
    assert {s.ident for s in index.elements()} == {'div', 'hi', 'p'}
    assert {s.ident for s in index.all() if s.is_model_class} == {
        'model.divPart',
        'model.pLike',
        'model.phrase',
    }
    assert {s.ident for s in index.all() if s.is_att_class} == {'att.global'}
    assert {s.ident for s in index.macros()} == {'macro.paraContent'}
    assert index.element('p').module == 'core'
    # gloss/desc/remarks/exemplum stay on the node: the ODD reads them with
    # XPath, which is where the xml:lang preference lives.
    gloss = index.element('p').node.find(qn('gloss'))
    assert gloss is not None
    assert gloss.text == 'paragraph'


def test_module_idents_do_not_collide_with_element_idents(index: SpecIndex) -> None:
    """A ``moduleSpec`` never displaces a spec of the same name.

    TEI names the ``certainty`` module after the ``certainty`` element; the
    fixture mirrors that with ``hi``.
    """
    assert index.require('hi').kind == 'element'
    assert all(s.kind != 'module' for s in index.all())


def test_may_contain_expands_macro_and_class(index: SpecIndex) -> None:
    idents = {c.ident for c in odd_expand._may_contain(index, index.element('p'))}
    assert 'hi' in idents
    assert TEXT_IDENT in idents
    assert 'div' not in idents


def test_contained_by_via_model_class(index: SpecIndex) -> None:
    assert {c.ident for c in odd_expand._contained_by(index, index.element('p'))} == {'div'}
    assert 'p' in {c.ident for c in odd_expand._contained_by(index, index.element('hi'))}


def test_members_and_used_by(index: SpecIndex) -> None:
    p_like = index.require('model.pLike')
    assert {m.ident for m in index.members_of('model.pLike')} == {'p'}
    # ``div`` references the class in its content model; ``model.divPart`` uses it
    # by way of membership, as the TEI Stylesheets report it.
    assert {u.ident for u in odd_expand._used_by(index, p_like)} == {'div', 'model.divPart'}
    phrase = index.require('model.phrase')
    assert {m.ident for m in index.members_of('model.phrase')} == {'hi'}
    assert {u.ident for u in odd_expand._used_by(index, phrase)} == {'macro.paraContent'}


def test_attribute_inheritance_marks_local_overrides(index: SpecIndex) -> None:
    p = index.element('p')
    assert {a.ident for a in p.local_atts} == {'rend'}
    tree = odd_expand._att_tree(index, p)
    (att_global,) = tree.findall('t:item', NS)
    assert att_global.findtext('t:ident', namespaces=NS) == 'att.global'
    names = {a.get('ident'): a for a in att_global.findall("t:list[@type='atts']/t:item", NS)}
    assert {'xml:id', 'n'} <= set(names)
    assert names['xml:id'].get('rend') is None


def test_skips_elementspec_inside_egxml(index: SpecIndex) -> None:
    # The exemplum contains a <p> instance, not an elementSpec; the index still
    # has exactly one p.
    assert index.element('p').kind == 'element'


def test_grouped_by_module(index: SpecIndex) -> None:
    grouped = odd_expand._grouped_list(odd_expand._may_contain(index, index.element('p')), 'mayContain')
    groups = {item.get('n'): item for item in grouped.findall('t:item', NS)}
    assert 'hi' in etree.tostring(groups['core'], encoding='unicode')
    assert list(groups)[-1] == 'Character data'


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
