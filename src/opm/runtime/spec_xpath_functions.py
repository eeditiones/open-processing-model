# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``tp:`` helpers that expose [`SpecIndex`][opm.spec_index.SpecIndex] to tagdocs.

The graph (contained-by, may-contain, members, used-by, attribute inheritance)
is computed in Python. These functions return small TEI fragments so the
documentation ODD can render them with ordinary models — catalogs, ref pages,
module groups — instead of assembling HTML in the site builder.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from lxml import etree

from opm.runtime.xpath_env import current_environment
from opm.runtime.xpath_extensions import expect_element, expect_string
from opm.spec_index import (
    TEXT_IDENT,
    AttClassView,
    Spec,
    SpecIndex,
    SpecRef,
    localname,
    pick_lang,
    qn,
    serialize_spec_xml,
)

_GUIDELINES_CHAPTER_RE = re.compile(r'^([A-Z]{2})')
_TEI_P5_DOC = 'https://www.tei-c.org/release/doc/tei-p5-doc'

_USAGE_LABELS = {
    'opt': 'Optional',
    'req': 'Required',
    'rec': 'Recommended',
    'mwa': 'Mandatory when applicable',
}

MODEL_TAGS = {'model', 'modelGrp', 'modelSequence'}

_KIND_TAGS = {
    'element': 'elementSpec',
    'class': 'classSpec',
    'macro': 'macroSpec',
    'datatype': 'dataSpec',
}

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


def _index(node: Any = None) -> SpecIndex | None:
    env = current_environment()
    if env is not None and env.spec_index is not None:
        return env.spec_index
    root = None
    if env is not None and env.root is not None:
        root = env.root
    elif node is not None:
        try:
            root = expect_element(node, arg_name='spec').getroottree().getroot()
        except ValueError:
            root = None
    if root is None:
        return None
    lang = 'en'
    if env is not None:
        lang = str((env.parameters or {}).get('lng') or 'en')
        index = SpecIndex.from_tree(root, lang=lang)
        env.spec_index = index
        return index
    return SpecIndex.from_tree(root, lang=lang)


def _spec_of(value: Any) -> Spec | None:
    node = expect_element(value, arg_name='spec')
    ident = node.get('ident')
    if not ident:
        return None
    index = _index(node)
    if index is None:
        return None
    return index.get(ident)


def _tei(tag: str, **attrs: str | None) -> etree._Element:
    el = etree.Element(qn(tag))
    for key, val in attrs.items():
        if val:
            el.set(key.replace('_', ':') if key == 'xml_id' else key, val)
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


def _grouped_list(spec: Spec, refs: list[SpecRef], *, list_type: str) -> etree._Element:
    wrap = _tei('list', type=list_type)
    groups = spec.grouped(refs)
    if not groups:
        empty = _tei('seg', type='empty')
        empty.text = 'empty'
        return empty
    for module, group in groups:
        bucket = etree.SubElement(wrap, qn('item'))
        if module:
            bucket.set('n', module)
        inner = etree.SubElement(bucket, qn('list'))
        inner.set('type', 'specItems')
        for ref in group:
            inner.append(_spec_item(ref, include_module=False))
    return wrap


def _section(anchor: str, heading: str) -> etree._Element:
    wrap = _tei('div', type='spec-section')
    wrap.set('n', anchor)
    head = etree.SubElement(wrap, qn('head'))
    head.text = heading
    return wrap


def spec_models(spec: Any) -> etree._Element | str:
    """Processing-model tree as a spec section, or the empty string."""
    resolved = _spec_of(spec)
    if resolved is None:
        return ''
    children = [
        child for child in resolved.node
        if localname(child) in MODEL_TAGS
    ]
    if not children:
        return ''
    wrap = _section('ref-models', 'Processing model')
    for child in children:
        wrap.append(copy.deepcopy(child))
    return wrap


def spec_notes(spec: Any) -> etree._Element | str:
    resolved = _spec_of(spec)
    if resolved is None or resolved.remarks is None:
        return ''
    wrap = _section('ref-notes', 'Note')
    wrap.append(copy.deepcopy(resolved.remarks))
    return wrap


def spec_examples(spec: Any) -> etree._Element | str:
    resolved = _spec_of(spec)
    if resolved is None or not resolved.exempla:
        return ''
    heading = 'Example' if len(resolved.exempla) == 1 else 'Examples'
    wrap = _section('ref-examples', heading)
    for example in resolved.exempla:
        wrap.append(copy.deepcopy(example))
    return wrap


def spec_constraints(spec: Any) -> etree._Element | str:
    resolved = _spec_of(spec)
    if resolved is None or not resolved.constraints:
        return ''
    wrap = _section('ref-constraints', 'Schematron')
    for constraint in resolved.constraints:
        wrap.append(copy.deepcopy(constraint))
    return wrap


def spec_content(spec: Any) -> etree._Element | str:
    resolved = _spec_of(spec)
    if resolved is None or resolved.content is None:
        return ''
    wrap = _section('ref-schema', 'Content model')
    wrap.append(copy.deepcopy(resolved.content))
    return wrap


def contained_by(spec: Any) -> etree._Element:
    """TEI list of elements that may contain *spec*."""
    resolved = _spec_of(spec)
    if resolved is None:
        return _tei('list', type='containedBy')
    return _grouped_list(resolved, resolved.contained_by, list_type='containedBy')


def may_contain(spec: Any) -> etree._Element:
    """TEI list of what *spec* may contain, grouped by module."""
    resolved = _spec_of(spec)
    if resolved is None:
        return _tei('list', type='mayContain')
    return _grouped_list(resolved, resolved.may_contain, list_type='mayContain')


def members(spec: Any) -> etree._Element:
    """TEI list of specs that claim membership in *spec*."""
    resolved = _spec_of(spec)
    if resolved is None:
        return _tei('list', type='members')
    return _ref_list(resolved.members, list_type='members')


def used_by(spec: Any) -> etree._Element:
    """TEI list of specs whose content model mentions *spec*."""
    resolved = _spec_of(spec)
    if resolved is None:
        return _tei('list', type='usedBy')
    return _ref_list(resolved.used_by, list_type='usedBy')


def member_of(spec: Any) -> etree._Element:
    """TEI list of classes *spec* belongs to (model and attribute)."""
    resolved = _spec_of(spec)
    index = _index(spec)
    if resolved is None or index is None:
        return _tei('list', type='memberOf')
    refs = [index.ref(key, kind='class') for key in resolved.member_of_keys]
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


def has_attribute_tree(spec: Any) -> bool:
    """True when *spec* inherits attributes from one or more att classes."""
    resolved = _spec_of(spec)
    return bool(resolved and resolved.attribute_tree)


def attribute_tree(spec: Any) -> etree._Element:
    """Inherited att-class tree for *spec* (nested lists)."""
    wrap = _tei('list', type='attTree')
    resolved = _spec_of(spec)
    if resolved is None:
        return wrap
    for branch in resolved.attribute_tree:
        wrap.append(_att_tree_item(branch))
    return wrap


def spec_exists(ident: Any, node: Any = None) -> bool:
    """True when *ident* is a documented element, class, macro or datatype."""
    spec = _spec_by_ident(ident, node)
    return spec is not None and spec.kind in {'element', 'class', 'macro', 'datatype'}


def spec_kind_tag(ident: Any, node: Any = None) -> str:
    """``elementSpec`` / ``classSpec`` / … for *ident*, for ``specDesc`` CSS."""
    spec = _spec_by_ident(ident, node)
    if spec is None:
        return 'elementSpec'
    return _KIND_TAGS.get(spec.kind, 'elementSpec')


def spec_gloss_label(ident: Any, node: Any = None) -> str:
    """``(gloss) `` prefix for a ``specDesc``, or the empty string."""
    spec = _spec_by_ident(ident, node)
    if spec is None or spec.gloss is None:
        return ''
    text = ' '.join(spec.gloss.itertext()).strip()
    return f'({text}) ' if text else ''


def spec_desc(ident: Any, node: Any = None) -> etree._Element | str:
    """The language-picked ``desc`` node for *ident*, or the empty string."""
    spec = _spec_by_ident(ident, node)
    if spec is None or spec.desc is None:
        return ''
    return spec.desc


def _spec_by_ident(ident: Any, node: Any = None) -> Spec | None:
    index = _index(node)
    if index is None:
        return None
    key = expect_string(ident, arg_name='spec ident').strip()
    if not key:
        return None
    return index.get(key)


def spec_count(kind: Any, node: Any = None) -> int:
    """Number of documented specs of *kind* (element, model, atts, macro)."""
    index = _index(node)
    if index is None:
        return 0
    key = expect_string(kind, arg_name='spec_count(kind)').strip().lower()
    pred = _KIND_PREDICATES.get(key)
    if key in {'attribute', 'attributes'}:
        return len(index.attributes())
    if pred is None:
        return 0
    return sum(1 for spec in index.all() if pred(spec))


def spec_catalog(kind: Any, node: Any = None) -> etree._Element:
    """A–Z catalog of specs of *kind*, as nested lists keyed by letter."""
    wrap = _tei('list', type='catalog')
    index = _index(node)
    if index is None:
        return wrap
    key = expect_string(kind, arg_name='spec_catalog(kind)').strip().lower()
    pred = _KIND_PREDICATES.get(key)
    specs = [s for s in index.all() if pred(s)] if pred else []
    buckets: dict[str, list[Spec]] = {}
    for spec in specs:
        letter = _bucket_letter(spec.ident)
        buckets.setdefault(letter, []).append(spec)
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


def attribute_catalog(node: Any = None) -> etree._Element:
    """Attribute name → defining class or element, as a definition list."""
    wrap = _tei('list', type='attCatalog')
    index = _index(node)
    if index is None:
        return wrap
    for ident, owners in index.attributes():
        item = etree.SubElement(wrap, qn('item'))
        item.set('ident', ident)
        for spec in owners:
            _spec_pointer(item, SpecRef(ident=spec.ident, kind=spec.kind, module=spec.module))
    return wrap


def usage_label(usage: Any) -> str:
    """Spell out a TEI ``@usage`` code (``opt`` → ``Optional``)."""
    if usage is None or usage == [] or usage == ():
        return ''
    code = expect_string(usage, arg_name='usage_label(usage)').strip()
    return _USAGE_LABELS.get(code, code)


def att_datatype(att_def: Any) -> etree._Element | str:
    """``ident`` pointing at the attribute's datatype, or the empty string."""
    node = expect_element(att_def, arg_name='att_datatype(attDef)')
    data_ref = node.find(f'.//{qn("dataRef")}')
    if data_ref is None:
        return ''
    key = data_ref.get('key') or data_ref.get('name')
    if not key:
        return ''
    ident = _tei('ident', type='datatype')
    ident.text = key
    return ident


def serialize_spec(node: Any) -> str:
    """Pretty-print a spec subtree (content model, Schematron, ``pb:template``)."""
    if node is None or node == [] or node == ():
        return ''
    el = expect_element(node, arg_name='serialize_spec(node)')
    return serialize_spec_xml(el)


def list_ref(spec: Any) -> etree._Element:
    """Guidelines ``listRef`` pointers as ``ref`` links to the published P5 docs."""
    wrap = _tei('list', type='listRef')
    resolved = _spec_of(spec)
    env = current_environment()
    lang = str((env.parameters or {}).get('lng') or 'en') if env else 'en'
    targets = resolved.list_refs if resolved is not None else []
    if resolved is None:
        node = expect_element(spec, arg_name='list_ref(spec)')
        targets = [
            (p.get('target') or '').lstrip('#')
            for p in node.iter(qn('ptr'))
            if p.get('target') and localname(p.getparent()) == 'listRef'
        ]
    for target in targets:
        code = target.lstrip('#')
        if not code:
            continue
        match = _GUIDELINES_CHAPTER_RE.match(code)
        if not match:
            continue
        chapter = match.group(1)
        item = etree.SubElement(wrap, qn('item'))
        ref = etree.SubElement(item, qn('ref'))
        ref.set('target', f'{_TEI_P5_DOC}/{lang}/html/{chapter}.html#{code}')
        ref.text = code
    return wrap


def guidelines_toc(node: Any = None) -> etree._Element | str:
    """TEI lists of chapter ``div``s, grouped by front / body / back.

    Headings (Front Matter, Text Body, …) stay in tagdocs; this only walks
    the prepared tree and emits ``list[@n]`` fragments. ``$parameters?root``
    is the home chunk, so the document element is used.
    """
    root = _document_root(node)
    if root is None:
        return ''
    groups: dict[str, list[etree._Element]] = {'front': [], 'body': [], 'back': []}
    for div in _top_chapters(root):
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
    return wrap if len(wrap) else ''


def _document_root(node: Any = None) -> etree._Element | None:
    """Document element for *node* or ``$parameters?root``, not the chunk itself."""
    env = current_environment()
    if env is not None and env.root is not None:
        try:
            return env.root.getroottree().getroot()
        except AttributeError:
            return env.root
    if node is not None and node != [] and node != ():
        try:
            el = expect_element(node, arg_name='guidelines_toc(node)')
            return el.getroottree().getroot()
        except ValueError:
            return None
    return None


def _top_chapters(root: etree._Element):
    from opm.odd_schema import iter_guideline_chapters
    from opm.spec_index import OPM_PAGE, PAGE_CHAPTER

    for div in iter_guideline_chapters(root):
        if div.get(OPM_PAGE) != PAGE_CHAPTER:
            continue
        yield div


def _toc_item(div: etree._Element) -> etree._Element:
    xml_id = div.get('{http://www.w3.org/XML/1998/namespace}id') or ''
    item = _tei('item')
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
        chapter_id = xml_id
        for child in nested:
            child_id = child.get('{http://www.w3.org/XML/1998/namespace}id') or ''
            sub = etree.SubElement(inner, qn('item'))
            sub_ref = etree.SubElement(sub, qn('ref'))
            if chapter_id and child_id and child_id != chapter_id:
                sub_ref.set('target', f'{chapter_id}.html#{child_id}')
            elif child_id:
                sub_ref.set('target', f'{child_id}.html')
            else:
                sub_ref.set('target', '#')
            sub_ref.text = _heading_text(child) or child_id
    return item


def _heading_text(div: etree._Element) -> str:
    for child in div:
        if localname(child) == 'head':
            return ' '.join(child.itertext()).strip()
    return ''


def _bucket_letter(ident: str) -> str:
    rest = ident
    for prefix in ('att.', 'model.', 'macro.', 'teidata.'):
        if rest.startswith(prefix):
            rest = rest[len(prefix):]
            break
    ch = rest[:1].upper() if rest else '#'
    return ch if ch.isalpha() else '#'


def lang_node(nodes: Any, name: str | None = None) -> etree._Element | str:
    """Pick the ``xml:lang``-matching child named *name* (default: context children).

    Kept for ODD expressions that need the same preference as SpecIndex:
    requested language, then unlanguaged, then the first.
    """
    env = current_environment()
    lang = str((env.parameters or {}).get('lng') or 'en') if env else 'en'
    parent = expect_element(nodes, arg_name='lang_node(nodes)')
    tag = expect_string(name, arg_name='lang_node(name)').strip() if name else ''
    candidates = [c for c in parent if not tag or localname(c) == tag]
    hit = pick_lang(candidates, lang)
    return hit if hit is not None else ''
