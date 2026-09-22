# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-memory graph of TEI ODD specification elements.

This is the documentation counterpart of
[`opm.odd_compiler.parse_odd`][opm.odd_compiler.parse_odd]: that module merges
``elementSpec``s so they can be compiled, while this one indexes
``elementSpec`` / ``classSpec`` / ``macroSpec`` / ``dataSpec`` and precomputes
the inverse relations the TEI Stylesheets emit as "Contained by", "May contain",
"Members" and "Used by", plus the processing models declared on each element.

The input is a compiled TEI document or ODD (``p5subset.xml``, a full
Guidelines ``p5.xml``, or the output of
[`compile_schema`][opm.odd_schema.compile_schema]). Nested TEI in ``desc``,
``gloss``, ``remarks`` and ``exemplum`` is left as lxml so a processing-model
transform can render it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from opm.xml_parser import make_parser

TEI_NS = 'http://www.tei-c.org/ns/1.0'
PB_NS = 'http://teipublisher.com/1.0'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
EX_NS = 'http://www.tei-c.org/ns/Examples'

_PARSER = make_parser(remove_comments=True)

SPEC_TAGS = {
    'elementSpec': 'element',
    'classSpec': 'class',
    'macroSpec': 'macro',
    'dataSpec': 'datatype',
    'moduleSpec': 'module',
}

MODEL_TAGS = {'model', 'modelGrp', 'modelSequence'}

TEXT_IDENT = '#TEXT'


def localname(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ''
    return etree.QName(tag).localname


def qn(name: str) -> str:
    return f'{{{TEI_NS}}}{name}'


def _inside_egxml(el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None:
        tag = parent.tag
        if isinstance(tag, str):
            q = etree.QName(tag)
            if q.localname == 'egXML' or q.namespace == EX_NS:
                return True
        parent = parent.getparent()
    return False


def pick_lang(elements: list[etree._Element], lang: str) -> etree._Element | None:
    """Prefer ``xml:lang=*lang*``, then an unlanguaged node, then the first."""
    if not elements:
        return None
    matched = [el for el in elements if el.get(XML_LANG) == lang]
    if matched:
        return matched[0]
    unlanguaged = [el for el in elements if not el.get(XML_LANG)]
    if unlanguaged:
        return unlanguaged[0]
    return elements[0]


def _children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if localname(c) == name]


def _first(el: etree._Element, name: str) -> etree._Element | None:
    for c in el:
        if localname(c) == name:
            return c
    return None


def serialize_spec_xml(el: etree._Element | None) -> str:
    """Pretty-print *el* without a default TEI xmlns declaration.

    ``with_tail=False`` so mixed-content examples (element + following text)
    stay well-formed; tails are handled by
    [`serialize_egxml`][opm.runtime.common_xpath_functions.serialize_egxml].
    """
    if el is None:
        return ''
    copy = etree.fromstring(etree.tostring(el, with_tail=False))
    etree.cleanup_namespaces(copy)
    text = etree.tostring(copy, encoding='unicode', pretty_print=True)
    return text.replace(' xmlns="http://www.tei-c.org/ns/1.0"', '').strip()


@dataclass(frozen=True)
class SpecRef:
    """A pointer to another spec, used in membership / content lists."""

    ident: str
    kind: str
    module: str | None = None

    @property
    def href(self) -> str:
        if self.kind == 'text':
            return ''
        return f'ref-{self.ident}.html'

    @property
    def is_text(self) -> bool:
        return self.kind == 'text'


@dataclass
class AttDefView:
    ident: str
    usage: str | None
    datatype: str | None
    desc: etree._Element | None
    gloss: etree._Element | None
    exemplum: etree._Element | None
    overridden: bool = False
    node: etree._Element | None = None
    desc_html: str = ''
    exemplum_html: str = ''

    @property
    def anchor(self) -> str:
        return 'att-' + self.ident.replace(':', '-')


@dataclass
class AttClassView:
    ident: str
    attributes: list[AttDefView] = field(default_factory=list)
    nested: list[AttClassView] = field(default_factory=list)

    @property
    def href(self) -> str:
        return f'ref-{self.ident}.html'


@dataclass
class ModelParam:
    name: str
    value: str | None = None


@dataclass
class ModelView:
    """One ``model``, ``modelGrp`` or ``modelSequence`` on an elementSpec."""

    kind: str
    behaviour: str | None = None
    predicate: str | None = None
    output: str | None = None
    css_class: str | None = None
    use: str | None = None
    desc: etree._Element | None = None
    desc_html: str = ''
    params: list[ModelParam] = field(default_factory=list)
    template: str | None = None
    renditions: list[tuple[str | None, str]] = field(default_factory=list)
    children: list[ModelView] = field(default_factory=list)


@dataclass
class Spec:
    ident: str
    kind: str
    module: str | None
    class_type: str | None
    #: The canonical spec element: the copy that gets a reference page, and
    #: that [`expand_document_tree`][opm.odd_expand.expand_document_tree]
    #: writes the relations into.
    node: etree._Element
    content: etree._Element | None
    list_refs: list[str]
    member_of_keys: list[str]
    local_atts: list[AttDefView]
    suppressed_atts: set[str] = field(default_factory=set)
    models: list[ModelView] = field(default_factory=list)
    #: The index this spec belongs to, set by [`SpecIndex`][opm.spec_index.SpecIndex].
    index: SpecIndex | None = field(default=None, repr=False, compare=False)

    @property
    def href(self) -> str:
        return f'ref-{self.ident}.html'

    # The relations below are not facts of the spec but readings of the graph,
    # derived from the index's primitives in opm.odd_expand. They stay here as
    # properties so code written against the precomputed fields of earlier
    # releases keeps working.

    @property
    def contained_by(self) -> list[SpecRef]:
        """Elements whose content may hold this one (derived; see [`contained_by`][opm.odd_expand.contained_by])."""
        return _relation(self, 'contained_by')

    @property
    def may_contain(self) -> list[SpecRef]:
        """What this spec's content allows (derived; see [`may_contain`][opm.odd_expand.may_contain])."""
        return _relation(self, 'may_contain')

    @property
    def members(self) -> list[SpecRef]:
        """Specs claiming membership in this class (derived; see [`members`][opm.odd_expand.members])."""
        return _relation(self, 'members')

    @property
    def used_by(self) -> list[SpecRef]:
        """Specs whose content models use this one (derived; see [`used_by`][opm.odd_expand.used_by])."""
        return _relation(self, 'used_by')

    @property
    def attribute_tree(self) -> list[AttClassView]:
        """Inherited attribute classes (derived; see [`attribute_tree`][opm.odd_expand.attribute_tree])."""
        return _relation(self, 'attribute_tree')

    @property
    def is_model_class(self) -> bool:
        return self.kind == 'class' and (
            self.class_type == 'model' or (self.ident or '').startswith('model.')
        )

    @property
    def is_att_class(self) -> bool:
        return self.kind == 'class' and (
            self.class_type == 'atts' or (self.ident or '').startswith('att.')
        )

    @property
    def model_classes(self) -> list[str]:
        return [k for k in self.member_of_keys if k.startswith('model.')]

    @property
    def att_classes(self) -> list[str]:
        return [k for k in self.member_of_keys if k.startswith('att.')]

    def grouped(self, refs: list[SpecRef]) -> list[tuple[str, list[SpecRef]]]:
        """Group *refs* by module, with character-data last (see [`grouped`][opm.odd_expand.grouped])."""
        from opm.odd_expand import grouped

        return grouped(refs)


def _relation(spec: Spec, name: str) -> list:
    """A derived relation of *spec*, computed by [`opm.odd_expand`][opm.odd_expand]."""
    if spec.index is None:
        return []
    from opm.odd_expand import relation

    return relation(spec.index, spec, name)


class SpecIndex:
    """The specs of a schema and the direct facts about them, indexed.

    The primitives: specs by ident, direct class memberships and content-model
    references, both inverted so that "who is a member of X" and "who refers
    to X" are lookups rather than scans, and the two graph walks everything
    else is built from. What those facts *mean* on a documentation page —
    contained-by, may-contain, used-by, attribute inheritance — is derived on
    top, in [`opm.odd_expand`][opm.odd_expand],
    and cached in [`memo`][opm.spec_index.SpecIndex.memo]. It is the
    counterpart of the indexes eXist gave the XQuery version of this code.
    """

    def __init__(
        self,
        specs: dict[str, Spec],
        *,
        modules: dict[str, Spec] | None = None,
        lang: str = 'en',
        title: str = '',
        chapter_anchors: dict[str, str] | None = None,
    ):
        self._specs = specs
        #: ``moduleSpec``s, kept apart from *specs* because module idents are
        #: their own namespace — see [`_collect_specs`][opm.spec_index._collect_specs].
        self._modules = modules or {}
        self.lang = lang
        self.title = title
        #: ``xml:id`` → the chapter page it lands on, for every id inside a
        #: published chapter. Empty unless the site publishes chapter prose.
        self._chapter_anchors = chapter_anchors or {}
        self.memo: dict[Any, Any] = {}
        """Cache for what layers above derive from the primitives, keyed by
        whatever they choose (``('contained_by', 'p')``). Lives and dies with
        the index, so a derivation is computed once per document."""
        self._build_lookups()

    def _build_lookups(self) -> None:
        """Invert memberships and content references once, for O(1) primitives."""
        self._members_of: dict[str, list[str]] = defaultdict(list)
        self._referrers: dict[tuple[str, str], list[SpecRef]] = defaultdict(list)
        self._content_refs: dict[str, list[tuple[str, str]]] = {}
        for spec in self._specs.values():
            spec.index = self
            for key in spec.member_of_keys:
                self._members_of[key].append(spec.ident)
            refs = _content_refs(spec.content) if spec.content is not None else []
            self._content_refs[spec.ident] = refs
            for ref_kind, key in refs:
                self._referrers[(ref_kind, key)].append(
                    SpecRef(ident=spec.ident, kind=spec.kind, module=spec.module)
                )

    @classmethod
    def from_tree(cls, root: etree._Element, *, lang: str = 'en', title: str = '') -> SpecIndex:
        specs, modules = _collect_specs(root, lang=lang)
        if not title:
            title = _document_title(root) or 'ODD documentation'
        return cls(
            specs,
            modules=modules,
            lang=lang,
            title=title,
            chapter_anchors=_collect_chapter_anchors(root),
        )

    def chapter_page(self, xml_id: str) -> str | None:
        """Local page URL for *xml_id*, or ``None`` when it is not published.

        Ids are only known when the site documents the schema whose prose it
        carries (TEI itself, a Guidelines ``p5.xml``, a Specs directory).
        A customization publishes no TEI chapters, so pointers into them stay
        external.
        """
        chapter = self._chapter_anchors.get(xml_id)
        if chapter is None:
            return None
        return f'{chapter}.html' if chapter == xml_id else f'{chapter}.html#{xml_id}'

    @classmethod
    def from_path(cls, path: Path | str, *, lang: str = 'en') -> SpecIndex:
        path = Path(path)
        tree = etree.parse(str(path), _PARSER)
        return cls.from_tree(tree.getroot(), lang=lang, title=path.stem)

    def get(self, ident: str) -> Spec | None:
        return self._specs.get(ident)

    def require(self, ident: str) -> Spec:
        spec = self.get(ident)
        if spec is None:
            raise KeyError(ident)
        return spec

    def element(self, ident: str) -> Spec:
        spec = self.require(ident)
        if spec.kind != 'element':
            raise KeyError(ident)
        return spec

    def ref(self, ident: str, *, kind: str | None = None) -> SpecRef:
        spec = self.get(ident)
        if spec is None:
            return SpecRef(ident=ident, kind=kind or 'element')
        return SpecRef(ident=spec.ident, kind=spec.kind, module=spec.module)

    def all(self) -> list[Spec]:
        return sorted(self._specs.values(), key=lambda s: s.ident.lower())

    def elements(self) -> list[Spec]:
        return [s for s in self.all() if s.kind == 'element']

    def model_classes(self) -> list[Spec]:
        return [s for s in self.all() if s.is_model_class]

    def att_classes(self) -> list[Spec]:
        return [s for s in self.all() if s.is_att_class]

    def macros(self) -> list[Spec]:
        return [s for s in self.all() if s.kind == 'macro']

    def datatypes(self) -> list[Spec]:
        return [s for s in self.all() if s.kind == 'datatype']

    def modules(self) -> list[Spec]:
        return sorted(self._modules.values(), key=lambda s: s.ident.lower())

    def module(self, ident: str) -> Spec | None:
        """A ``moduleSpec`` by ident. Modules are not reachable via `get`."""
        return self._modules.get(ident)

    def attributes(self) -> list[tuple[str, list[Spec]]]:
        """Attribute ident → specs (classes/elements) that define it, A–Z."""
        owners: dict[str, list[Spec]] = defaultdict(list)
        for spec in self.all():
            if spec.kind not in {'class', 'element'}:
                continue
            for att in spec.local_atts:
                owners[att.ident].append(spec)
        return sorted(owners.items(), key=lambda kv: kv[0].lower())

    def members_of(self, key: str) -> list[SpecRef]:
        """Specs whose ``memberOf`` names *key* directly, A–Z."""
        return unique_refs([self.ref(ident) for ident in self._members_of.get(key, ())])

    def referrers(self, kind: str, key: str) -> list[SpecRef]:
        """Specs whose content model refers to *key* directly.

        *kind* is the reference: ``element`` (``elementRef``), ``class``
        (``classRef``), ``macro`` (``macroRef``) or ``data`` (``dataRef``).
        In document order, duplicates kept, as the references stand.
        """
        return list(self._referrers.get((kind, key), ()))

    def content_refs(self, ident: str) -> list[tuple[str, str]]:
        """``(kind, key)`` for every reference in *ident*'s content model."""
        return list(self._content_refs.get(ident, ()))

    def class_members_transitive(self, ident: str) -> list[SpecRef]:
        """Elements in *ident* or any subclass, walking ``memberOf`` downward."""
        out: list[SpecRef] = []
        seen: set[str] = set()
        stack = [ident]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for member in self._members_of.get(current, ()):
                spec = self._specs.get(member)
                if spec is None:
                    continue
                if spec.kind == 'element':
                    out.append(self.ref(spec.ident))
                elif spec.kind == 'class':
                    stack.append(spec.ident)
        return unique_refs(out)

    def expand_model_ancestors(self, keys: list[str]) -> list[str]:
        """Walk *up* model-class membership (``p`` → ``model.pLike`` → …)."""
        out: list[str] = []
        seen: set[str] = set()
        stack = list(keys)
        while stack:
            key = stack.pop()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
            spec = self.get(key)
            if spec is None:
                continue
            stack.extend(spec.model_classes)
        return out


def unique_refs(refs: list[SpecRef]) -> list[SpecRef]:
    """*refs* without repeats, character data first, then A–Z."""
    seen: set[tuple[str, str]] = set()
    out: list[SpecRef] = []
    for ref in refs:
        key = (ref.kind, ref.ident)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    out.sort(key=lambda r: (r.kind != 'text', (r.ident or '').lower()))
    return out


def _content_refs(content: etree._Element) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for el in content.iter():
        tag = localname(el)
        if tag == 'elementRef' and el.get('key'):
            refs.append(('element', el.get('key') or ''))
        elif tag == 'classRef' and el.get('key'):
            refs.append(('class', el.get('key') or ''))
        elif tag == 'macroRef' and el.get('key'):
            refs.append(('macro', el.get('key') or ''))
        elif tag == 'dataRef' and (el.get('key') or el.get('name')):
            refs.append(('data', el.get('key') or el.get('name') or ''))
    return refs


def _att_def(el: etree._Element, lang: str) -> AttDefView:
    datatype_el = el.find(f'.//{qn("dataRef")}')
    datatype = None
    if datatype_el is not None:
        datatype = datatype_el.get('key') or datatype_el.get('name')
    return AttDefView(
        ident=el.get('ident') or '',
        usage=el.get('usage'),
        datatype=datatype,
        desc=pick_lang(_children(el, 'desc'), lang),
        gloss=pick_lang(_children(el, 'gloss'), lang),
        exemplum=pick_lang(_children(el, 'exemplum'), lang),
        node=el,
    )


def _spec_from_element(el: etree._Element, kind: str, lang: str) -> Spec | None:
    ident = el.get('ident')
    if not ident:
        return None
    classes = _first(el, 'classes')
    member_of = []
    if classes is not None:
        member_of = [
            m.get('key') or ''
            for m in _children(classes, 'memberOf')
            if m.get('key')
        ]
    att_list = _first(el, 'attList')
    local_atts = []
    suppressed_atts: set[str] = set()
    if att_list is not None:
        for a in att_list.iter(qn('attDef')):
            att_ident = a.get('ident')
            if not att_ident:
                continue
            if (a.get('mode') or '').lower() == 'delete':
                suppressed_atts.add(att_ident)
                continue
            local_atts.append(_att_def(a, lang))
    ptrs = [
        (p.get('target') or '').lstrip('#')
        for p in el.iter(qn('ptr'))
        if p.get('target') and not _inside_egxml(p)
        and localname(p.getparent()) == 'listRef'
    ]
    return Spec(
        ident=ident,
        kind=kind,
        module=el.get('module'),
        class_type=el.get('type'),
        node=el,
        content=_first(el, 'content'),
        list_refs=ptrs,
        member_of_keys=member_of,
        local_atts=local_atts,
        suppressed_atts=suppressed_atts,
        models=_models_from_spec(el, lang) if kind == 'element' else [],
    )


def _models_from_spec(el: etree._Element, lang: str) -> list[ModelView]:
    return [
        _model_view(child, lang)
        for child in el
        if localname(child) in MODEL_TAGS
    ]


def _model_view(el: etree._Element, lang: str) -> ModelView:
    from opm.odd_compiler.codegen import _serialize_template_content

    params = [
        ModelParam(name=p.get('name') or '', value=p.get('value'))
        for p in el
        if localname(p) == 'param'
    ]
    template = None
    for child in el:
        if child.tag == f'{{{PB_NS}}}template' or localname(child) == 'template':
            template = _serialize_template_content(child).strip() or None
            break
    renditions = [
        (r.get('scope'), ''.join(r.itertext()).strip())
        for r in el
        if localname(r) == 'outputRendition'
    ]
    return ModelView(
        kind=localname(el),
        behaviour=el.get('behaviour'),
        predicate=el.get('predicate'),
        output=el.get('output'),
        css_class=el.get('cssClass'),
        use=el.get('use'),
        desc=pick_lang(_children(el, 'desc'), lang),
        params=params,
        template=template,
        renditions=renditions,
        children=[
            _model_view(child, lang)
            for child in el
            if localname(child) in MODEL_TAGS
        ],
    )


def iter_canonical_specs(root: etree._Element):
    """Yield schema specs, skipping examples embedded in ``egXML``."""
    for tag, kind in SPEC_TAGS.items():
        for el in root.iter(qn(tag)):
            if _inside_egxml(el):
                continue
            if el.get('mode') == 'delete':
                continue
            yield el, kind


def _collect_specs(
    root: etree._Element, *, lang: str
) -> tuple[dict[str, Spec], dict[str, Spec]]:
    """Referenceable specs by ident, and ``moduleSpec``s by ident.

    Modules are kept in a dict of their own because module idents are a
    separate namespace: ``moduleRef/@key`` names a module, while
    ``elementRef`` / ``classRef`` / ``macroRef`` / ``dataRef`` name the rest.
    TEI does reuse one name across both — ``certainty`` is an element *and*
    the module that declares it — so a single dict keyed on ident alone drops
    whichever of the two is indexed second.

    Within either namespace a repeated ident is still possible (a merged ODD
    can carry more than one copy of a spec), and there the copy carrying
    ``@module`` wins as the canonical one.
    """
    merged: dict[str, Spec] = {}
    modules: dict[str, Spec] = {}
    for el, kind in iter_canonical_specs(root):
        spec = _spec_from_element(el, kind, lang)
        if spec is None:
            continue
        target = modules if kind == 'module' else merged
        previous = target.get(spec.ident)
        if previous is None or (spec.module and not previous.module):
            target[spec.ident] = spec
    return merged, modules


def _collect_chapter_anchors(root: etree._Element) -> dict[str, str]:
    """Map every ``xml:id`` under a chapter to that chapter's id.

    A chapter is a top-level division of front, body or back — the pages
    ``opm odd document`` writes one per. A customization's tree holds only its
    own chapters, TEI's staying out of its site, so pointers into TEI's prose
    find no entry here and stay external.
    """
    from opm.odd_schema import iter_guideline_chapters

    anchors: dict[str, str] = {}
    for div in iter_guideline_chapters(root):
        chapter = div.get(XML_ID)
        if not chapter:
            continue
        anchors[chapter] = chapter
        for el in div.iter():
            xml_id = el.get(XML_ID)
            if xml_id:
                anchors.setdefault(xml_id, chapter)
    return anchors


def _document_title(root: etree._Element) -> str:
    for path in (
        f'.//{qn("teiHeader")}/{qn("fileDesc")}/{qn("titleStmt")}/{qn("title")}',
        f'.//{qn("schemaSpec")}',
    ):
        el = root.find(path)
        if el is not None:
            if localname(el) == 'schemaSpec':
                return el.get('ident') or ''
            text = ''.join(el.itertext()).strip()
            if text:
                return text.split('\n')[0].strip()
    return ''
