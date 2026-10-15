# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""EPUB-oriented HTML serialisation (``ext-epub.xql`` equivalent).

Extends web HTML with EPUB 3 semantics: synthetic fragment ids, pagebreak
markers, and footnote asides linked by ``epub:type="noteref"``.
"""

from __future__ import annotations

import re

from lxml import etree

from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.output_functions import (
    PMResult,
    XML_ID,
    add_lang_attrs,
    classes,
    is_lemma_range_note,
    lemma_range_markers,
    normalize,
    note_for_anchor,
    param_str,
)

EPUB_NS = 'http://www.idpf.org/2007/ops'
EPUB_TYPE = f'{{{EPUB_NS}}}type'

# Elements that force a degraded web component to become a <div> rather than a <span>.
BLOCK_TAGS = frozenset({
    'address', 'blockquote', 'div', 'dl', 'figure', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'hr', 'ol', 'p', 'pre', 'section', 'table', 'ul',
})


def _epub_safe_id(node, config) -> str:
    """Stable-enough id for TOC / footnote links within one transform run."""
    existing = node.get(XML_ID) if node is not None else None
    if existing:
        return re.sub(r'[^A-Za-z0-9_-]', '_', existing)
    # Prefixed so a synthetic id cannot collide with the source's own: TEI
    # notes are commonly ``n1``, ``n2``, … which a bare ``n{counter}`` repeats.
    return f'opm-n{config.state.next_id()}'


def _footnote_body(config, node, content, marker: str | None = None) -> etree._Element:
    """Wrap footnote content so popover styling can target a plain class.

    Register entries (person, place, …) get their own ``output="epub"`` models
    in the ODD (see ``teipublisher.odd``): a ``<p class="fn-title">`` instead
    of the register page's own ``<h1>``, which would otherwise read as a
    spurious chapter opening to a reading system's heading-based navigation.
    """
    body = etree.Element('div')
    body.set('class', 'fn-body')
    if marker:
        # The note's own number or letter, so the footnotes section at the end
        # of a chapter (and a reader's popup) shows which callout it answers.
        num = etree.SubElement(body, 'span')
        num.set('class', 'fn-number')
        num.text = marker
        num.tail = ' '
    if content is not None:
        config.apply_children(config, node, content, body)
    return body


class EpubOutputFunctions(HtmlOutputFunctions):
    """Serialise to HTML with EPUB 3 structural semantics.

    Equivalent to the ``pmf:*`` overrides in ``ext-epub.xql``. Packaging into a
    ``.epub`` ZIP is handled separately by `opm.epub`.
    """

    def block(self, config, node, cls, content) -> PMResult:
        el = self._el('div', cls, node)
        # Always ensure a fragment id (synthetic when ``xml:id`` is absent).
        if node is not None and node.get(XML_ID):
            el.set('id', node.get(XML_ID))
        else:
            el.set('id', _epub_safe_id(node, config))
        config.apply_children(config, node, content, el)
        return [el]

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        kind = (type or '').lower()
        if kind == 'page':
            parts = ['pagebreak'] + list(cls)
            el = etree.Element('span', nsmap={'epub': EPUB_NS})
            el.set('class', classes(*parts))
            el.set(EPUB_TYPE, 'pagebreak')
            if label is not None and not isinstance(label, (list, tuple)):
                text = str(label).strip()
                el.set('id', f'page{re.sub(r"[^A-Za-z0-9_-]", "_", text)}')
                el.text = text
            else:
                el.set('id', f'page{_epub_safe_id(node, config)}')
                # XQuery wraps applied content in ``[...]``.
                el.text = '['
                config.apply_children(config, node, content if content is not None else [], el)
                if len(el):
                    el[-1].tail = (el[-1].tail or '') + ']'
                else:
                    el.text = (el.text or '') + ']'
            return [el]
        return super().break_(config, node, cls, content, type=type, label=label)

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        """Emit an EPUB noteref + footnote aside (in-flow; packager may hoist).

        Labels and lemma ranges follow
        [`HtmlOutputFunctions.note`][opm.runtime.html_output_functions.HtmlOutputFunctions.note]:
        a note carrying its own ``@n`` shows that label and leaves the running
        number alone, and a range reads ``a-`` … ``-a`` in the text and ``a-a``
        on the note. The label is kept as ``data-n`` so a stylesheet can set the
        two series apart.
        """
        label_s = param_str(label) or None
        place_s = param_str(place) or None
        if place_s == 'start':
            return self._lemma_range_start(config, node, cls, label_s)
        # A lookup that found neither content nor a label is not a note.
        if not label_s and isinstance(content, (list, tuple)) and not content:
            return []

        range_note = bool(label_s) and is_lemma_range_note(node)
        if label_s:
            if range_note:
                _start, ref_marker, fn_marker = lemma_range_markers(label_s)
            else:
                ref_marker = fn_marker = label_s
        else:
            ref_marker = fn_marker = str(config.state.next_note())
        fn_id = _epub_safe_id(node, config)

        ref = etree.Element('a', nsmap={'epub': EPUB_NS})
        ref.set(EPUB_TYPE, 'noteref')
        ref.set('href', f'#fn{fn_id}')
        ref.set('class', 'noteref')
        ref.text = ref_marker

        aside = etree.Element('aside', nsmap={'epub': EPUB_NS})
        aside.set(EPUB_TYPE, 'footnote')
        aside.set('id', f'fn{fn_id}')
        aside.set('class', classes('note', *cls))
        if label_s:
            for el in (ref, aside):
                el.set('data-n', label_s)
                if range_note:
                    el.set('data-range', 'end')
        add_lang_attrs(aside, node)
        aside.append(_footnote_body(config, node, content, fn_marker))
        return [ref, aside]

    def _lemma_range_start(self, config, node, cls, label_s: str | None) -> PMResult:
        """Opening marker of a lemma range (``a-``), linking to the end note."""
        if not label_s:
            return []
        start_marker, _end, _fn = lemma_range_markers(label_s)
        end_note = note_for_anchor(node)
        target = end_note if end_note is not None else node
        ref = etree.Element('a', nsmap={'epub': EPUB_NS})
        ref.set(EPUB_TYPE, 'noteref')
        ref.set('href', f'#fn{_epub_safe_id(target, config)}')
        ref.set('class', classes('noteref', *cls, 'note-range-start'))
        ref.set('data-n', label_s)
        ref.set('data-range', 'start')
        ref.text = start_marker
        return [ref]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        """Default reading as noteref; alternate body as footnote aside.

        An alternate that adds nothing — empty, or only the default reading
        again, as a register reference does when no register is configured —
        stays plain text: a popup repeating the word just tapped is noise.
        """
        _ = content, optional
        body = _footnote_body(config, node, alternate)
        shown = self._el('span', cls, node)
        config.apply_children(config, node, default, shown)
        extra = ' '.join(''.join(body.itertext()).split())
        if not extra or extra == ' '.join(''.join(shown.itertext()).split()):
            return [shown]

        fn_id = _epub_safe_id(node, config)
        ref = etree.Element('a', nsmap={'epub': EPUB_NS})
        ref.set(EPUB_TYPE, 'noteref')
        ref.set('href', f'#fn{fn_id}')
        ref.set('class', classes('alternate', *cls))
        ref.text = shown.text
        for child in list(shown):
            ref.append(child)

        aside = etree.Element('aside', nsmap={'epub': EPUB_NS})
        aside.set(EPUB_TYPE, 'footnote')
        aside.set('id', f'fn{fn_id}')
        aside.set('class', classes('altcontent', *cls))
        aside.append(body)
        return [ref, aside]

    def webcomponent(self, config, node, cls, content, name, optional=None) -> PMResult:
        """Degrade custom elements: EPUB 3 XHTML has no place for them.

        ``pb-link`` keeps its cross-reference as a fragment link (rewritten to
        the target chapter file during packaging); everything else becomes a
        transparent ``div`` / ``span`` wrapper.
        """
        opts = optional or {}
        if name == 'pb-code-highlight':
            return super().webcomponent(config, node, cls, content, name, optional)

        if name == 'pb-link':
            target = opts.get('xml-id') or opts.get('xml_id')
            if target:
                a = self._el('a', cls, node)
                a.set('href', f'#{target}')
                config.apply_children(config, node, content, a)
                return [a]

        el = self._el('div', cls, node)
        xml_id = node.get(XML_ID)
        if xml_id:
            el.set('id', xml_id)
        config.apply_children(config, node, content, el)
        if not any(
            isinstance(child.tag, str) and etree.QName(child).localname in BLOCK_TAGS
            for child in el
        ):
            el.tag = 'span'
        return [el]

    def cells(self, config, node, cls, content) -> PMResult:
        """Wrap each content item as a ``<td>`` inside a ``<tr>`` (``ext-epub``)."""
        tr = etree.Element('tr')
        for item in normalize(content):
            td = etree.SubElement(tr, 'td')
            td.set('class', classes(*cls))
            config.apply_children(config, node, item, td)
        return [tr]
