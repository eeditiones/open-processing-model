# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Expand a prepared documentation tree so tagdocs renders it without lookups.

[`prepare_document_tree`][opm.document_site.prepare_document_tree] ends with
[`expand_document_tree`][opm.odd_expand.expand_document_tree]: everything a
page shows that depends on the schema's graph or on the document as a whole is
computed here, from a [`SpecIndex`][opm.spec_index.SpecIndex], and written into
the tree as plain TEI: contained-by, may-contain, members, used-by and the
attribute tree onto each spec, the A–Z lists into the catalog pages, and a
spec's notes, examples, processing models and content model into sections of
their own.

What a page can read off the document itself stays with ``tagdocs.odd``,
which resolves it while rendering: a division's outline label, the table of
contents, the chapter before and after, how many specs a catalog lists, the
chapters a spec cites, and every link from a name to the spec it names.

What depends on the language is left for the ODD to choose: every
``xml:lang`` variant of a note, an example or a description stays in the tree.
So is what depends on the output format: links are plain pointers to an id
(``#ref-p``, ``#COEDADD``), which the web and the PDF each resolve their own
way.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from lxml import etree

from opm.spec_index import (
    TEXT_IDENT,
    Spec,
    SpecIndex,
    SpecRef,
    _inside_egxml,
    localname,
    qn,
    unique_refs,
)

XML_ID = '{http://www.w3.org/XML/1998/namespace}id'

#: The kinds that get a reference page of their own.
_PAGE_KINDS = frozenset({'element', 'class', 'macro', 'datatype'})

#: The catalog pages' ``xml:id``, ``@subtype`` (the kind they list; none for
#: the attribute catalog) and heading, in the order they open ``text/back``.
#: The ids are TEI's own for the appendices they replace.
CATALOGS = (
    ('REF-ELEMENTS', 'elements', 'Elements'),
    ('REF-CLASSES-MODEL', 'model', 'Model classes'),
    ('REF-CLASSES-ATTS', 'atts', 'Attribute classes'),
    ('REF-MACROS', 'macro', 'Macros and datatypes'),
    ('REF-ATTS', None, 'Attributes'),
)

_OF_KIND = {
    'elements': lambda s: s.kind == 'element',
    'model': lambda s: s.is_model_class,
    'atts': lambda s: s.is_att_class,
    'macro': lambda s: s.kind in {'macro', 'datatype'},
}


# ── The relations, derived from the index ─────────────────────────────────


def _used_by(index: SpecIndex, spec: Spec) -> list[SpecRef]:
    used = (index.referrers('class', spec.ident)
            + index.referrers('macro', spec.ident)
            + index.referrers('data', spec.ident))
    if spec.is_model_class:
        # A model class is also "used" by the classes it is a member of: a
        # classRef to the parent matches this class's members too. The TEI
        # Stylesheets list those parents alongside the content-model
        # references, so model.persStateLike shows model.personPart.
        used += [index.ref(key, kind='class') for key in spec.model_classes]
    return unique_refs(used)


def _may_contain(index: SpecIndex, spec: Spec) -> list[SpecRef]:
    if spec.content is None:
        return []
    return unique_refs(_walk_content(index, spec.content, seen=set()))


def _walk_content(index: SpecIndex, el: etree._Element, seen: set[str]) -> list[SpecRef]:
    """Everything a content model admits: classes expanded to their elements,
    macros followed into their own content, text as character data."""
    out: list[SpecRef] = []
    tag = localname(el)
    key = el.get('key')
    if tag == 'elementRef' and key:
        # An element the schema leaves out is named, but admits nothing.
        if index.get(key) is not None:
            out.append(index.ref(key, kind='element'))
    elif tag == 'classRef' and key:
        out.extend(index.class_members_transitive(key))
    elif tag == 'macroRef' and key and key not in seen:
        seen.add(key)
        macro = index.get(key)
        if macro is not None and macro.content is not None:
            out.extend(_walk_content(index, macro.content, seen))
    elif tag == 'dataRef' and (key or el.get('name')):
        out.append(index.ref(key or el.get('name') or '', kind='datatype'))
    elif tag == 'textNode':
        out.append(SpecRef(ident=TEXT_IDENT, kind='text'))
    for child in el:
        out.extend(_walk_content(index, child, seen))
    return out


def _contained_by(index: SpecIndex, spec: Spec) -> list[SpecRef]:
    """Elements whose content admits *spec*: directly, through one of its model
    classes (or their ancestors), or through a macro that references either."""
    parents: list[SpecRef] = list(index.referrers('element', spec.ident))
    classes = index.expand_model_ancestors(spec.model_classes)
    for cls in classes:
        parents.extend(index.referrers('class', cls))
    chase = {spec.ident, *classes}
    for macro in index.macros():
        refs = set(index.content_refs(macro.ident))
        if any((kind, key) in refs for kind in ('class', 'element') for key in chase):
            parents.extend(index.referrers('macro', macro.ident))
    return [
        ref for ref in unique_refs(parents)
        if ref.kind == 'element' and ref.ident != spec.ident
    ]


# ── The relation lists ────────────────────────────────────────────────────


def _tei(tag: str, **attrs: str | None) -> etree._Element:
    el = etree.Element(qn(tag))
    for key, val in attrs.items():
        if val:
            el.set(key, val)
    return el


def _spec_pointer(parent: etree._Element, ref: SpecRef) -> None:
    """A ``gi`` naming an element, an ``ident`` naming anything else."""
    if ref.kind == 'element':
        etree.SubElement(parent, qn('gi')).text = ref.ident
    else:
        child = etree.SubElement(parent, qn('ident'))
        child.set('type', ref.kind)
        child.text = ref.ident


def _spec_item(ref: SpecRef, *, include_module: bool = True) -> etree._Element:
    item = _tei('item')
    if ref.is_text:
        item.set('type', 'charData')
        item.text = 'character data'
        return item
    _spec_pointer(item, ref)
    if include_module and ref.module and ref.kind != 'class':
        etree.SubElement(item, qn('seg'), type='module').text = ref.module
    return item


def _ref_list(refs: list[SpecRef], list_type: str) -> etree._Element:
    wrap = _tei('list', type=list_type)
    for ref in refs:
        wrap.append(_spec_item(ref))
    return wrap


def _grouped_list(refs: list[SpecRef], list_type: str) -> etree._Element:
    """*refs* by module, A–Z, with character data last; a list holding only
    ``seg[@type='empty']`` when there are none."""
    buckets: dict[str, list[SpecRef]] = {}
    for ref in refs:
        buckets.setdefault('Character data' if ref.is_text else (ref.module or ''), []).append(ref)
    wrap = _tei('list', type=list_type)
    if not buckets:
        etree.SubElement(wrap, qn('seg'), type='empty').text = 'empty'
        return wrap
    modules = sorted((key for key in buckets if key != 'Character data'), key=str.lower)
    if 'Character data' in buckets:
        modules.append('Character data')
    for module in modules:
        bucket = etree.SubElement(wrap, qn('item'))
        if module:
            bucket.set('n', module)
        inner = etree.SubElement(bucket, qn('list'), type='specItems')
        for ref in buckets[module]:
            inner.append(_spec_item(ref, include_module=False))
    return wrap


def _att_tree_item(
    index: SpecIndex, ident: str, local: set[str], suppressed: set[str],
) -> etree._Element:
    """One inherited class: its attributes, then the classes it inherits from."""
    item = _tei('item')
    etree.SubElement(item, qn('ident'), type='class').text = ident
    cls = index.get(ident)
    if cls is None:
        return item
    atts = [att for att in cls.local_atts if att.ident not in suppressed]
    if atts:
        wrap = etree.SubElement(item, qn('list'), type='atts')
        for att in atts:
            att_item = etree.SubElement(wrap, qn('item'), ident=att.ident, n=att.anchor)
            if att.ident in local:
                att_item.set('rend', 'overridden')
            att_item.text = att.ident
    if cls.att_classes:
        nested = etree.SubElement(item, qn('list'), type='attTree')
        for key in cls.att_classes:
            nested.append(_att_tree_item(index, key, local, suppressed))
    return item


def _att_tree(index: SpecIndex, spec: Spec) -> etree._Element:
    """The att classes *spec* inherits from, nested as they inherit. An
    attribute *spec* redefines carries ``rend="overridden"``; one it deletes is
    left out."""
    local = {att.ident for att in spec.local_atts}
    wrap = _tei('list', type='attTree')
    for key in spec.att_classes:
        wrap.append(_att_tree_item(index, key, local, spec.suppressed_atts))
    return wrap


#: Per page kind: the relation lists appended to the spec, in this order.
_SPEC_LISTS = {
    'element': (
        _att_tree,
        # Model classes only: the attribute classes are the attribute tree's,
        # as in the TEI Stylesheets (generateModelParents).
        lambda index, spec: _ref_list(
            [index.ref(key, kind='class') for key in spec.model_classes], 'memberOf'),
        lambda index, spec: _grouped_list(_may_contain(index, spec), 'mayContain'),
        lambda index, spec: _grouped_list(_contained_by(index, spec), 'containedBy'),
    ),
    'att_class': (
        _att_tree,
        lambda index, spec: _ref_list(_used_by(index, spec), 'usedBy'),
        lambda index, spec: _ref_list(index.members_of(spec.ident), 'members'),
    ),
    'class': (
        lambda index, spec: _ref_list(_used_by(index, spec), 'usedBy'),
        lambda index, spec: _ref_list(index.members_of(spec.ident), 'members'),
    ),
    'macro': (lambda index, spec: _ref_list(_used_by(index, spec), 'usedBy'),),
    'datatype': (lambda index, spec: _ref_list(_used_by(index, spec), 'usedBy'),),
}

_NOTES = ('ref-notes', 'Note', ('remarks',))
_EXAMPLES = ('ref-examples', 'Examples', ('exemplum',))
_CONTENT = ('ref-schema', 'Content model', ('content',))

#: Per page kind: the reference-page sections, as (anchor, heading, children).
_SECTIONS = {
    'element': (
        ('ref-models', 'Processing model', ('model', 'modelGrp', 'modelSequence')),
        _NOTES,
        _EXAMPLES,
        ('ref-constraints', 'Schematron', ('constraintSpec',)),
        _CONTENT,
    ),
    'att_class': (_NOTES, _EXAMPLES),
    'class': (_NOTES, _EXAMPLES),
    'macro': (_NOTES, _EXAMPLES, _CONTENT),
    'datatype': (_NOTES, _CONTENT),
}


def _page_kind(spec: Spec) -> str:
    if spec.kind == 'class':
        return 'att_class' if spec.is_att_class else 'class'
    return spec.kind


def _wrap_sections(spec: Spec) -> None:
    """Move *spec*'s notes, examples, models, Schematron and content model into
    ``div[@type='spec-section']``, one per section that has something to show.

    Only direct children move: the ``exemplum`` and ``constraintSpec`` of an
    ``attDef`` belong to the attribute. The language variants move together,
    and the ODD picks the one to show.
    """
    node = spec.node
    for anchor, heading, names in _SECTIONS[_page_kind(spec)]:
        children = [child for child in node if localname(child) in names]
        if not children:
            continue
        section = _tei('div', type='spec-section', n=anchor)
        etree.SubElement(section, qn('head')).text = heading
        for child in children:
            # A child's tail belongs to the spec's layout, not to the section.
            child.tail = None
            section.append(child)
        node.append(section)


def _inherited_att_def(
    index: SpecIndex, classes: list[str], ident: str, seen: set[str],
) -> etree._Element | None:
    """The ``attDef`` for *ident* that *classes* pass on: the first class,
    depth first in membership order, that declares it."""
    for key in classes:
        if key in seen:
            continue
        seen.add(key)
        cls = index.get(key)
        if cls is None:
            continue
        for att in cls.local_atts:
            if att.ident == ident:
                return att.node
        found = _inherited_att_def(index, cls.att_classes, ident, seen)
        if found is not None:
            return found
    return None


def _without_ids(el: etree._Element) -> etree._Element:
    """A copy of *el* that does not repeat the original's ids."""
    copy = deepcopy(el)
    for child in copy.iter():
        child.attrib.pop(XML_ID, None)
    return copy


def _complete_changed_atts(index: SpecIndex, spec: Spec) -> None:
    """Fill each ``attDef mode="change"`` of *spec* from the attribute it changes.

    A change restates only what differs, often just a ``valList`` or
    ``@usage``. What it leaves out (gloss, description, datatype, examples,
    notes) is taken from the class attribute it overrides, as the TEI
    Stylesheets show it, and ``@source`` on the ``attDef`` names that class.
    """
    for att_def in spec.node.iter(qn('attDef')):
        if att_def.get('mode') != 'change' or _inside_egxml(att_def):
            continue
        inherited = _inherited_att_def(index, spec.att_classes, att_def.get('ident') or '', set())
        if inherited is None:
            continue
        cls = inherited.xpath('ancestor::*[local-name()="classSpec"][1]/@ident')
        if cls:
            att_def.set('source', f'#ref-{cls[0]}')
        for name, value in inherited.attrib.items():
            if name not in att_def.attrib and name not in {'mode', XML_ID}:
                att_def.set(name, value)
        own = [c for c in att_def if isinstance(c.tag, str)]
        own_names = {localname(c) for c in own}
        merged: list[etree._Element] = []
        placed: set[str] = set()
        # The inherited order, each part the change restates in its place.
        for child in inherited:
            if not isinstance(child.tag, str):
                continue
            name = localname(child)
            if name not in own_names:
                merged.append(_without_ids(child))
            elif name not in placed:
                merged.extend(c for c in own if localname(c) == name)
                placed.add(name)
        merged.extend(c for c in own if localname(c) not in placed)
        for child in list(att_def):
            att_def.remove(child)
        att_def.text = None
        att_def.extend(merged)


# ── Catalogs and the home page ────────────────────────────────────────────


def _bucket_letter(ident: str) -> str:
    rest = ident
    for prefix in ('att.', 'model.', 'macro.', 'teidata.'):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    ch = rest[:1].upper() if rest else '#'
    return ch if ch.isalpha() else '#'


def _lettered(
    items: list, ident: Callable[[Any], str], list_type: str, items_type: str,
) -> tuple[etree._Element, dict[str, tuple[etree._Element, list]]]:
    """A list of one ``item[@n]`` per letter, and each letter's inner list."""
    buckets: dict[str, list] = {}
    for entry in items:
        buckets.setdefault(_bucket_letter(ident(entry)), []).append(entry)
    wrap = _tei('list', type=list_type)
    inner = {}
    for letter in sorted(buckets):
        group = etree.SubElement(wrap, qn('item'), n=letter)
        inner[letter] = (etree.SubElement(group, qn('list'), type=items_type), buckets[letter])
    return wrap, inner


def _spec_catalog(index: SpecIndex, kind: str) -> etree._Element:
    """The specs of *kind*, A–Z by letter; the ``att.``, ``model.``,
    ``macro.`` and ``teidata.`` prefixes do not count."""
    specs = [spec for spec in index.all() if _OF_KIND[kind](spec)]
    wrap, letters = _lettered(specs, lambda s: s.ident, 'catalog', 'catalogItems')
    for inner, group in letters.values():
        for spec in group:
            entry = etree.SubElement(inner, qn('item'), type=spec.kind, ident=spec.ident)
            if spec.module:
                entry.set('n', spec.module)
            entry.text = spec.ident
    return wrap


def _attribute_catalog(index: SpecIndex) -> etree._Element:
    """Each attribute and the classes and elements that define it, A–Z."""
    wrap, letters = _lettered(index.attributes(), lambda a: a[0], 'attCatalog', 'attCatalogItems')
    for inner, group in letters.values():
        for ident, owners in group:
            item = etree.SubElement(inner, qn('item'), ident=ident)
            for spec in owners:
                _spec_pointer(item, SpecRef(ident=spec.ident, kind=spec.kind))
    return wrap


def _fill_catalogs(root: etree._Element, index: SpecIndex) -> None:
    kinds = {xml_id: kind for xml_id, kind, _ in CATALOGS}
    for div in root.iter(qn('div')):
        xml_id = div.get(XML_ID)
        if xml_id in kinds:
            kind = kinds[xml_id]
            div.append(_spec_catalog(index, kind) if kind else _attribute_catalog(index))


def expand_document_tree(root: etree._Element, index: SpecIndex) -> None:
    """Write everything tagdocs needs into *root*, so it renders without lookups.

    *index* must be built from *root* before this runs: the relations are read
    from it, never from what this adds. Each spec that has a page (the copy
    stamped ``xml:id="ref-{ident}"``) gets its relation lists and its sections;
    the catalog pages get their A–Z lists; and every ``gi``/``ident`` naming a
    spec points at it.
    """
    for spec in index.all():
        if spec.kind not in _PAGE_KINDS or spec.node.get(XML_ID) != f'ref-{spec.ident}':
            continue
        _complete_changed_atts(index, spec)
        for build in _SPEC_LISTS[_page_kind(spec)]:
            spec.node.append(build(index, spec))
        _wrap_sections(spec)
    _fill_catalogs(root, index)


__all__ = ['CATALOGS', 'expand_document_tree']
