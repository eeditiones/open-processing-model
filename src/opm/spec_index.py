# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""In-memory graph of TEI ODD specification elements.

This is the documentation counterpart of
[`opm.odd_compiler.parse_odd`][opm.odd_compiler.parse_odd]: that module merges
``elementSpec``s so they can be compiled, while this one indexes
``elementSpec`` / ``classSpec`` / ``macroSpec`` / ``dataSpec`` and inverts
their class memberships and content-model references, from which
[`opm.odd_expand`][opm.odd_expand] derives what the TEI Stylesheets show as
"Contained by", "May contain", "Members" and "Used by".

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

from opm.xml_parser import make_parser

TEI_NS = 'http://www.tei-c.org/ns/1.0'
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


def _children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if localname(c) == name]


def _first(el: etree._Element, name: str) -> etree._Element | None:
    for c in el:
        if localname(c) == name:
            return c
    return None


@dataclass(frozen=True)
class SpecRef:
    """A pointer to another spec, used in membership / content lists."""

    ident: str
    kind: str
    module: str | None = None

    @property
    def is_text(self) -> bool:
        return self.kind == 'text'


@dataclass
class AttDefView:
    """An attribute a spec declares itself."""

    ident: str
    node: etree._Element

    @property
    def anchor(self) -> str:
        return 'att-' + self.ident.replace(':', '-')


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

class SpecIndex:
    """The specs of a schema and the direct facts about them, indexed.

    The primitives: specs by ident, direct class memberships and content-model
    references, both inverted so that "who is a member of X" and "who refers
    to X" are lookups rather than scans, and the two graph walks everything
    else is built from. What those facts *mean* on a documentation page —
    contained-by, may-contain, used-by, attribute inheritance — is derived on
    top, in [`opm.odd_expand`][opm.odd_expand]. It is the counterpart of the
    indexes eXist gave the XQuery version of this code.
    """

    def __init__(
        self,
        specs: dict[str, Spec],
        *,
        lang: str = 'en',
        title: str = '',
    ):
        self._specs = specs
        self.lang = lang
        self.title = title
        self._build_lookups()

    def _build_lookups(self) -> None:
        """Invert memberships and content references once, for O(1) primitives."""
        self._members_of: dict[str, list[str]] = defaultdict(list)
        self._referrers: dict[tuple[str, str], list[SpecRef]] = defaultdict(list)
        self._content_refs: dict[str, list[tuple[str, str]]] = {}
        for spec in self._specs.values():
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
        specs = _collect_specs(root)
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

    def macros(self) -> list[Spec]:
        return [s for s in self.all() if s.kind == 'macro']

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


def _spec_from_element(el: etree._Element, kind: str) -> Spec | None:
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
            local_atts.append(AttDefView(ident=att_ident, node=a))
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


def _collect_specs(root: etree._Element) -> dict[str, Spec]:
    """Referenceable specs by ident.

    ``moduleSpec``s are left out: module idents are a namespace of their own
    (``certainty`` is an element *and* the module declaring it), and nothing
    refers to a module the way ``elementRef`` / ``classRef`` / ``macroRef`` /
    ``dataRef`` refer to the rest. A merged ODD can carry more than one copy
    of a spec; the copy carrying ``@module`` is the canonical one.
    """
    specs: dict[str, Spec] = {}
    for el, kind in iter_canonical_specs(root):
        if kind == 'module':
            continue
        spec = _spec_from_element(el, kind)
        if spec is None:
            continue
        previous = specs.get(spec.ident)
        if previous is None or (spec.module and not previous.module):
            specs[spec.ident] = spec
    return specs


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
