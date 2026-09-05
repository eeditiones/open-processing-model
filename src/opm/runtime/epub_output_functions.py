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
    normalize,
)

EPUB_NS = 'http://www.idpf.org/2007/ops'
EPUB_TYPE = f'{{{EPUB_NS}}}type'

# Elements that force a degraded web component to become a <div> rather than a <span>.
BLOCK_TAGS = frozenset({
    'address', 'blockquote', 'div', 'dl', 'figure', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'hr', 'ol', 'p', 'pre', 'section', 'table', 'ul',
})


def _epub_safe_id(node, config: dict) -> str:
    """Stable-enough id for TOC / footnote links within one transform run."""
    existing = node.get(XML_ID) if node is not None else None
    if existing:
        return re.sub(r'[^A-Za-z0-9_-]', '_', existing)
    counter = config.setdefault('_epub_id_counter', 0) + 1
    config['_epub_id_counter'] = counter
    return f'n{counter}'


def _footnote_body(config: dict, node, content) -> etree._Element:
    """Wrap footnote content so popover styling can target a plain class.

    Register entries (person, place, …) get their own ``output="epub"`` models
    in the ODD (see ``teipublisher.odd``): a ``<p class="fn-title">`` instead
    of the register page's own ``<h1>``, which would otherwise read as a
    spurious chapter opening to a reading system's heading-based navigation.
    """
    body = etree.Element('div')
    body.set('class', 'fn-body')
    if content is not None:
        config['apply_children'](config, node, content, body)
    return body


class EpubOutputFunctions(HtmlOutputFunctions):
    """Serialise to HTML with EPUB 3 structural semantics.

    Equivalent to the ``pmf:*`` overrides in ``ext-epub.xql``. Packaging into a
    ``.epub`` ZIP is handled separately by :mod:`opm.epub`.
    """

    def block(self, config, node, cls, content) -> PMResult:
        el = self._el('div', cls, node)
        # Always ensure a fragment id (synthetic when ``xml:id`` is absent).
        if node is not None and node.get(XML_ID):
            el.set('id', node.get(XML_ID))
        else:
            el.set('id', _epub_safe_id(node, config))
        config['apply_children'](config, node, content, el)
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
                config['apply_children'](config, node, content if content is not None else [], el)
                if len(el):
                    el[-1].tail = (el[-1].tail or '') + ']'
                else:
                    el.text = (el.text or '') + ']'
            return [el]
        return super().break_(config, node, cls, content, type=type, label=label)

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        """Emit an EPUB noteref + footnote aside (in-flow; packager may hoist)."""
        from . import output_functions as of

        _ = place, label
        of._note_counter += 1
        fn_id = _epub_safe_id(node, config)
        nr = of._note_counter

        ref = etree.Element('a', nsmap={'epub': EPUB_NS})
        ref.set(EPUB_TYPE, 'noteref')
        ref.set('href', f'#fn{fn_id}')
        ref.set('class', 'noteref')
        ref.text = str(nr)

        aside = etree.Element('aside', nsmap={'epub': EPUB_NS})
        aside.set(EPUB_TYPE, 'footnote')
        aside.set('id', f'fn{fn_id}')
        aside.set('class', classes('note', *cls))
        add_lang_attrs(aside, node)
        aside.append(_footnote_body(config, node, content))
        return [ref, aside]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        """Default reading as noteref; alternate body as footnote aside."""
        _ = content, optional
        fn_id = _epub_safe_id(node, config)

        ref = etree.Element('a', nsmap={'epub': EPUB_NS})
        ref.set(EPUB_TYPE, 'noteref')
        ref.set('href', f'#fn{fn_id}')
        ref.set('class', classes('alternate', *cls))
        config['apply_children'](config, node, default, ref)

        aside = etree.Element('aside', nsmap={'epub': EPUB_NS})
        aside.set(EPUB_TYPE, 'footnote')
        aside.set('id', f'fn{fn_id}')
        aside.set('class', classes('altcontent', *cls))
        aside.append(_footnote_body(config, node, alternate))
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
                config['apply_children'](config, node, content, a)
                return [a]

        el = self._el('div', cls, node)
        xml_id = node.get(XML_ID)
        if xml_id:
            el.set('id', xml_id)
        config['apply_children'](config, node, content, el)
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
            config['apply_children'](config, node, item, td)
        return [tr]
