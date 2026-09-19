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

from lxml import etree

TEI_NS = 'http://www.tei-c.org/ns/1.0'
PB_NS = 'http://teipublisher.com/1.0'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
EX_NS = 'http://www.tei-c.org/ns/Examples'
OPM_NS = 'http://teipublisher.com/opm/1.0'
#: Marks a node that ``opm odd document`` publishes as its own page, and says
#: which kind. Written by the site builder onto a copy of the compiled tree,
#: never by an ODD author — it is a namespace of our own precisely so that it
#: cannot collide with the document's ``@type``, which stays as authored.
OPM_PAGE = f'{{{OPM_NS}}}page'
#: Values ``@opm:page`` takes. ``chapter`` is prose from the document; the
#: rest are stub ``div``s the site builder injects.
PAGE_CHAPTER = 'chapter'
PAGE_HOME = 'home'
PAGE_CATALOG = 'catalog'
PAGE_ATTS = 'atts'
#: Injected stubs, as opposed to chapters that came from the document.
INJECTED_PAGES = frozenset({PAGE_HOME, PAGE_CATALOG, PAGE_ATTS})

_PARSER = etree.XMLParser(collect_ids=False, remove_comments=True)

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
    node: etree._Element
    gloss: etree._Element | None
    desc: etree._Element | None
    remarks: etree._Element | None
    exempla: list[etree._Element]
    content: etree._Element | None
    constraints: list[etree._Element]
    list_refs: list[str]
    member_of_keys: list[str]
    local_atts: list[AttDefView]
    suppressed_atts: set[str] = field(default_factory=set)
    models: list[ModelView] = field(default_factory=list)
    contained_by: list[SpecRef] = field(default_factory=list)
    may_contain: list[SpecRef] = field(default_factory=list)
    members: list[SpecRef] = field(default_factory=list)
    used_by: list[SpecRef] = field(default_factory=list)
    attribute_tree: list[AttClassView] = field(default_factory=list)

    @property
    def href(self) -> str:
        return f'ref-{self.ident}.html'

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
        """Group *refs* by module, with character-data last."""
        buckets: dict[str, list[SpecRef]] = {}
        order: list[str] = []
        for ref in refs:
            key = 'Character data' if ref.is_text else (ref.module or '')
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(ref)
        named = sorted((k for k in order if k != 'Character data'), key=str.lower)
        if 'Character data' in buckets:
            named.append('Character data')
        return [(k, buckets[k]) for k in named]


class SpecIndex:
    """Lookup table of specs plus precomputed membership / content relations."""

    def __init__(self, specs: dict[str, Spec], *, lang: str = 'en', title: str = ''):
        self._specs = specs
        self.lang = lang
        self.title = title
        self._compute_relations()

    @classmethod
    def from_tree(cls, root: etree._Element, *, lang: str = 'en', title: str = '') -> SpecIndex:
        specs = _collect_specs(root, lang=lang)
        if not title:
            title = _document_title(root) or 'ODD documentation'
        return cls(specs, lang=lang, title=title)

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
        return [s for s in self.all() if s.kind == 'module']

    def attributes(self) -> list[tuple[str, list[Spec]]]:
        """Attribute ident → specs (classes/elements) that define it, A–Z."""
        owners: dict[str, list[Spec]] = defaultdict(list)
        for spec in self.all():
            if spec.kind not in {'class', 'element'}:
                continue
            for att in spec.local_atts:
                owners[att.ident].append(spec)
        return sorted(owners.items(), key=lambda kv: kv[0].lower())

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
            for spec in self._specs.values():
                if current not in spec.member_of_keys:
                    continue
                if spec.kind == 'element':
                    out.append(self.ref(spec.ident))
                elif spec.kind == 'class':
                    stack.append(spec.ident)
        return _unique_refs(out)

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

    def _compute_relations(self) -> None:
        content_parents: dict[tuple[str, str], list[SpecRef]] = defaultdict(list)
        for spec in self._specs.values():
            if spec.content is None:
                continue
            for ref_kind, key in _content_refs(spec.content):
                content_parents[(ref_kind, key)].append(
                    SpecRef(ident=spec.ident, kind=spec.kind, module=spec.module)
                )

        for spec in self._specs.values():
            spec.members = _unique_refs([
                self.ref(other.ident)
                for other in self._specs.values()
                if spec.ident in other.member_of_keys
            ])
            spec.used_by = _unique_refs(content_parents.get(('class', spec.ident), [])
                                        + content_parents.get(('macro', spec.ident), [])
                                        + content_parents.get(('data', spec.ident), []))
            if spec.kind == 'element':
                spec.may_contain = self._expand_content(spec.content)
                spec.contained_by = self._contained_by(spec, content_parents)
                spec.attribute_tree = self._attribute_tree(spec)
            elif spec.is_att_class:
                spec.attribute_tree = self._attribute_tree(spec)
            elif spec.kind in {'macro', 'datatype'}:
                spec.may_contain = self._expand_content(spec.content)

    def _expand_content(self, content: etree._Element | None) -> list[SpecRef]:
        if content is None:
            return []
        return _unique_refs(self._walk_content(content, seen=set()))

    def _walk_content(self, el: etree._Element, seen: set[str]) -> list[SpecRef]:
        out: list[SpecRef] = []
        tag = localname(el)
        if tag == 'elementRef':
            key = el.get('key')
            if key:
                out.append(self.ref(key, kind='element'))
        elif tag == 'classRef':
            key = el.get('key')
            if key:
                out.extend(self.class_members_transitive(key))
        elif tag == 'macroRef':
            key = el.get('key')
            if key and key not in seen:
                seen.add(key)
                macro = self.get(key)
                if macro is not None and macro.content is not None:
                    out.extend(self._walk_content(macro.content, seen))
        elif tag == 'dataRef':
            key = el.get('key') or el.get('name')
            if key:
                out.append(self.ref(key, kind='datatype'))
        elif tag == 'textNode':
            out.append(SpecRef(ident=TEXT_IDENT, kind='text'))
        for child in el:
            out.extend(self._walk_content(child, seen))
        return out

    def _contained_by(
        self,
        spec: Spec,
        content_parents: dict[tuple[str, str], list[SpecRef]],
    ) -> list[SpecRef]:
        parents: list[SpecRef] = []
        parents.extend(content_parents.get(('element', spec.ident), []))
        classes = self.expand_model_ancestors(spec.model_classes)
        for cls in classes:
            parents.extend(content_parents.get(('class', cls), []))
        macros_to_chase = {spec.ident, *classes}
        for other in self._specs.values():
            if other.kind != 'macro' or other.content is None:
                continue
            refs = set(_content_refs(other.content))
            if any((kind, key) in refs for kind in ('class', 'element') for key in macros_to_chase):
                parents.extend(content_parents.get(('macro', other.ident), []))
        return [
            ref for ref in _unique_refs(parents)
            if ref.kind == 'element' and ref.ident != spec.ident
        ]

    def _attribute_tree(self, spec: Spec) -> list[AttClassView]:
        local_names = {a.ident for a in spec.local_atts}
        views = [
            self._att_class_view(key, local_names, spec.suppressed_atts)
            for key in spec.att_classes
        ]
        return [v for v in views if v is not None]

    def _att_class_view(
        self,
        ident: str,
        local_names: set[str],
        suppressed: set[str],
    ) -> AttClassView | None:
        spec = self.get(ident)
        if spec is None:
            return AttClassView(ident=ident)
        atts = [
            AttDefView(
                ident=a.ident,
                usage=a.usage,
                datatype=a.datatype,
                desc=a.desc,
                gloss=a.gloss,
                exemplum=a.exemplum,
                overridden=a.ident in local_names,
                node=a.node,
            )
            for a in spec.local_atts
            if a.ident not in suppressed
        ]
        nested = [
            view
            for key in spec.att_classes
            if (view := self._att_class_view(key, local_names, suppressed)) is not None
        ]
        return AttClassView(ident=ident, attributes=atts, nested=nested)


def _unique_refs(refs: list[SpecRef]) -> list[SpecRef]:
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
        gloss=pick_lang(_children(el, 'gloss'), lang),
        desc=pick_lang(_children(el, 'desc'), lang),
        remarks=pick_lang(_children(el, 'remarks'), lang),
        exempla=[
            ex for ex in _children(el, 'exemplum')
            if (ex.get(XML_LANG) or lang) == lang
        ] or _children(el, 'exemplum')[:1],
        content=_first(el, 'content'),
        constraints=_children(el, 'constraintSpec'),
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


def _collect_specs(root: etree._Element, *, lang: str) -> dict[str, Spec]:
    merged: dict[str, Spec] = {}
    for el, kind in iter_canonical_specs(root):
        spec = _spec_from_element(el, kind, lang)
        if spec is None:
            continue
        previous = merged.get(spec.ident)
        # Prefer the copy that carries @module (canonical Guidelines / p5subset).
        if previous is None or (spec.module and not previous.module):
            merged[spec.ident] = spec
    return merged


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
