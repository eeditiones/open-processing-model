# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Expand a prepared documentation tree so tagdocs renders it without lookups.

[`prepare_document_tree`][opm.document_site.prepare_document_tree] ends with
[`expand_document_tree`][opm.odd_expand.expand_document_tree]: everything a
page shows that depends on the schema's graph or on the document as a whole is
computed here, from a [`SpecIndex`][opm.spec_index.SpecIndex], and written into
the tree as plain TEI. Contained-by, may-contain, members, used-by and the
attribute tree go onto each spec, the A–Z lists into the catalog pages, the
table of contents onto the home page, outline numbers into the headings, and
link targets onto the ``gi``/``ident`` that name a spec. ``tagdocs.odd`` then
renders each node from its own children, in document order. The guide's
[ODD documentation](../guide/odd-documentation.md#the-prepared-tree) page shows
what each addition looks like.

What depends on the language is left for the ODD to choose: every
``xml:lang`` variant of a note, an example or a description stays in the tree.
So is what depends on the output format: links are plain pointers to an id
(``#ref-p``, ``#COEDADD``), which the web and the PDF each resolve their own
way.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from lxml import etree

from opm.odd_schema import iter_guideline_chapters
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

_GUIDELINES_CHAPTER_RE = re.compile(r'^([A-Z]{2})')
_TEI_P5_DOC = 'https://www.tei-c.org/release/doc/tei-p5-doc'

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

#: The catalogs in the order the home page lists them.
_HOME_ORDER = ('REF-ELEMENTS', 'REF-CLASSES-MODEL', 'REF-CLASSES-ATTS', 'REF-ATTS', 'REF-MACROS')

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


def _list_ref(index: SpecIndex, spec: Spec) -> etree._Element:
    """The Guidelines sections *spec* cites: the section in this document when
    it carries it (``ref/@type='local'``), else the one on tei-c.org."""
    wrap = _tei('list', type='listRef')
    for target in spec.list_refs:
        code = target.lstrip('#')
        if not code:
            continue
        if index.chapter_page(code) is not None:
            attrs = {'type': 'local', 'target': f'#{code}'}
        elif match := _GUIDELINES_CHAPTER_RE.match(code):
            attrs = {'target': f'{_TEI_P5_DOC}/{index.lang}/html/{match.group(1)}.html#{code}'}
        else:
            continue
        etree.SubElement(etree.SubElement(wrap, qn('item')), qn('ref'), attrs).text = code
    return wrap


#: Per page kind: the relation lists appended to the spec, in this order.
_SPEC_LISTS = {
    'element': (
        _list_ref,
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


def _count(index: SpecIndex, kind: str | None) -> int:
    if kind is None:
        return len(index.attributes())
    return sum(1 for spec in index.all() if _OF_KIND[kind](spec))


def _fill_catalogs(root: etree._Element, index: SpecIndex) -> None:
    kinds = {xml_id: kind for xml_id, kind, _ in CATALOGS}
    for div in root.iter(qn('div')):
        xml_id = div.get(XML_ID)
        if xml_id in kinds:
            kind = kinds[xml_id]
            div.append(_spec_catalog(index, kind) if kind else _attribute_catalog(index))


def _fill_home(root: etree._Element, index: SpecIndex, toc: etree._Element | None) -> None:
    """The table of contents and the reference list, onto the home page."""
    home = next((div for div in root.iter(qn('div')) if div.get(XML_ID) == 'index'), None)
    if home is None:
        return
    if toc is not None:
        home.append(toc)
    catalogs = {xml_id: (kind, heading) for xml_id, kind, heading in CATALOGS}
    reference = _tei('list', type='reference')
    for xml_id in _HOME_ORDER:
        kind, heading = catalogs[xml_id]
        item = etree.SubElement(reference, qn('item'))
        ref = etree.SubElement(item, qn('ref'), target=f'#{xml_id}')
        ref.text = heading
        ref.tail = ' '
        etree.SubElement(item, qn('num')).text = str(_count(index, kind))
    home.append(reference)


# ── Outline numbers, contents, chapter navigation ─────────────────────────

_ROMAN = (
    (1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'), (100, 'c'), (90, 'xc'),
    (50, 'l'), (40, 'xl'), (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i'),
)


def _roman(n: int) -> str:
    out: list[str] = []
    for value, sign in _ROMAN:
        while n >= value:
            out.append(sign)
            n -= value
    return ''.join(out)


def _letter(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA (appendix labels)."""
    out = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord('A') + rem) + out
    return out


def _is_numbered_div(node: etree._Element) -> bool:
    """False for a div that only carries the title page: it stands in for
    ``front/titlePage``, which TEI's numbering skips."""
    return localname(node) == 'div' and not any(
        localname(child) == 'titlePage' for child in node
    )


def heading_label(div: etree._Element) -> str:
    """Guidelines-style outline label for a chapter ``div`` or one of its sections.

    Body chapters run ``1``, ``1.2``, ``1.2.1``; front matter takes lowercase
    roman numerals with a trailing dot (``iv.``, ``iv.1.``); back matter is
    lettered (``Appendix A``, ``Appendix A.1``), each level counting the div's
    position among its sibling divs. ``''`` outside ``front``/``body``/``back``.
    """
    if not _is_numbered_div(div):
        return ''
    chain: list[etree._Element] = [div]
    while (parent := chain[-1].getparent()) is not None and localname(parent) == 'div':
        chain.append(parent)
    top_parent = chain[-1].getparent()
    part = localname(top_parent) if top_parent is not None else ''
    if part not in ('front', 'body', 'back'):
        return ''
    indices = [
        1 + sum(1 for sib in el.itersiblings(preceding=True) if _is_numbered_div(sib))
        for el in reversed(chain)
    ]
    if part == 'body':
        head, suffix = str(indices[0]), ''
    elif part == 'front':
        head, suffix = _roman(indices[0]), '.'
    else:
        head, suffix = f'Appendix {_letter(indices[0])}', ''
    return '.'.join([head, *(str(i) for i in indices[1:])]) + suffix


def _label_seg(text: str, *, label: str | None = None) -> etree._Element:
    seg = _tei('seg', type='headingNumber', n=label)
    # The space is part of the text, as in the published Guidelines: it keeps
    # "1.1 Modules" readable wherever the heading is read as plain text — the
    # on-this-page rail, the search index, a copied line.
    seg.text = f'{text} '
    return seg


def _add_heading_numbers(root: etree._Element) -> None:
    """Open each numbered heading with its outline label.

    A chapter's label opens its page on a line of its own, so a bare index is
    spelled out ("Chapter 3", "Front matter iv"); an appendix ("Appendix F")
    and a section ("1.2") are left as they are. ``@n`` keeps the bare label.
    """
    for div in list(root.iter(qn('div'))):
        label = heading_label(div)
        head = next((child for child in div if localname(child) == 'head'), None)
        if not label or head is None:
            continue
        text = label
        if label.isdigit():
            text = f'Chapter {label}'
        elif label.endswith('.') and label[:-1].isalpha():
            text = f'Front matter {label[:-1]}'
        mark = _label_seg(text, label=label)
        mark.tail = head.text
        head.text = None
        head.insert(0, mark)


def _heading_text(div: etree._Element) -> str:
    """The text of *div*'s head, without its outline number."""
    for child in div:
        if localname(child) == 'head':
            parts = [child.text or '']
            for node in child:
                if not (localname(node) == 'seg' and node.get('type') == 'headingNumber'):
                    parts.extend(node.itertext())
                parts.append(node.tail or '')
            return ' '.join(part for part in parts if part).strip()
    return ''


def _toc_item(div: etree._Element, *, sections: bool) -> etree._Element:
    """A contents entry: the bare outline label, as TEI's own contents have
    it, a link, and with *sections* the headed sections one level down."""
    xml_id = div.get(XML_ID) or ''
    item = _tei('item')
    label = heading_label(div)
    if label:
        item.append(_label_seg(label))
    ref = etree.SubElement(item, qn('ref'), target=f'#{xml_id}')
    ref.text = _heading_text(div) or xml_id
    nested = [c for c in div if localname(c) == 'div' and _heading_text(c)] if sections else []
    if nested:
        inner = etree.SubElement(item, qn('list'), type='toc')
        for child in nested:
            inner.append(_toc_item(child, sections=False))
    return item


def _guidelines_toc(root: etree._Element) -> etree._Element | None:
    """The chapters, as ``list[@type='toc']`` per front / body / back; ``None``
    when there are none."""
    groups: dict[str, list[etree._Element]] = {'front': [], 'body': [], 'back': []}
    for div in iter_guideline_chapters(root):
        parent = div.getparent()
        part = localname(parent) if parent is not None else 'body'
        groups[part if part in groups else 'body'].append(div)
    wrap = _tei('div', type='guidelines-toc')
    for part, chapters in groups.items():
        if chapters:
            inner = etree.SubElement(wrap, qn('list'), type='toc', n=part)
            for div in chapters:
                inner.append(_toc_item(div, sections=True))
    return wrap if len(wrap) else None


def _link_chapters(root: etree._Element) -> None:
    """Open each chapter with ``list[@type='chapterNav']``: the previous and
    next chapter, ``ref/@n`` their outline label."""
    chapters = [
        div for div in root.iter(qn('div'))
        if (parent := div.getparent()) is not None
        and localname(parent) in {'front', 'body', 'back'}
    ]
    for position, div in enumerate(chapters):
        nav = _tei('list', type='chapterNav')
        for n, other in (
            ('prev', chapters[position - 1] if position > 0 else None),
            ('next', chapters[position + 1] if position + 1 < len(chapters) else None),
        ):
            if other is None:
                continue
            item = etree.SubElement(nav, qn('item'), n=n)
            ref = etree.SubElement(item, qn('ref'))
            ref.set('target', f'#{other.get(XML_ID)}' if other.get(XML_ID) else '')
            label = heading_label(other)
            if label:
                ref.set('n', label)
            ref.text = ' '.join(_heading_text(other).split())
        div.insert(0, nav)


# ── Links ─────────────────────────────────────────────────────────────────


def _pageless(el: etree._Element) -> bool:
    """True inside markup the ODD serializes as code rather than renders."""
    return _inside_egxml(el) or any(
        localname(anc) in {'content', 'constraintSpec'} for anc in el.iterancestors()
    )


def _link_spec_names(root: etree._Element, index: SpecIndex) -> None:
    """``@target="#ref-{ident}"`` on every ``gi``/``ident`` that names a spec
    with a page, and on the ``dataRef`` of an attribute's datatype."""
    def page(ident: str) -> str | None:
        spec = index.get(ident)
        return f'#ref-{spec.ident}' if spec is not None and spec.kind in _PAGE_KINDS else None

    for el in root.iter(qn('gi'), qn('ident')):
        if el.get('target') or _pageless(el):
            continue
        if localname(el) == 'ident' and el.get('type') not in {'class', 'macro', 'datatype', 'schema'}:
            continue
        href = page(' '.join(''.join(el.itertext()).split()))
        if href:
            el.set('target', href)
    for att_def in root.iter(qn('attDef')):
        for data_ref in att_def.iter(qn('dataRef')):
            href = page(data_ref.get('key') or '')
            if href and not data_ref.get('target'):
                data_ref.set('target', href)


def _describe_spec_refs(root: etree._Element, index: SpecIndex) -> None:
    """Copy into each ``specDesc`` the gloss and description of the spec it
    names; ``@rend`` is the spec's element name, a CSS class for the ODD."""
    for spec_desc in root.iter(qn('specDesc')):
        spec = index.get(spec_desc.get('key') or '')
        if spec is None:
            continue
        spec_desc.set('rend', localname(spec.node))
        for child in spec.node:
            if localname(child) in {'gloss', 'desc'}:
                copy = _without_ids(child)
                copy.tail = None
                spec_desc.append(copy)


def expand_document_tree(root: etree._Element, index: SpecIndex) -> None:
    """Write everything tagdocs needs into *root*, so it renders without lookups.

    *index* must be built from *root* before this runs: the relations are read
    from it, never from what this adds. Each spec that has a page (the copy
    stamped ``xml:id="ref-{ident}"``) gets its relation lists and its sections;
    the catalog pages get their A–Z lists and the home page its table of
    contents and reference list; each chapter learns the previous and next
    one; numbered headings get their label; and every
    ``gi``/``ident`` naming a spec points at it.
    """
    # The contents read the headings as the document has them, before anything
    # below adds to the chapters.
    toc = _guidelines_toc(root)
    for spec in index.all():
        if spec.kind not in _PAGE_KINDS or spec.node.get(XML_ID) != f'ref-{spec.ident}':
            continue
        _complete_changed_atts(index, spec)
        for build in _SPEC_LISTS[_page_kind(spec)]:
            spec.node.append(build(index, spec))
        _wrap_sections(spec)
    _fill_catalogs(root, index)
    _fill_home(root, index, toc)
    _link_chapters(root)
    _add_heading_numbers(root)
    _describe_spec_refs(root, index)
    _link_spec_names(root, index)


__all__ = ['CATALOGS', 'expand_document_tree']
