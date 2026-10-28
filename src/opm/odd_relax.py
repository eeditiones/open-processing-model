# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Translate a compiled ODD into RELAX NG, as the TEI Stylesheets' odd2relax does.

Expects the output of [`compiled_odd`][opm.odd_schema.compiled_odd]: one
``schemaSpec`` with every selected spec already merged (no ``moduleRef``,
``@source``, or ``@mode`` left to resolve). The translation follows what the
TEI Stylesheets do in
``odds/odd2relax.xsl``, ``odds/teiodds.xsl`` and ``odds/classatts.xsl``.

* **Names.** Each element, macro or class becomes a ``define`` named from its
  ident, with the spec's ``@prefix`` or the ``schemaSpec``'s. A model class is
  a ``choice`` of its members (``notAllowed`` if empty). An attribute class
  becomes ``<class>.attributes``, with parent-class refs and one
  ``<class>.attribute.<ident>`` per attribute.
* **Attributes.** An element refs its classes' ``.attributes`` patterns.
  If its ``attList`` overrides a class attribute, that class is expanded
  attribute by attribute and the override is merged in.
* **Content.** ODD content maps to RELAX NG: ``sequence`` → ``group`` (or
  ``list`` when it holds only ``dataRef``), ``alternate`` → ``choice``,
  ``@minOccurs`` / ``@maxOccurs`` → repetition patterns, ``classRef/@expand``
  → the class members, ``anyElement`` → its own pattern. Datatypes are
  written inline; embedded RELAX NG in ``content`` is copied through.
* **Clean-up.** Refs to specs the schema omits are dropped, along with empty
  patterns and unreachable definitions.

Does not embed Schematron (``constraintSpec``), and skips Guidelines chapters
cited by ``listRef``.
"""

from __future__ import annotations

from copy import deepcopy

from lxml import etree

from opm.spec_index import TEI_NS, SpecIndex, _inside_egxml, localname, qn

RNG_NS = 'http://relaxng.org/ns/structure/1.0'
A_NS = 'http://relaxng.org/ns/compatibility/annotations/1.0'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
EX_NS = 'http://www.tei-c.org/ns/Examples'
XSD_DATATYPES = 'http://www.w3.org/2001/XMLSchema-datatypes'

#: Repetitions beyond this are written as zeroOrMore, as the Stylesheets' $maxint.
_MAXINT = 400
#: The variants a model class can be expanded to, which name lookups strip.
_EXPANSIONS = ('sequenceOptionalRepeatable', 'sequenceOptional', 'sequenceRepeatable', 'sequence', 'alternation')
#: Patterns that hold other patterns and mean nothing without them.
_REPEATS = {'optional', 'zeroOrMore', 'oneOrMore'}
_GROUPS = {'choice', 'group', 'interleave'}


def rng(tag: str, **attrs: str) -> etree._Element:
    return etree.Element(f'{{{RNG_NS}}}{tag}', **attrs)


def _sub(parent: etree._Element, tag: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f'{{{RNG_NS}}}{tag}', **attrs)


def _is_rng(el: etree._Element, name: str | None = None) -> bool:
    if not isinstance(el.tag, str):
        return False
    q = etree.QName(el)
    return q.namespace == RNG_NS and (name is None or q.localname == name)


def _is_tei(el: etree._Element, name: str | None = None) -> bool:
    if not isinstance(el.tag, str):
        return False
    q = etree.QName(el)
    return q.namespace == TEI_NS and (name is None or q.localname == name)


def _tei_children(el: etree._Element, name: str) -> list[etree._Element]:
    return [c for c in el if _is_tei(c, name)]


def _tei_child(el: etree._Element, name: str) -> etree._Element | None:
    for c in el:
        if _is_tei(c, name):
            return c
    return None


def _norm(text: str) -> str:
    return ' '.join(text.split())


def _occurrences(el: etree._Element) -> tuple[int, int]:
    """``@minOccurs`` and ``@maxOccurs``, both defaulting to 1; -1 is unbounded."""
    low = int((el.get('minOccurs') or '1').strip() or 1)
    high_raw = (el.get('maxOccurs') or '1').strip() or '1'
    high = -1 if high_raw == 'unbounded' else int(high_raw)
    if high != -1 and high < low:
        raise ValueError(f'minOccurs {low} exceeds maxOccurs {high} on <{localname(el)}>')
    return low, high


def _wrapper(low: int, high: int) -> str:
    """The pattern for ``low`` to ``high`` occurrences when there is one."""
    return {(0, 1): 'optional', (0, -1): 'zeroOrMore', (1, -1): 'oneOrMore'}.get((low, high), '')


def _repeat(patterns: list[etree._Element], low: int, high: int) -> list[etree._Element]:
    """*patterns*, ``low`` to ``high`` times: the Stylesheets' repeat_as_needed."""
    if (low, high) == (1, 1):
        return patterns
    wrap = _wrapper(low, high)
    if wrap:
        outer = rng(wrap)
        outer.extend(deepcopy(p) for p in patterns)
        return [outer]
    out = [deepcopy(p) for _ in range(min(low, _MAXINT)) for p in patterns]
    if high == -1:
        tail = rng('zeroOrMore')
        tail.extend(deepcopy(p) for p in patterns)
        out.append(tail)
    else:
        for _ in range(low, high):
            tail = rng('optional')
            tail.extend(deepcopy(p) for p in patterns)
            out.append(tail)
    return out


def _ref_repeat(patterns: list[etree._Element], low: int, high: int) -> list[etree._Element]:
    """A reference repeated, nesting the optional ones so the result stays deterministic."""
    if (low, high) == (1, 1) or _wrapper(low, high) or not patterns:
        return _repeat(patterns, low, high)
    group = rng('group')
    for _ in range(min(low, _MAXINT)):
        group.extend(deepcopy(p) for p in patterns)
    count = high - low
    if high == -1 or count >= _MAXINT:
        tail = _sub(group, 'zeroOrMore')
        tail.extend(deepcopy(p) for p in patterns)
    else:
        parent = group
        for _ in range(count):
            parent = _sub(parent, 'optional')
            parent.extend(deepcopy(p) for p in patterns)
    return [group]


class _Translator:
    """One compiled ODD on its way to a ``grammar``."""

    def __init__(self, tree: etree._Element) -> None:
        self.schema = _main_schema_spec(tree)
        self.index = SpecIndex.from_tree(tree)
        attrs = dict(self.schema.attrib) if self.schema is not None else {}
        self.prefix = attrs.get('prefix') or ''
        self.ns = attrs.get('ns') or TEI_NS
        self.lang = attrs.get('docLang') or 'en'
        self.default_exceptions = attrs.get('defaultExceptions') or f'{TEI_NS} teix:egXML'
        self.defines: dict[str, etree._Element] = {}
        # Keyed by the element itself: holding it keeps lxml handing back the same proxy.
        self.any_elements: dict[etree._Element, str] = {}
        self._number_any_elements(tree)

    # ── names ──────────────────────────────────────────────────────────

    def spec_prefix(self, spec_el: etree._Element) -> str:
        own = spec_el.get('prefix')
        return own if own is not None else self.prefix

    def ref_name(self, name: str) -> str:
        """The Stylesheets' generateRefPrefix: a known ident behind its prefix."""
        lookup = name
        for suffix in _EXPANSIONS:
            if lookup.endswith('_' + suffix):
                lookup = lookup[: -len(suffix) - 1]
                break
        spec = self.index.get(lookup)
        if spec is None:
            return name
        prefix = self.spec_prefix(spec.node)
        if prefix and name.startswith(prefix):
            return _ncname(name)
        return _ncname(prefix + name)

    # ── documentation ──────────────────────────────────────────────────

    def _pick(self, el: etree._Element, name: str) -> etree._Element | None:
        """The ``gloss`` or ``desc`` in the documentation language, else the unlabelled or English one."""
        candidates = [
            c for c in _tei_children(el, name)
            if not (name == 'desc' and c.get('type') == 'deprecationInfo')
        ]
        if not candidates:
            return None
        if len(candidates) == 1 and not candidates[0].get(f'{{{XML_NS}}}lang'):
            return candidates[0]
        for lang in (self.lang, None, 'en'):
            for c in candidates:
                if c.get(f'{{{XML_NS}}}lang') == lang:
                    return c
        return None

    def description(self, el: etree._Element) -> str:
        """``(gloss) desc``, and for an open or semi-open list its sample values."""
        parts: list[str] = []
        gloss = self._pick(el, 'gloss')
        if gloss is not None and _text(gloss):
            parts.append(f'({_text(gloss)})')
        desc = self._pick(el, 'desc')
        if desc is not None and _text(desc):
            parts.append(_text(desc))
        text = ' '.join(parts)
        val_list = _tei_child(el, 'valList')
        if val_list is not None and val_list.get('type') in ('open', 'semi'):
            items = _tei_children(val_list, 'valItem')
            label = 'Sample' if val_list.get('type') == 'open' else 'Suggested'
            entries = []
            for n, item in enumerate(items, 1):
                item_gloss = self._pick(item, 'gloss')
                gloss_text = f' ({_text(item_gloss)})' if item_gloss is not None and _text(item_gloss) else ''
                entries.append(f'{n}] {_value_name(item)}{gloss_text}')
            if entries:
                text += f'\n{label} values include: ' + '; '.join(entries)
        return text

    def documentation(self, el: etree._Element) -> etree._Element | None:
        text = self.description(el)
        if not text:
            return None
        doc = etree.Element(f'{{{A_NS}}}documentation')
        doc.text = text
        return doc

    # ── content models ─────────────────────────────────────────────────

    def particles(self, el: etree._Element, restriction: str | None = None) -> list[etree._Element]:
        """The patterns one Pure ODD (or embedded RELAX NG) node stands for."""
        if not isinstance(el.tag, str):
            return []
        if _is_rng(el):
            return [self.copy_rng(el)]
        if not _is_tei(el):
            return []
        tag = localname(el)
        if tag in ('elementRef', 'classRef', 'macroRef'):
            return self.reference(el)
        if tag in ('sequence', 'interleave'):
            inner = [p for child in el for p in self.particles(child)]
            if not inner:
                return []
            data_only = all(_is_tei(c, 'dataRef') for c in el if isinstance(c.tag, str))
            if el.get('preserveOrder') == 'false' or tag == 'interleave':
                interleave = rng('interleave')
                interleave.extend(inner)
                inner = [interleave]
            outer = rng('list' if data_only else 'group')
            outer.extend(_repeat(inner, *_occurrences(el)))
            return [outer]
        if tag == 'alternate':
            choice = rng('choice')
            choice.extend(p for child in el for p in self.particles(child))
            return _repeat([choice], *_occurrences(el))
        if tag == 'textNode':
            return [rng('text')]
        if tag == 'empty':
            return [rng('empty')]
        if tag == 'anyElement':
            name = self.any_elements.get(el)
            if not name:
                return []
            return _repeat([rng('ref', name=name)], *_occurrences(el))
        if tag == 'dataRef':
            return self.data_ref(el, restriction)
        if tag == 'valList':
            return [self.values(el)] if _tei_children(el, 'valItem') else []
        return []

    def reference(self, el: etree._Element) -> list[etree._Element]:
        """``elementRef`` / ``classRef`` / ``macroRef``, expanded and repeated."""
        key = el.get('key') or ''
        expand = el.get('expand')
        include = (el.get('include') or '').split()
        exclude = (el.get('except') or '').split()
        if localname(el) == 'classRef' and (expand or include or exclude):
            members = [
                m for m in self._class_members(key)
                if (m.get('ident') in include if include else m.get('ident') not in exclude)
            ]
            refs = [p for m in members for p in self.class_member(m, key, expand)]
            if expand in ('sequence', 'sequenceOptional', 'sequenceRepeatable', 'sequenceOptionalRepeatable'):
                wrap = {
                    'sequenceOptional': 'optional',
                    'sequenceRepeatable': 'oneOrMore',
                    'sequenceOptionalRepeatable': 'zeroOrMore',
                }.get(expand)
                if wrap:
                    refs = [_wrapped(wrap, [r]) for r in refs]
                patterns = refs
            else:
                choice = rng('choice')
                choice.extend(refs)
                patterns = [choice]
        else:
            patterns = [rng('ref', name=self.ref_name(key))]
        return _ref_repeat(patterns, *_occurrences(el))

    def _class_members(self, key: str) -> list[etree._Element]:
        return [
            spec.node
            for ref in self.index.members_of(key)
            if (spec := self.index.get(ref.ident)) is not None and spec.kind in ('element', 'class')
        ]

    def class_member(self, member: etree._Element, cls: str, expand: str | None) -> list[etree._Element]:
        """A member in its class's pattern: a class by (expanded) name, an element by
        its ``memberOf/@min`` and ``@max``."""
        name = self.spec_prefix(member) + (member.get('ident') or '')
        if localname(member) == 'classSpec':
            return [rng('ref', name=name if not expand or expand == 'NULL' else f'{name}_{expand}')]
        low, high = 1, 1
        classes = _tei_child(member, 'classes')
        for m in _tei_children(classes, 'memberOf') if classes is not None else []:
            if m.get('key') == cls:
                low = int(m.get('min')) if (m.get('min') or '').isdigit() else 1
                high_raw = m.get('max') or ''
                high = -1 if high_raw == 'unbounded' else int(high_raw) if high_raw.isdigit() else 1
        out = [rng('ref', name=name) for _ in range(low)]
        if high == -1:
            out.append(_wrapped('zeroOrMore', [rng('ref', name=name)]))
        else:
            out.extend(_wrapped('optional', [rng('ref', name=name)]) for _ in range(low, high))
        return out

    def data_ref(self, el: etree._Element, restriction: str | None) -> list[etree._Element]:
        """A datatype: ``data`` for an XSD name, the ``dataSpec``'s own content for a key."""
        restriction = el.get('restriction') or restriction
        if el.get('name'):
            data = rng('data', type=el.get('name') or '')
            facets = _tei_children(el, 'dataFacet')
            if facets:
                for facet in facets:
                    param = _sub(data, 'param', name=facet.get('name') or '')
                    param.text = facet.get('value') or ''
            elif restriction:
                _sub(data, 'param', name='pattern').text = restriction
            return [data]
        spec = self.index.get(el.get('key') or '')
        if spec is None:
            return []
        if spec.content is None:
            # A dataSpec may hold its valList directly rather than inside content.
            val_list = _tei_child(spec.node, 'valList')
            return [self.values(val_list)] if val_list is not None and _tei_children(val_list, 'valItem') else []
        return [p for child in spec.content for p in self.particles(child, restriction)]

    def values(self, val_list: etree._Element) -> etree._Element:
        """A ``choice`` of a ``valList``'s values, each followed by its documentation."""
        choice = rng('choice')
        for item in _tei_children(val_list, 'valItem'):
            _sub(choice, 'value').text = _value_name(item)
            doc = self.documentation(item)
            choice.append(doc if doc is not None else etree.Element(f'{{{A_NS}}}documentation'))
        return choice

    def copy_rng(self, el: etree._Element) -> etree._Element:
        """Embedded RELAX NG, its references behind their prefixes, its TEI translated.

        A prefixed name (``mei:mdiv``) is bound where it stands in the ODD, not in
        the grammar, so it moves to ``@ns`` and a local name.
        """
        tag = localname(el)
        out = etree.Element(f'{{{RNG_NS}}}{tag}', dict(el.attrib))
        if tag == 'ref' and el.get('name'):
            out.set('name', self.ref_name(el.get('name') or ''))
        elif tag in ('element', 'attribute') and ':' in (el.get('name') or ''):
            _unprefix(el, el.get('name') or '', lambda local, ns: (out.set('name', local), out.set('ns', ns)))
        out.text = el.text if tag in ('value', 'param', 'name', 'nsName') else None
        if tag == 'name' and ':' in (el.text or ''):
            _unprefix(el, el.text.strip(), lambda local, ns: (setattr(out, 'text', local), out.set('ns', ns)))
        for child in el:
            if _is_tei(child):
                out.extend(self.particles(child))
            elif isinstance(child.tag, str):
                out.append(self.copy_rng(child) if _is_rng(child) else deepcopy(child))
        return out

    def content(self, spec_el: etree._Element) -> list[etree._Element]:
        """An element's or macro's content model (the Stylesheets' defineContent)."""
        val_list = _tei_child(spec_el, 'valList')
        if val_list is not None and val_list.get('type') == 'closed':
            return [self.values(val_list)]
        content = _tei_child(spec_el, 'content')
        if content is None:
            return []
        return [p for child in content for p in self.particles(child)]

    # ── attributes ─────────────────────────────────────────────────────

    def attribute(self, att_def: etree._Element) -> etree._Element:
        """One ``attDef``: optional unless required, documented, its values typed."""
        alt = _tei_child(att_def, 'altIdent')
        ident = att_def.get('ident') or ''
        name = _norm(alt.text or '') if alt is not None and alt.text else ident
        if att_def.get('ns') == XML_NS and not name.startswith('xml:'):
            name = 'xml:' + name
        attribute = rng('attribute', name=name)
        if att_def.get('ns'):
            attribute.set('ns', att_def.get('ns') or '')
        default = _tei_child(att_def, 'defaultVal')
        if default is not None and _text(default):
            attribute.set(f'{{{A_NS}}}defaultValue', _text(default))
        doc = self.documentation(att_def)
        if doc is not None:
            attribute.append(doc)
        datatype = _tei_child(att_def, 'datatype')
        low, high = _occurrences(datatype) if datatype is not None else (1, 1)
        data = self.attribute_data(att_def)
        if (low, high) == (0, 1):
            attribute.append(_wrapped('optional', data))
        elif datatype is None or high == 1 or any(_is_rng(c, 'text') for c in datatype):
            attribute.extend(data)
        else:
            # Several values, space-separated.
            _sub(attribute, 'list').extend(_repeat(data, low, high))
        if att_def.get('usage') == 'req':
            return attribute
        return _wrapped('optional', [attribute])

    def attribute_data(self, att_def: etree._Element) -> list[etree._Element]:
        """The value of an attribute: its closed or semi-open list, else its datatype, else text."""
        val_list = _tei_child(att_def, 'valList')
        datatype = _tei_child(att_def, 'datatype')
        typed = [p for c in datatype for p in self.particles(c)] if datatype is not None else []
        if val_list is not None and val_list.get('type') == 'closed':
            return [self.values(val_list)]
        if val_list is not None and val_list.get('type') == 'semi':
            choice = self.values(val_list)
            choice.extend(typed or [rng('data', type='Name')])
            return [choice]
        return typed or [rng('text')]

    def class_attributes(self, cls: etree._Element) -> list[tuple[str, etree._Element]]:
        """``(class, attDef)`` for every attribute *cls* has, its own first, then
        its parent classes' (the Stylesheets' classAttributes)."""
        out: list[tuple[str, etree._Element]] = []
        seen: set[str] = set()

        def walk(spec_el: etree._Element) -> None:
            ident = spec_el.get('ident') or ''
            if ident in seen:
                return
            seen.add(ident)
            att_list = _tei_child(spec_el, 'attList')
            if att_list is not None:
                for att in att_list.iter(qn('attDef')):
                    if att.get('mode') != 'delete':
                        out.append((ident, att))
            for key in self._att_class_keys(spec_el):
                walk(self.index.require(key).node)

        walk(cls)
        return out

    def _att_class_keys(self, spec_el: etree._Element) -> list[str]:
        classes = _tei_child(spec_el, 'classes')
        keys = [m.get('key') or '' for m in _tei_children(classes, 'memberOf')] if classes is not None else []
        return [
            k for k in keys
            if (spec := self.index.get(k)) is not None and spec.is_att_class
        ]

    def element_attributes(self, spec_el: etree._Element) -> list[etree._Element]:
        """An element's attributes: its classes' patterns, spelled out where it
        overrides one of their attributes, then its own (classatts.xsl)."""
        att_list = _tei_child(spec_el, 'attList')
        own = list(att_list.iter(qn('attDef'))) if att_list is not None else []
        overrides: dict[str, etree._Element] = {}
        for att in own:
            overrides.setdefault(att.get('ident') or '', att)
        out: list[etree._Element] = []
        encountered: set[str] = set()
        for key in self._att_class_keys(spec_el):
            cls = self.index.require(key).node
            inherited = self.class_attributes(cls)
            if not any(att.get('ident') in overrides for _owner, att in inherited):
                out.append(rng('ref', name=f'{self.spec_prefix(cls)}{key}.attributes'))
                continue
            for owner, att in inherited:
                ident = att.get('ident') or ''
                encountered.add(ident)
                change = overrides.get(ident)
                if change is None:
                    owner_el = self.index.require(owner).node
                    out.append(rng('ref', name=f'{self.spec_prefix(owner_el)}{owner}.attribute.{ident.replace(":", "")}'))
                elif change.get('mode') == 'delete':
                    continue
                elif change.get('mode') in (None, 'replace'):
                    out.append(self.attribute(change))
                else:
                    out.append(self.attribute(_merge_attribute(att, change)))
        if att_list is not None:
            out.extend(self._own_attributes(att_list, encountered))
        return out

    def _own_attributes(self, att_list: etree._Element, encountered: set[str]) -> list[etree._Element]:
        out: list[etree._Element] = []
        for child in att_list:
            if _is_tei(child, 'attDef'):
                ident = child.get('ident') or ''
                mode = child.get('mode')
                if ident in encountered or ident.startswith('xmlns'):
                    continue
                if mode in ('change', 'delete'):
                    continue
                out.append(self.attribute(child))
            elif _is_tei(child, 'attRef'):
                out.extend(self.att_ref(child))
            elif _is_tei(child, 'attList'):
                inner = self._own_attributes(child, encountered)
                if not inner:
                    continue
                if child.get('org') == 'choice':
                    out.append(_wrapped('choice', inner))
                elif att_list.get('org') == 'choice':
                    out.append(_wrapped('group', inner))
                else:
                    out.extend(inner)
        if att_list.get('org') == 'choice' and localname(att_list.getparent()) != 'attList' and out:
            return [_wrapped('choice', out)]
        return out

    def att_ref(self, att_ref: etree._Element) -> list[etree._Element]:
        cls_key = att_ref.get('class')
        name = att_ref.get('name') or att_ref.get('key')
        if cls_key:
            cls = self.index.get(cls_key)
            if cls is None:
                return []
            prefix = self.spec_prefix(cls.node)
            if name:
                return [rng('ref', name=f'{prefix}{cls_key}.attribute.{name.replace(":", "")}')]
            return [rng('ref', name=f'{prefix}{cls_key}.attributes')]
        return [rng('ref', name=name)] if name else []

    # ── specs ──────────────────────────────────────────────────────────

    def define(self, name: str, patterns: list[etree._Element]) -> None:
        define = rng('define', name=name)
        define.extend(patterns)
        self.defines[name] = define

    def element_spec(self, spec_el: etree._Element) -> None:
        name = _ncname(self.spec_prefix(spec_el) + (spec_el.get('ident') or ''))
        content = _tei_child(spec_el, 'content')
        if content is not None and any(_is_rng(c, 'notAllowed') for c in content):
            self.define(name, [rng('notAllowed')])
            return
        alt = _tei_child(spec_el, 'altIdent')
        element = rng('element', name=_norm(alt.text or '') if alt is not None and alt.text else spec_el.get('ident') or '')
        if spec_el.get('ns'):
            element.set('ns', spec_el.get('ns') or '')
        elif ':' in (element.get('name') or ''):
            _unprefix(spec_el, element.get('name') or '', lambda local, ns: (element.set('name', local), element.set('ns', ns)))
        doc = self.documentation(spec_el)
        if doc is not None:
            element.append(doc)
        element.extend(self.content(spec_el) or [rng('empty')])
        element.extend(self.element_attributes(spec_el))
        self.define(name, [element])

    def model_class(self, spec_el: etree._Element) -> None:
        ident = spec_el.get('ident') or ''
        name = self.spec_prefix(spec_el) + ident
        members = self._class_members(ident)
        if not members:
            self.define(name, [rng('notAllowed')])
        else:
            self.define(name, [_wrapped('choice', [p for m in members for p in self.class_member(m, ident, None)])])
        # The expansions a content model may name; those nothing names are pruned.
        for expand in _EXPANSIONS:
            variant = f'{name}_{expand}'
            if not members:
                empty = expand.startswith('sequence') and expand != 'sequenceRepeatable'
                self.define(variant, [rng('empty' if empty else 'notAllowed')])
                continue
            refs = [p for m in members for p in self.class_member(m, ident, expand)]
            wrap = {'sequenceOptional': 'optional', 'sequenceRepeatable': 'oneOrMore',
                    'sequenceOptionalRepeatable': 'zeroOrMore'}.get(expand)
            if expand == 'alternation':
                self.define(variant, [_wrapped('choice', refs)])
            else:
                self.define(variant, [_wrapped(wrap, [r]) for r in refs] if wrap else refs)

    def att_class(self, spec_el: etree._Element) -> None:
        ident = spec_el.get('ident') or ''
        name = self.spec_prefix(spec_el) + ident
        refs = [
            rng('ref', name=f'{self.spec_prefix(self.index.require(k).node)}{k}.attributes')
            for k in self._att_class_keys(spec_el)
        ]
        att_list = _tei_child(spec_el, 'attList')
        atts = [
            a for a in (att_list.iter(qn('attDef')) if att_list is not None else [])
            if a.get('mode') != 'delete' and not (a.get('ident') or '').startswith('xmlns')
        ]
        refs.extend(rng('ref', name=f'{name}.attribute.{(a.get("ident") or "").replace(":", "")}') for a in atts)
        if att_list is not None:
            for att_ref in att_list.iter(qn('attRef')):
                refs.extend(self.att_ref(att_ref))
        self.define(f'{name}.attributes', refs or [rng('empty')])
        for att in atts:
            self.define(f'{name}.attribute.{(att.get("ident") or "").replace(":", "")}', [self.attribute(att)])

    def macro(self, spec_el: etree._Element) -> None:
        """A ``macroSpec`` or ``dataSpec``; several bare RELAX NG children are a choice."""
        name = self.spec_prefix(spec_el) + (spec_el.get('ident') or '')
        patterns = self.content(spec_el)
        content = _tei_child(spec_el, 'content')
        bare = content is not None and any(_is_rng(c, 'text') or _is_rng(c, 'ref') for c in content)
        if not patterns:
            patterns = [rng('empty')]
        elif len(patterns) > 1 and bare:
            patterns = [_wrapped('choice', patterns)]
        self.define(name, patterns)

    def any_element(self, el: etree._Element, name: str) -> None:
        except_ = rng('except')
        for token in dict.fromkeys((el.get('exclude') or self.default_exceptions).split()):
            if token == 'teix:egXML':
                _sub(except_, 'name', ns=EX_NS).text = 'egXML'
            elif ':' in token and not token.startswith(('http:', 'https:', 'urn:')):
                prefix, local = token.split(':', 1)
                uri = el.nsmap.get(prefix)
                if uri:
                    _sub(except_, 'name', ns=uri).text = local
                else:
                    _sub(except_, 'nsName', ns=token)
            else:
                _sub(except_, 'nsName', ns=token)
        element = rng('element')
        any_name = _sub(element, 'anyName')
        any_name.append(except_)
        _sub(_sub(element, 'zeroOrMore'), 'attribute').append(rng('anyName'))
        choice = _sub(_sub(element, 'zeroOrMore'), 'choice')
        _sub(choice, 'text')
        _sub(choice, 'ref', name=name)
        self.define(name, [element])

    def _number_any_elements(self, tree: etree._Element) -> None:
        found = [el for el in tree.iter(qn('anyElement')) if not _inside_egxml(el)]
        width = len(str(len(found)))
        for n, el in enumerate(found, 1):
            spec = next((a for a in el.iterancestors() if localname(a) in ('elementSpec', 'macroSpec')), None)
            owner = spec.get('ident') if spec is not None else ''
            self.any_elements[el] = f'anyElement_{owner}_{n:0{width}d}'

    # ── the grammar ────────────────────────────────────────────────────

    def grammar(self) -> etree._Element:
        specs = self.index.all()
        for spec in specs:
            if spec.kind in ('macro', 'datatype'):
                self.macro(spec.node)
        for spec_el in (s.node for s in specs):
            for any_el in spec_el.iter(qn('anyElement')):
                name = self.any_elements.get(any_el)
                if name:
                    self.any_element(any_el, name)
        for spec in specs:
            if spec.kind == 'element':
                self.element_spec(spec.node)
            elif spec.is_model_class:
                self.model_class(spec.node)
            elif spec.is_att_class:
                self.att_class(spec.node)
        start = self.start()

        for define in self.defines.values():
            _tidy(define, set(self.defines))
        keep = self._reachable(start)

        grammar = etree.Element(
            f'{{{RNG_NS}}}grammar',
            nsmap={None: RNG_NS, 'a': A_NS},
            ns=self.ns,
            datatypeLibrary=XSD_DATATYPES,
        )
        if start is not None:
            grammar.append(start)
        for name, define in self.defines.items():
            if name in keep:
                grammar.append(define)
        return grammar

    def start(self) -> etree._Element | None:
        """``@start``, else ``TEI`` (and ``teiCorpus`` when the schema has it); none for ``start=""``."""
        tokens = self.schema.get('start') if self.schema is not None else None
        if tokens is not None and not tokens.strip():
            return None
        if tokens is None:
            tokens = 'TEI teiCorpus' if self.index.get('teiCorpus') else 'TEI'
        names = []
        for token in tokens.split():
            for candidate in (token, self.prefix + token):
                if candidate in self.defines:
                    names.append(candidate)
                    break
        if not names:
            return None
        return _wrapped('start', [_wrapped('choice', [rng('ref', name=n) for n in names])])

    def _reachable(self, start: etree._Element | None) -> set[str]:
        """The definitions kept, as the Stylesheets' passes 2 and 4 keep them: those
        some reference names, and of those, the elements and what the rest still name."""

        def named(names: set[str]) -> set[str]:
            refs = {r.get('name') or '' for n in names for r in self.defines[n].iter(f'{{{RNG_NS}}}ref')}
            if start is not None:
                refs.update(r.get('name') or '' for r in start.iter(f'{{{RNG_NS}}}ref'))
            return refs

        first = set(self.defines) & named(set(self.defines))
        still = named(first)
        return {
            name for name in first
            if name in still or any(_is_rng(c, 'element') for c in self.defines[name])
        }


def _wrapped(tag: str, patterns: list[etree._Element]) -> etree._Element:
    outer = rng(tag)
    outer.extend(patterns)
    return outer


def _text(el: etree._Element) -> str:
    """The plain text of documentation: ``<gi>`` as ``<x>``, ``<att>`` as ``@x``,
    ``<code>`` and ``<tag>`` in backticks. A ``gloss`` is its bare text, as the Stylesheets take it."""
    if localname(el) == 'gloss':
        return _norm(''.join(el.itertext()))
    return _norm(_marked(el))


def _marked(el: etree._Element) -> str:
    parts: list[str] = [el.text or '']
    for child in el:
        if isinstance(child.tag, str):
            name = localname(child)
            if name == 'gi':
                parts.append(f'<{_norm(_marked(child))}>')
            elif name == 'att':
                parts.append(f'@{_norm(_marked(child))}')
            elif name == 'code':
                parts.append(f'`{_marked(child)}`')
            elif name == 'tag':
                parts.append(f'`<{_marked(child)}>`')
            else:
                parts.append(_marked(child))
        parts.append(child.tail or '')
    return ''.join(parts)


def _ncname(name: str) -> str:
    """A define name for an ident such as ``mei:mdiv``, which may not hold a colon."""
    return name.replace(':', '_')


def _unprefix(el: etree._Element, qname: str, apply) -> None:
    """Call *apply* with the local name and namespace of *qname* as *el* binds its
    prefix; ``xml:`` stays as it is, since every grammar binds it."""
    prefix, local = qname.split(':', 1)
    uri = el.nsmap.get(prefix)
    if prefix != 'xml' and uri:
        apply(local, uri)


def _value_name(item: etree._Element) -> str:
    alt = _tei_child(item, 'altIdent')
    if alt is not None and alt.text and _norm(alt.text) != item.get('ident'):
        return _norm(alt.text)
    return item.get('ident') or ''


def _merge_attribute(old: etree._Element, new: etree._Element) -> etree._Element:
    """A class attribute with an element's change to it laid over (mergeClassAttribute)."""
    merged = etree.Element(qn('attDef'), ident=old.get('ident') or '')
    usage = new.get('usage') or old.get('usage')
    if usage:
        merged.set('usage', usage)
    if old.get('ns'):
        merged.set('ns', old.get('ns') or '')
    for name in ('altIdent',):
        for child in _tei_children(new, name):
            merged.append(deepcopy(child))
    for name in ('equiv', 'gloss', 'desc', 'datatype', 'defaultVal'):
        source = new if _tei_children(new, name) else old
        for child in _tei_children(source, name):
            merged.append(deepcopy(child))
    val_list = _merge_val_list(_tei_child(old, 'valList'), _tei_child(new, 'valList'))
    if val_list is not None:
        merged.append(val_list)
    return merged


def _merge_val_list(old: etree._Element | None, new: etree._Element | None) -> etree._Element | None:
    if new is None:
        return deepcopy(old) if old is not None else None
    mode = new.get('mode')
    if mode == 'delete':
        return None
    if mode in (None, 'add', 'replace') or old is None:
        out = etree.Element(qn('valList'))
        for name in ('type', 'repeatable'):
            if new.get(name):
                out.set(name, new.get(name) or '')
        out.extend(deepcopy(c) for c in _tei_children(new, 'valItem'))
        return out
    out = deepcopy(old)
    for name, value in new.attrib.items():
        if name != 'mode':
            out.set(name, value)
    changes = {item.get('ident'): item for item in _tei_children(new, 'valItem')}
    for item in _tei_children(out, 'valItem'):
        change = changes.get(item.get('ident'))
        if change is None:
            continue
        if change.get('mode') in ('delete', 'replace'):
            out.remove(item)
            continue
        for name in ('equiv', 'gloss', 'desc'):
            if _tei_children(change, name):
                for old_child in _tei_children(item, name):
                    item.remove(old_child)
                item.extend(deepcopy(c) for c in _tei_children(change, name))
    known = {item.get('ident') for item in _tei_children(out, 'valItem')}
    for item in _tei_children(new, 'valItem'):
        if item.get('mode') == 'replace' or (item.get('mode') in (None, 'add') and item.get('ident') not in known):
            added = deepcopy(item)
            added.attrib.pop('mode', None)
            out.append(added)
    return out


def _tidy(el: etree._Element, defined: set[str]) -> None:
    """Drop references to what is not defined, and the patterns they leave empty
    (the Stylesheets' passes 2 to 4)."""
    for child in list(el):
        if not _is_rng(child):
            continue
        _tidy(child, defined)
        tag = localname(child)
        patterns = [c for c in child if _is_rng(c)]
        if tag == 'ref' and child.get('name') not in defined:
            el.remove(child)
        elif tag in _REPEATS and (not patterns or all(_is_rng(c, 'empty') for c in patterns)):
            el.remove(child)
        elif tag in _GROUPS and not patterns:
            _replace(el, child, rng('empty'))
        elif tag == 'group' and len(patterns) == 1 and len(child) == 1:
            _replace(el, child, patterns[0])
        elif tag == 'list' and not patterns:
            _replace(el, child, rng('text'))
    if _is_rng(el, 'element') or _is_rng(el, 'define'):
        patterns = [c for c in el if _is_rng(c) and localname(c) not in ('anyName', 'name', 'nsName')]
        if not patterns:
            el.append(rng('empty'))


def _replace(parent: etree._Element, old: etree._Element, new: etree._Element) -> None:
    new.tail = old.tail
    parent.replace(old, new)


def _main_schema_spec(root: etree._Element) -> etree._Element | None:
    for el in root.iter(qn('schemaSpec')):
        if not _inside_egxml(el):
            return el
    return None


def odd_to_rng(tree: etree._Element) -> etree._Element:
    """The RELAX NG ``grammar`` for the compiled ODD *tree*."""
    return _Translator(tree).grammar()
