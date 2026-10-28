"""RELAX NG from a compiled ODD, as the TEI Stylesheets' odd2relax writes it."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from opm.cli import main
from opm.odd_relax import A_NS, RNG_NS, odd_to_rng

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
MINI = FIXTURES / 'mini_schema.odd'
TEI_NS = 'http://www.tei-c.org/ns/1.0'

# Shared by most cases: a root, an attribute class and a model class with one member.
BASE = """
  <classSpec ident="att.global" type="atts" module="tei">
    <attList>
      <attDef ident="xml:id"><datatype><dataRef name="ID"/></datatype></attDef>
      <attDef ident="rend">
        <datatype><dataRef key="teidata.word"/></datatype>
        <valList type="closed">
          <valItem ident="bold"><gloss>bold face</gloss></valItem>
          <valItem ident="italic"/>
        </valList>
      </attDef>
    </attList>
  </classSpec>
  <classSpec ident="model.phrase" type="model" module="tei"/>
  <dataSpec ident="teidata.word" module="tei">
    <content><dataRef name="token" restriction="[^\\s]+"/></content>
  </dataSpec>
  <elementSpec ident="hi" module="core">
    <gloss>highlighted</gloss>
    <desc>marks a <gi>p</gi> part with <att>rend</att> in <code>x</code>.</desc>
    <classes><memberOf key="att.global"/><memberOf key="model.phrase"/></classes>
    <content><alternate minOccurs="0" maxOccurs="unbounded"><textNode/><classRef key="model.phrase"/></alternate></content>
  </elementSpec>
"""


def _grammar(specs: str, schema_attrs: str = 'ident="t" start="doc"') -> etree._Element:
    odd = f"""<TEI xmlns="{TEI_NS}" xmlns:rng="{RNG_NS}"><text><body>
      <schemaSpec {schema_attrs}>{specs}</schemaSpec></body></text></TEI>"""
    return odd_to_rng(etree.fromstring(odd))


def _define(grammar: etree._Element, name: str) -> etree._Element:
    found = grammar.find(f'{{{RNG_NS}}}define[@name="{name}"]')
    assert found is not None, f'no define {name}'
    return found


def _valid(grammar: etree._Element, xml: str) -> bool:
    return etree.RelaxNG(grammar).validate(etree.fromstring(xml))


def _doc(body: str) -> str:
    return f'<doc xmlns="{TEI_NS}">{body}</doc>'


DOC = """
  <elementSpec ident="doc" module="core">
    <classes><memberOf key="att.global"/></classes>
    <content><sequence><elementRef key="head" minOccurs="0"/><classRef key="model.phrase" minOccurs="0" maxOccurs="unbounded"/></sequence></content>
  </elementSpec>
"""


def test_elements_classes_and_start() -> None:
    g = _grammar(BASE + DOC)
    assert [r.get('name') for r in g.find(f'{{{RNG_NS}}}start').iter(f'{{{RNG_NS}}}ref')] == ['doc']
    assert _valid(g, _doc('<hi rend="bold">a <hi>b</hi></hi>'))
    assert not _valid(g, _doc('<hi rend="huge"/>'))
    assert not _valid(g, '<hi xmlns="http://www.tei-c.org/ns/1.0"/>')
    # The model class is a choice of its members; head is not in the schema and drops out.
    assert [r.get('name') for r in _define(g, 'model.phrase').iter(f'{{{RNG_NS}}}ref')] == ['hi']
    assert not g.xpath('//rng:ref[@name="head"]', namespaces={'rng': RNG_NS})


def test_attribute_classes_are_spelled_out_per_attribute() -> None:
    g = _grammar(BASE + DOC)
    assert [r.get('name') for r in _define(g, 'att.global.attributes')] == [
        'att.global.attribute.xmlid', 'att.global.attribute.rend',
    ]
    rend = _define(g, 'att.global.attribute.rend').find(f'{{{RNG_NS}}}optional/{{{RNG_NS}}}attribute')
    assert rend.get('name') == 'rend'
    assert [v.text for v in rend.iter(f'{{{RNG_NS}}}value')] == ['bold', 'italic']
    # Each value is documented right after it.
    assert rend.find(f'.//{{{RNG_NS}}}value').getnext().text == '(bold face)'


def test_an_element_overriding_a_class_attribute_spells_the_class_out() -> None:
    override = DOC.replace('</elementSpec>', """
      <attList>
        <attDef ident="rend" mode="change" usage="req">
          <valList type="closed" mode="change"><valItem ident="italic" mode="delete"/><valItem ident="caps"/></valList>
        </attDef>
        <attDef ident="xml:id" mode="delete"/>
      </attList></elementSpec>""")
    g = _grammar(BASE + override)
    element = _define(g, 'doc').find(f'{{{RNG_NS}}}element')
    assert not element.xpath('rng:ref[@name="att.global.attributes"]', namespaces={'rng': RNG_NS})
    rend = element.find(f'{{{RNG_NS}}}attribute')
    assert rend.get('name') == 'rend' and rend.getparent() is element  # required now
    assert [v.text for v in rend.iter(f'{{{RNG_NS}}}value')] == ['bold', 'caps']
    assert _valid(g, _doc('').replace('<doc ', '<doc rend="caps" '))
    assert not _valid(g, _doc('').replace('<doc ', '<doc rend="italic" '))
    assert not _valid(g, _doc(''))
    assert not _valid(g, _doc('').replace('<doc ', '<doc xml:id="a" rend="bold" '))
    # Elements that do not override still point at the class.
    assert _define(g, 'hi').xpath('rng:element/rng:ref[@name="att.global.attributes"]', namespaces={'rng': RNG_NS})


def test_occurrences_sequences_and_interleave() -> None:
    specs = BASE + """
      <elementSpec ident="doc" module="core">
        <content><sequence preserveOrder="false"><elementRef key="hi" minOccurs="2" maxOccurs="3"/><elementRef key="item"/></sequence></content>
      </elementSpec>
      <elementSpec ident="item" module="core"><content><empty/></content></elementSpec>
    """
    g = _grammar(specs)
    assert g.xpath('//rng:define[@name="doc"]//rng:interleave', namespaces={'rng': RNG_NS})
    assert _valid(g, _doc('<item/><hi/><hi/>'))
    assert _valid(g, _doc('<hi/><hi/><hi/><item/>'))
    assert not _valid(g, _doc('<hi/><item/>'))
    assert not _valid(g, _doc('<hi/><hi/><hi/><hi/><item/>'))
    assert not _valid(g, _doc('<hi/><hi/><item>x</item>'))


def test_class_ref_expanded_to_a_sequence_of_members() -> None:
    specs = BASE + """
      <elementSpec ident="b" module="core"><classes><memberOf key="model.phrase"/></classes><content><empty/></content></elementSpec>
      <elementSpec ident="doc" module="core"><content><classRef key="model.phrase" expand="sequence"/></content></elementSpec>
    """
    g = _grammar(specs)
    assert _valid(g, _doc('<b/><hi/>'))
    assert not _valid(g, _doc('<hi/>'))


def test_an_empty_model_class_allows_nothing() -> None:
    specs = BASE.replace('<memberOf key="model.phrase"/>', '') + """
      <elementSpec ident="doc" module="core"><content><classRef key="model.phrase" minOccurs="0"/></content></elementSpec>
    """
    g = _grammar(specs)
    assert _define(g, 'model.phrase')[0].tag == f'{{{RNG_NS}}}notAllowed'
    assert _valid(g, _doc(''))


def test_datatypes_are_written_in_place() -> None:
    specs = BASE + """
      <elementSpec ident="doc" module="core">
        <content><empty/></content>
        <attList>
          <attDef ident="n" usage="req"><datatype><dataRef key="teidata.word"/></datatype></attDef>
          <attDef ident="targets"><datatype minOccurs="1" maxOccurs="unbounded"><dataRef name="anyURI"/></datatype></attDef>
          <attDef ident="type"><datatype><dataRef key="teidata.word"/></datatype>
            <valList type="semi"><valItem ident="x"/></valList></attDef>
        </attList>
      </elementSpec>
    """
    g = _grammar(specs)
    n = g.xpath('//rng:attribute[@name="n"]', namespaces={'rng': RNG_NS})[0]
    assert n.find(f'{{{RNG_NS}}}data').get('type') == 'token'
    assert n.find(f'{{{RNG_NS}}}data/{{{RNG_NS}}}param').text == '[^\\s]+'
    assert not g.xpath('//rng:define[@name="teidata.word"]', namespaces={'rng': RNG_NS})
    targets = g.xpath('//rng:attribute[@name="targets"]', namespaces={'rng': RNG_NS})[0]
    assert targets.find(f'{{{RNG_NS}}}list/{{{RNG_NS}}}oneOrMore/{{{RNG_NS}}}data') is not None
    type_doc = g.xpath('//rng:attribute[@name="type"]/a:documentation', namespaces={'rng': RNG_NS, 'a': A_NS})
    assert type_doc[0].text.endswith('Suggested values include: 1] x')
    assert _valid(g, _doc('').replace('<doc ', '<doc n="a" targets="#a #b" type="other" '))
    assert not _valid(g, _doc('').replace('<doc ', '<doc n="a b" '))
    assert not _valid(g, _doc(''))


def test_any_element_and_embedded_rng() -> None:
    specs = BASE + """
      <elementSpec ident="doc" module="core" xmlns:mei="http://www.music-encoding.org/ns/mei">
        <content><sequence><anyElement minOccurs="0"/><rng:element name="mei:mdiv"><rng:empty/></rng:element></sequence></content>
      </elementSpec>
    """
    g = _grammar(specs)
    any_define = g.find(f'{{{RNG_NS}}}define[@name="anyElement_doc_1"]')
    assert any_define is not None
    assert [e.get('ns') for e in any_define.iter(f'{{{RNG_NS}}}nsName')] == [TEI_NS]
    mdiv = g.xpath('//rng:element[@name="mdiv"]', namespaces={'rng': RNG_NS})[0]
    assert mdiv.get('ns') == 'http://www.music-encoding.org/ns/mei'
    mei = 'xmlns:mei="http://www.music-encoding.org/ns/mei"'
    assert _valid(g, _doc(f'<x xmlns="urn:x" a="1">y</x><mei:mdiv {mei}/>'))
    assert not _valid(g, _doc(f'<hi/><mei:mdiv {mei}/>'))


def test_schema_prefix_names_the_patterns_not_the_elements() -> None:
    g = _grammar(BASE + DOC, 'ident="t" start="doc" prefix="tei_"')
    assert _define(g, 'tei_doc').find(f'{{{RNG_NS}}}element').get('name') == 'doc'
    assert _define(g, 'tei_att.global.attributes') is not None
    assert [r.get('name') for r in g.find(f'{{{RNG_NS}}}start').iter(f'{{{RNG_NS}}}ref')] == ['tei_doc']
    assert _valid(g, _doc('<hi/>'))


def test_documentation_is_gloss_and_description() -> None:
    g = _grammar(BASE + DOC)
    doc = _define(g, 'hi').find(f'{{{RNG_NS}}}element/{{{A_NS}}}documentation')
    assert doc.text == '(highlighted) marks a <p> part with @rend in `x`.'


def test_unreferenced_specs_are_dropped() -> None:
    specs = BASE + DOC + """
      <elementSpec ident="orphan" module="core"><content><empty/></content></elementSpec>
      <macroSpec ident="macro.unused" module="core"><content><textNode/></content></macroSpec>
    """
    g = _grammar(specs)
    names = {d.get('name') for d in g.iter(f'{{{RNG_NS}}}define')}
    assert 'orphan' not in names and 'macro.unused' not in names
    assert {'doc', 'hi', 'model.phrase'} <= names


def test_odd_compile_writes_rng(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(['odd', 'compile', str(MINI), '--format', 'rng']) == 0
    grammar = etree.parse(str(tmp_path / 'mini_schema.rng')).getroot()
    schema = etree.RelaxNG(grammar)
    assert schema.validate(etree.fromstring(f'<div xmlns="{TEI_NS}"><p>text</p></div>'))
    assert not schema.validate(etree.fromstring(f'<p xmlns="{TEI_NS}"/>'))
    assert main(['odd', 'compile', str(MINI), '--format', 'rng']) != 0
    assert main(['odd', 'compile', str(MINI), '--format', 'dtd']) != 0
