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
renders each node from its own children, in document order.

What depends on the language is left for the ODD to choose: every
``xml:lang`` variant of a note, an example or a description stays in the tree.
"""

from __future__ import annotations

import re
from copy import deepcopy

from lxml import etree

from opm import spec_index as _si
from opm.odd_schema import iter_guideline_chapters
from opm.spec_index import (
    TEXT_IDENT,
    AttClassView,
    AttDefView,
    Spec,
    SpecIndex,
    SpecRef,
    _inside_egxml,
    localname,
    qn,
)

XML_ID = '{http://www.w3.org/XML/1998/namespace}id'

_GUIDELINES_CHAPTER_RE = re.compile(r'^([A-Z]{2})')
_TEI_P5_DOC = 'https://www.tei-c.org/release/doc/tei-p5-doc'

_KIND_PREDICATES = {
    'element': lambda s: s.kind == 'element',
    'elements': lambda s: s.kind == 'element',
    'model': lambda s: s.is_model_class,
    'model_classes': lambda s: s.is_model_class,
    'atts': lambda s: s.is_att_class,
    'att_classes': lambda s: s.is_att_class,
    'macro': lambda s: s.kind in {'macro', 'datatype'},
    'macros': lambda s: s.kind in {'macro', 'datatype'},
}

#: The kinds that get a reference page of their own.
PAGE_KINDS = frozenset({'element', 'class', 'macro', 'datatype'})

#: The catalog pages' ``xml:id``, ``@subtype`` and heading, in the order they
#: open ``text/back``. The ids are TEI's own for the appendices they replace.
CATALOGS = (
    ('REF-ELEMENTS', 'elements', 'Elements'),
    ('REF-CLASSES-MODEL', 'model', 'Model classes'),
    ('REF-CLASSES-ATTS', 'atts', 'Attribute classes'),
    ('REF-MACROS', 'macro', 'Macros and datatypes'),
    ('REF-ATTS', None, 'Attributes'),
)

#: The home page's reference list: catalog page, label, what it counts.
_REFERENCE = (
    ('REF-ELEMENTS', 'Elements', 'element'),
    ('REF-CLASSES-MODEL', 'Model classes', 'model'),
    ('REF-CLASSES-ATTS', 'Attribute classes', 'atts'),
    ('REF-ATTS', 'Attributes', 'attributes'),
    ('REF-MACROS', 'Macros and datatypes', 'macro'),
)


# ── The relations, derived from the index ─────────────────────────────────


def relation(index: SpecIndex, spec: Spec, name: str) -> list:
    """*spec*'s relation *name*, derived once per index and cached."""
    key = (name, spec.ident)
    if key not in index.memo:
        index.memo[key] = _RELATIONS[name](index, spec)
    return index.memo[key]


def _members(index: SpecIndex, spec: Spec) -> list[SpecRef]:
    return index.members_of(spec.ident)


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
    return _si.unique_refs(used)


def _may_contain(index: SpecIndex, spec: Spec) -> list[SpecRef]:
    if spec.kind not in {'element', 'macro', 'datatype'} or spec.content is None:
        return []
    return _si.unique_refs(_walk_content(index, spec.content, seen=set()))


def _walk_content(index: SpecIndex, el: etree._Element, seen: set[str]) -> list[SpecRef]:
    """Everything a content model admits: classes expanded to their elements,
    macros followed into their own content, text as character data."""
    out: list[SpecRef] = []
    tag = localname(el)
    key = el.get('key')
    if tag == 'elementRef' and key:
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
    if spec.kind != 'element':
        return []
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
        ref for ref in _si.unique_refs(parents)
        if ref.kind == 'element' and ref.ident != spec.ident
    ]


def _attribute_tree_of(index: SpecIndex, spec: Spec) -> list[AttClassView]:
    """The att classes *spec* inherits from, nested as they inherit, with the
    attributes *spec* redefines marked and those it deletes left out."""
    if spec.kind != 'element' and not spec.is_att_class:
        return []
    local = {att.ident for att in spec.local_atts}
    views = [
        _att_class_view(index, key, local, spec.suppressed_atts)
        for key in spec.att_classes
    ]
    return [view for view in views if view is not None]


def _att_class_view(
    index: SpecIndex, ident: str, local: set[str], suppressed: set[str],
) -> AttClassView | None:
    cls = index.get(ident)
    if cls is None:
        return AttClassView(ident=ident)
    atts = [
        AttDefView(
            ident=att.ident,
            usage=att.usage,
            datatype=att.datatype,
            desc=att.desc,
            gloss=att.gloss,
            exemplum=att.exemplum,
            overridden=att.ident in local,
            node=att.node,
        )
        for att in cls.local_atts
        if att.ident not in suppressed
    ]
    nested = [
        view
        for key in cls.att_classes
        if (view := _att_class_view(index, key, local, suppressed)) is not None
    ]
    return AttClassView(ident=ident, attributes=atts, nested=nested)


def grouped(refs: list[SpecRef]) -> list[tuple[str, list[SpecRef]]]:
    """*refs* by module, A–Z, with character data last."""
    buckets: dict[str, list[SpecRef]] = {}
    for ref in refs:
        buckets.setdefault('Character data' if ref.is_text else (ref.module or ''), []).append(ref)
    named = sorted((key for key in buckets if key != 'Character data'), key=str.lower)
    if 'Character data' in buckets:
        named.append('Character data')
    return [(key, buckets[key]) for key in named]


_RELATIONS = {
    'members': _members,
    'used_by': _used_by,
    'may_contain': _may_contain,
    'contained_by': _contained_by,
    'attribute_tree': _attribute_tree_of,
}


# ── TEI fragments ─────────────────────────────────────────────────────────


def _tei(tag: str, **attrs: str | None) -> etree._Element:
    el = etree.Element(qn(tag))
    for key, val in attrs.items():
        if val:
            el.set(key, val)
    return el


def _spec_pointer(parent: etree._Element, ref: SpecRef) -> etree._Element:
    if ref.is_text or ref.ident == TEXT_IDENT:
        seg = etree.SubElement(parent, qn('seg'))
        seg.set('type', 'charData')
        seg.text = 'character data'
        return seg
    child_tag = 'gi' if ref.kind == 'element' else 'ident'
    child = etree.SubElement(parent, qn(child_tag))
    if child_tag == 'ident' and ref.kind:
        child.set('type', 'class' if ref.kind == 'class' else ref.kind)
    child.text = ref.ident
    return child


def _spec_item(ref: SpecRef, *, include_module: bool = True) -> etree._Element:
    item = _tei('item')
    if ref.is_text or ref.ident == TEXT_IDENT:
        item.set('type', 'charData')
        item.text = 'character data'
        return item
    _spec_pointer(item, ref)
    if include_module and ref.module and ref.kind != 'class':
        mod = etree.SubElement(item, qn('seg'))
        mod.set('type', 'module')
        mod.text = ref.module
    return item


def _ref_list(refs: list[SpecRef], *, list_type: str) -> etree._Element:
    wrap = _tei('list', type=list_type)
    for ref in refs:
        wrap.append(_spec_item(ref))
    return wrap


def _grouped_list(refs: list[SpecRef], *, list_type: str) -> etree._Element:
    groups = grouped(refs)
    wrap = _tei('list', type=list_type)
    if not groups:
        empty = etree.SubElement(wrap, qn('seg'))
        empty.set('type', 'empty')
        empty.text = 'empty'
        return wrap
    for module, group in groups:
        bucket = etree.SubElement(wrap, qn('item'))
        if module:
            bucket.set('n', module)
        inner = etree.SubElement(bucket, qn('list'))
        inner.set('type', 'specItems')
        for ref in group:
            inner.append(_spec_item(ref, include_module=False))
    return wrap


def contained_by(index: SpecIndex, spec: Spec) -> etree._Element:
    """The elements that may contain *spec*, grouped by module.

    For ``abbr``:

    ```xml
    <list type="containedBy">
      <item n="analysis">
        <list type="specItems">
          <item><gi>cl</gi></item>
          <item><gi>pc</gi></item>
          <!-- … -->
        </list>
      </item>
      <item n="core">
        <list type="specItems">
          <item><gi>add</gi></item>
          <!-- … -->
        </list>
      </item>
    </list>
    ```

    One item per module, A–Z, with character data last; a list holding only
    ``seg[@type='empty']`` when there is nothing to list.
    """
    return _grouped_list(relation(index, spec, 'contained_by'), list_type='containedBy')


def may_contain(index: SpecIndex, spec: Spec) -> etree._Element:
    """What *spec* may contain, grouped by module.

    For ``abbr``:

    ```xml
    <list type="mayContain">
      <item n="analysis">
        <list type="specItems">
          <item><gi>c</gi></item>
          <!-- … -->
        </list>
      </item>
      <!-- … -->
      <item n="Character data">
        <list type="specItems">
          <item type="charData">character data</item>
        </list>
      </item>
    </list>
    ```

    Empty as in [`contained_by`][opm.odd_expand.contained_by].
    """
    return _grouped_list(relation(index, spec, 'may_contain'), list_type='mayContain')


def members(index: SpecIndex, spec: Spec) -> etree._Element:
    """The specs that claim membership in *spec*.

    For ``model.pPart.edit``:

    ```xml
    <list type="members">
      <item><ident type="class">model.pPart.editorial</ident></item>
      <item><ident type="class">model.pPart.transcriptional</ident></item>
    </list>
    ```

    An element member is a ``gi`` followed by ``seg[@type='module']``, as in
    [`used_by`][opm.odd_expand.used_by].
    """
    return _ref_list(relation(index, spec, 'members'), list_type='members')


def used_by(index: SpecIndex, spec: Spec) -> etree._Element:
    """The specs whose content model mentions *spec*.

    For ``model.pPart.edit``:

    ```xml
    <list type="usedBy">
      <item><gi>bibl</gi><seg type="module">core</seg></item>
      <item><ident type="class">model.phrase</ident></item>
      <item><gi>pc</gi><seg type="module">analysis</seg></item>
    </list>
    ```
    """
    return _ref_list(relation(index, spec, 'used_by'), list_type='usedBy')


def member_of(index: SpecIndex, spec: Spec) -> etree._Element:
    """The classes *spec* belongs to, model and attribute.

    For ``abbr``:

    ```xml
    <list type="memberOf">
      <item><ident type="class">att.global</ident></item>
      <item><ident type="class">att.typed</ident></item>
      <item><ident type="class">model.choicePart</ident></item>
      <!-- … -->
    </list>
    ```
    """
    refs = [index.ref(key, kind='class') for key in spec.member_of_keys]
    return _ref_list(refs, list_type='memberOf')


def _att_tree_item(branch: AttClassView) -> etree._Element:
    item = _tei('item')
    ident = etree.SubElement(item, qn('ident'))
    ident.set('type', 'class')
    ident.text = branch.ident
    if branch.attributes:
        atts = etree.SubElement(item, qn('list'))
        atts.set('type', 'atts')
        for att in branch.attributes:
            att_item = etree.SubElement(atts, qn('item'))
            att_item.set('ident', att.ident)
            att_item.set('n', att.anchor)
            if att.overridden:
                att_item.set('rend', 'overridden')
            att_item.text = att.ident
    if branch.nested:
        nested = etree.SubElement(item, qn('list'))
        nested.set('type', 'attTree')
        for child in branch.nested:
            nested.append(_att_tree_item(child))
    return item


def attribute_tree(index: SpecIndex, spec: Spec) -> etree._Element:
    """The att classes *spec* inherits from, as nested lists.

    Each class lists its own attributes (``@n`` is the anchor on the page that
    defines them), then the classes it inherits from. An attribute *spec*
    redefines itself carries ``rend="overridden"``. For ``abbr``:

    ```xml
    <list type="attTree">
      <item>
        <ident type="class">att.global</ident>
        <list type="atts">
          <item ident="xml:id" n="att-xml-id">xml:id</item>
          <item ident="n" n="att-n">n</item>
          <!-- … -->
        </list>
        <list type="attTree">
          <item>
            <ident type="class">att.global.analytic</ident>
            <list type="atts">
              <item ident="ana" n="att-ana">ana</item>
            </list>
          </item>
          <!-- … -->
        </list>
      </item>
      <!-- … -->
    </list>
    ```
    """
    wrap = _tei('list', type='attTree')
    for branch in relation(index, spec, 'attribute_tree'):
        wrap.append(_att_tree_item(branch))
    return wrap


def list_ref(index: SpecIndex, spec: Spec, *, lang: str = 'en') -> etree._Element:
    """The Guidelines sections *spec*'s ``listRef`` cites, as ``ref`` links.

    When the site publishes that section itself the link stays inside the site
    (``ref/@type='local'``); otherwise it points at the published P5
    documentation on tei-c.org, in *lang*. For ``abbr``, on a site that
    publishes the Guidelines:

    ```xml
    <list type="listRef">
      <item><ref type="local" target="CO.html#CONAAB">CONAAB</ref></item>
    </list>
    ```

    and on a customization's site:

    ```xml
    <list type="listRef">
      <item>
        <ref target="https://www.tei-c.org/release/doc/tei-p5-doc/en/html/CO.html#CONAAB">CONAAB</ref>
      </item>
    </list>
    ```
    """
    wrap = _tei('list', type='listRef')
    for target in spec.list_refs:
        code = target.lstrip('#')
        if not code:
            continue
        local = index.chapter_page(code)
        if local is None:
            match = _GUIDELINES_CHAPTER_RE.match(code)
            if not match:
                continue
            chapter = match.group(1)
        item = etree.SubElement(wrap, qn('item'))
        ref = etree.SubElement(item, qn('ref'))
        if local is not None:
            ref.set('type', 'local')
            ref.set('target', local)
        else:
            ref.set('target', f'{_TEI_P5_DOC}/{lang}/html/{chapter}.html#{code}')
        ref.text = code
    return wrap


def spec_count(index: SpecIndex, kind: str) -> int:
    """How many specs of *kind* the schema has: ``element``, ``model``,
    ``atts``, ``macro`` (with datatypes), or ``attributes``."""
    if kind in {'attribute', 'attributes'}:
        return len(index.attributes())
    pred = _KIND_PREDICATES.get(kind)
    return sum(1 for spec in index.all() if pred(spec)) if pred else 0


def spec_catalog(index: SpecIndex, kind: str) -> etree._Element:
    """A–Z catalog of the specs of *kind*, as nested lists keyed by letter.

    ``@n`` on an entry is the spec's module. The ``att.``, ``model.``,
    ``macro.`` and ``teidata.`` prefixes are skipped when sorting into
    letters. For ``element``:

    ```xml
    <list type="catalog">
      <item n="A">
        <list type="catalogItems">
          <item type="element" ident="ab" n="linking">ab</item>
          <item type="element" ident="abbr" n="core">abbr</item>
          <!-- … -->
        </list>
      </item>
      <!-- … -->
    </list>
    ```
    """
    pred = _KIND_PREDICATES.get(kind)
    specs = [s for s in index.all() if pred(s)] if pred else []
    buckets: dict[str, list[Spec]] = {}
    for spec in specs:
        buckets.setdefault(_bucket_letter(spec.ident), []).append(spec)
    wrap = _tei('list', type='catalog')
    for letter in sorted(buckets):
        group = etree.SubElement(wrap, qn('item'))
        group.set('n', letter)
        inner = etree.SubElement(group, qn('list'))
        inner.set('type', 'catalogItems')
        for spec in buckets[letter]:
            entry = etree.SubElement(inner, qn('item'))
            entry.set('type', spec.kind)
            entry.set('ident', spec.ident)
            if spec.module:
                entry.set('n', spec.module)
            entry.text = spec.ident
    return wrap


def attribute_catalog(index: SpecIndex) -> etree._Element:
    """Attribute name → defining class or element, in A–Z groups.

    Grouped by letter like the spec catalogs
    ([`spec_catalog`][opm.odd_expand.spec_catalog]): 275 attributes in one
    table is a page nothing breaks up, and the letter headings are what the
    jump links and the on-this-page rail key on.

    ```xml
    <list type="attCatalog">
      <item n="A">
        <list type="attCatalogItems">
          <item ident="active">
            <gi>interaction</gi>
            <gi>relation</gi>
          </item>
          <item ident="agent">
            <ident type="class">att.damaged</ident>
            <gi>gap</gi>
            <gi>unclear</gi>
          </item>
          <!-- … -->
        </list>
      </item>
      <!-- … -->
    </list>
    ```
    """
    wrap = _tei('list', type='attCatalog')
    buckets: dict[str, list[tuple[str, list[Spec]]]] = {}
    for ident, owners in index.attributes():
        buckets.setdefault(_bucket_letter(ident), []).append((ident, owners))
    for letter in sorted(buckets):
        group = etree.SubElement(wrap, qn('item'))
        group.set('n', letter)
        inner = etree.SubElement(group, qn('list'))
        inner.set('type', 'attCatalogItems')
        for ident, owners in buckets[letter]:
            item = etree.SubElement(inner, qn('item'))
            item.set('ident', ident)
            for spec in owners:
                _spec_pointer(
                    item, SpecRef(ident=spec.ident, kind=spec.kind, module=spec.module),
                )
    return wrap


def _bucket_letter(ident: str) -> str:
    rest = ident
    for prefix in ('att.', 'model.', 'macro.', 'teidata.'):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    ch = rest[:1].upper() if rest else '#'
    return ch if ch.isalpha() else '#'


# ── Outline numbers ───────────────────────────────────────────────────────

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
    """False for a div that only carries the title page.

    It stands in for ``front/titlePage``, which is no division of the text, and
    TEI's own numbering skips it (the title page is no div there to begin
    with). The home page needs no such rule: it sits directly under ``text``,
    outside front/body/back, so it never gets a label at all.
    """
    if localname(node) != 'div':
        return False
    return not any(localname(child) == 'titlePage' for child in node)


def _div_index(div: etree._Element) -> int:
    n = 1
    for sib in div.itersiblings(preceding=True):
        if _is_numbered_div(sib):
            n += 1
    return n


def heading_label(div: etree._Element) -> str:
    """Guidelines-style outline label for a chapter ``div`` or one of its sections.

    The TEI Guidelines number each part of the text differently: body chapters
    run ``1``, ``1.2``, ``1.2.1``; front matter takes lowercase roman numerals
    with a trailing dot (``iv.``, ``iv.1.``); back matter is lettered
    (``Appendix A``, ``Appendix A.1``). The index at every level is the div's
    position among its sibling divs, so the title page — a ``titlePage``, not a
    div — is skipped, exactly as in TEI's own stylesheets.

    Returns ``''`` for anything outside ``front``/``body``/``back`` (the home
    page, spec sections, catalogs of a customization that has no back matter).
    """
    if not _is_numbered_div(div):
        return ''
    chain: list[etree._Element] = [div]
    while True:
        parent = chain[-1].getparent()
        if parent is None or localname(parent) != 'div':
            break
        chain.append(parent)
    top_parent = chain[-1].getparent()
    part = localname(top_parent) if top_parent is not None else ''
    if part not in ('front', 'body', 'back'):
        return ''
    indices = [_div_index(el) for el in reversed(chain)]
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


def heading_mark(div: etree._Element) -> etree._Element | None:
    """[`heading_label`][opm.odd_expand.heading_label] as the ``seg`` that opens a heading.

    A chapter's label opens its page on a line of its own, so a bare index is
    spelled out to say what it counts: "Chapter 3", "Front matter iv". Back
    matter already reads as a phrase ("Appendix F"), and a section's label
    ("1.2", "iv.1.") is a mark beside its heading rather than a line, so both
    are left alone. ``@n`` keeps the bare label, for the chapter navigation.
    For the first body chapter, then its first section:

    ```xml
    <seg type="headingNumber" n="1">Chapter 1 </seg>
    <seg type="headingNumber" n="1.1">1.1 </seg>
    ```

    ``None`` where there is no label.
    """
    label = heading_label(div)
    if not label:
        return None
    text = label
    if label.isdigit():
        text = f'Chapter {label}'
    elif label.endswith('.') and label[:-1].isalpha():
        text = f'Front matter {label[:-1]}'
    return _label_seg(text, label=label)


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


# ── Table of contents ─────────────────────────────────────────────────────


def guidelines_toc(root: etree._Element) -> etree._Element | None:
    """The chapters of *root*, as lists grouped by front / body / back.

    Each chapter is an item with its label and a link, and its sections are a
    nested list. The title page has no label. For the Guidelines:

    ```xml
    <div type="guidelines-toc">
      <list type="toc" n="front">
        <item><ref target="Title.html">Title</ref></item>
        <item>
          <seg type="headingNumber">iv. </seg>
          <ref target="AB.html">About These Guidelines</ref>
          <list type="toc">
            <item>
              <seg type="headingNumber">iv.1. </seg>
              <ref target="AB.html#ABSTRUNC">Structure and Notational Conventions of this Document</ref>
            </item>
            <!-- … -->
          </list>
        </item>
        <!-- … -->
      </list>
      <list type="toc" n="body"><!-- … --></list>
      <list type="toc" n="back"><!-- … --></list>
    </div>
    ```

    ``None`` when there are no chapters.
    """
    groups: dict[str, list[etree._Element]] = {'front': [], 'body': [], 'back': []}
    for div in iter_guideline_chapters(root):
        parent = div.getparent()
        part = localname(parent) if parent is not None else 'body'
        groups[part if part in groups else 'body'].append(div)
    wrap = _tei('div', type='guidelines-toc')
    for part in ('front', 'body', 'back'):
        items = groups[part]
        if not items:
            continue
        inner = etree.SubElement(wrap, qn('list'))
        inner.set('type', 'toc')
        inner.set('n', part)
        for div in items:
            inner.append(_toc_item(div))
    return wrap if len(wrap) else None


def _toc_item(div: etree._Element) -> etree._Element:
    xml_id = div.get(XML_ID) or ''
    item = _tei('item')
    _append_mark(item, div)
    ref = etree.SubElement(item, qn('ref'))
    ref.set('target', f'{xml_id}.html' if xml_id else '#')
    ref.text = _heading_text(div) or xml_id
    nested = [
        child for child in div
        if localname(child) == 'div' and _heading_text(child)
    ]
    if nested:
        inner = etree.SubElement(item, qn('list'))
        inner.set('type', 'toc')
        for child in nested:
            child_id = child.get(XML_ID) or ''
            sub = etree.SubElement(inner, qn('item'))
            _append_mark(sub, child)
            sub_ref = etree.SubElement(sub, qn('ref'))
            if xml_id and child_id and child_id != xml_id:
                sub_ref.set('target', f'{xml_id}.html#{child_id}')
            elif child_id:
                sub_ref.set('target', f'{child_id}.html')
            else:
                sub_ref.set('target', '#')
            sub_ref.text = _heading_text(child) or child_id
    return item


def _append_mark(item: etree._Element, div: etree._Element) -> None:
    """Prefix a table-of-contents entry with its outline label, as TEI does.

    The bare label, not the spelled-out chapter heading: a list of chapters
    reads as a numbered list, and repeating the word on every line would only
    push the titles out of alignment.
    """
    label = heading_label(div)
    if label:
        item.append(_label_seg(label))


# ── Expanding the tree ────────────────────────────────────────────────────

#: Per spec kind: the relation lists appended to it, in this order.
_SPEC_LISTS = {
    'element': ('listRef', 'attTree', 'memberOf', 'mayContain', 'containedBy'),
    'att_class': ('attTree', 'usedBy', 'members'),
    'class': ('usedBy', 'members'),
    'macro': ('usedBy',),
    'datatype': ('usedBy',),
}

#: Per spec kind: the reference-page sections, as (anchor, heading, children).
_SECTIONS = {
    'element': (
        ('ref-models', 'Processing model', ('model', 'modelGrp', 'modelSequence')),
        ('ref-notes', 'Note', ('remarks',)),
        ('ref-examples', 'Examples', ('exemplum',)),
        ('ref-constraints', 'Schematron', ('constraintSpec',)),
        ('ref-schema', 'Content model', ('content',)),
    ),
    'att_class': (
        ('ref-notes', 'Note', ('remarks',)),
        ('ref-examples', 'Examples', ('exemplum',)),
    ),
    'class': (
        ('ref-notes', 'Note', ('remarks',)),
        ('ref-examples', 'Examples', ('exemplum',)),
    ),
    'macro': (
        ('ref-notes', 'Note', ('remarks',)),
        ('ref-examples', 'Examples', ('exemplum',)),
        ('ref-schema', 'Content model', ('content',)),
    ),
    'datatype': (
        ('ref-notes', 'Note', ('remarks',)),
        ('ref-schema', 'Content model', ('content',)),
    ),
}


def _page_kind(spec: Spec) -> str:
    if spec.kind == 'class':
        return 'att_class' if spec.is_att_class else 'class'
    return spec.kind


def _spec_list(index: SpecIndex, spec: Spec, name: str, lang: str) -> etree._Element:
    if name == 'listRef':
        return list_ref(index, spec, lang=lang)
    if name == 'attTree':
        return attribute_tree(index, spec)
    if name == 'memberOf':
        return member_of(index, spec)
    if name == 'mayContain':
        return may_contain(index, spec)
    if name == 'containedBy':
        return contained_by(index, spec)
    if name == 'usedBy':
        return used_by(index, spec)
    return members(index, spec)


def _wrap_sections(spec: Spec) -> None:
    """Move *spec*'s notes, examples, models, Schematron and content model into
    ``div[@type='spec-section']``, one per section that has something to show.

    Only direct children move: the ``exemplum`` and ``constraintSpec`` of an
    ``attDef`` belong to the attribute. The language variants move together,
    and the ODD picks the one to show.
    """
    node = spec.node
    for anchor, heading, names in _SECTIONS.get(_page_kind(spec), ()):
        children = [child for child in node if localname(child) in names]
        if not children:
            continue
        section = _tei('div', type='spec-section', n=anchor)
        head = etree.SubElement(section, qn('head'))
        head.text = heading
        for child in children:
            # A child's tail belongs to the spec's layout, not to the section.
            child.tail = None
            section.append(child)
        node.append(section)


def _add_heading_numbers(root: etree._Element) -> None:
    """Open each numbered heading with its outline label."""
    for div in list(root.iter(qn('div'))):
        mark = heading_mark(div)
        if mark is None:
            continue
        head = next((child for child in div if localname(child) == 'head'), None)
        if head is None:
            continue
        mark.tail = head.text
        head.text = None
        head.insert(0, mark)


def _pageless(el: etree._Element) -> bool:
    """True inside markup the ODD serializes as code rather than renders."""
    return _inside_egxml(el) or any(
        localname(anc) in {'content', 'constraintSpec'} for anc in el.iterancestors()
    )


def _link_spec_names(root: etree._Element, index: SpecIndex) -> None:
    """``@target`` on every ``gi``/``ident`` that names a spec with a page, and
    on the ``dataRef`` of an attribute's datatype."""
    def page(ident: str) -> str | None:
        spec = index.get(ident)
        return spec.href if spec is not None and spec.kind in PAGE_KINDS else None

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
    """Copy into each ``specDesc`` the gloss and description of the spec it names.

    ``@rend`` is the spec's element name, which the ODD uses as a CSS class.
    """
    for spec_desc in root.iter(qn('specDesc')):
        spec = index.get(spec_desc.get('key') or '')
        if spec is None:
            continue
        spec_desc.set('rend', localname(spec.node))
        for child in spec.node:
            if localname(child) in {'gloss', 'desc'}:
                copy = deepcopy(child)
                copy.tail = None
                spec_desc.append(copy)


def _link_chapters(root: etree._Element) -> None:
    """Give each chapter the previous and next one, for the chapter navigation.

    The first child of every division of front, body or back:

    ```xml
    <list type="chapterNav">
      <item n="prev"><ref target="AB.html" n="iv.">About These Guidelines</ref></item>
      <item n="next"><ref target="CO.html" n="2">Elements Available in All TEI Documents</ref></item>
    </list>
    ```

    ``ref/@n`` is the outline label. The first chapter has no ``prev`` item,
    the last no ``next``.
    """
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
            item = etree.SubElement(nav, qn('item'))
            item.set('n', n)
            ref = etree.SubElement(item, qn('ref'))
            ref.set('target', f'{other.get(XML_ID)}.html' if other.get(XML_ID) else '')
            label = heading_label(other)
            if label:
                ref.set('n', label)
            ref.text = ' '.join(_heading_text(other).split())
        div.insert(0, nav)


def _fill_catalogs(root: etree._Element, index: SpecIndex) -> None:
    ids = {xml_id: subtype for xml_id, subtype, _heading in CATALOGS}
    for div in root.iter(qn('div')):
        xml_id = div.get(XML_ID)
        if xml_id not in ids:
            continue
        subtype = ids[xml_id]
        div.append(spec_catalog(index, subtype) if subtype else attribute_catalog(index))


def _fill_home(root: etree._Element, index: SpecIndex, toc: etree._Element | None) -> None:
    """The table of contents and the reference list, onto the home page.

    ```xml
    <list type="reference">
      <item><ref target="REF-ELEMENTS.html">Elements</ref> <num>590</num></item>
      <!-- … -->
    </list>
    ```
    """
    home = next((div for div in root.iter(qn('div')) if div.get(XML_ID) == 'index'), None)
    if home is None:
        return
    if toc is not None:
        home.append(toc)
    reference = _tei('list', type='reference')
    for xml_id, label, kind in _REFERENCE:
        item = etree.SubElement(reference, qn('item'))
        ref = etree.SubElement(item, qn('ref'))
        ref.set('target', f'{xml_id}.html')
        ref.text = label
        ref.tail = ' '
        num = etree.SubElement(item, qn('num'))
        num.text = str(spec_count(index, kind))
    home.append(reference)


def expand_document_tree(root: etree._Element, index: SpecIndex, *, lang: str = 'en') -> None:
    """Write everything tagdocs needs into *root*, so it renders without lookups.

    *index* must be built from *root* before this runs: the relations are read
    from it, never from what this adds. Each spec that has a page (the copy
    stamped ``xml:id="ref-{ident}"``) gets its relation lists and its sections;
    the catalog pages get their A–Z lists and the home page its table of
    contents and reference list; each chapter learns the previous and next
    one; numbered headings get their label; and every
    ``gi``/``ident`` naming a spec gets the ``@target`` of its page.
    """
    toc = guidelines_toc(root)
    for spec in index.all():
        if spec.kind not in PAGE_KINDS or spec.node.get(XML_ID) != f'ref-{spec.ident}':
            continue
        for name in _SPEC_LISTS.get(_page_kind(spec), ()):
            spec.node.append(_spec_list(index, spec, name, lang))
        _wrap_sections(spec)
    _fill_catalogs(root, index)
    _fill_home(root, index, toc)
    _link_chapters(root)
    _add_heading_numbers(root)
    _describe_spec_refs(root, index)
    _link_spec_names(root, index)


__all__ = [
    'CATALOGS',
    'attribute_catalog',
    'attribute_tree',
    'contained_by',
    'expand_document_tree',
    'grouped',
    'guidelines_toc',
    'heading_label',
    'heading_mark',
    'list_ref',
    'may_contain',
    'member_of',
    'members',
    'relation',
    'spec_catalog',
    'spec_count',
    'used_by',
]
