"""HTML5 serialisation for the TEI processing model (``html-functions.xql`` equivalent)."""

from __future__ import annotations

import re
from lxml import etree

from opm.runtime.output_functions import (
    PMResult,
    TEI_NS,
    XLINK_HREF,
    XML_ID,
    ProcessingModelFunctions,
    add_lang_attrs,
    apply_pb_template,
    classes,
    normalize,
    child_nodes,
)


class HtmlOutputFunctions(ProcessingModelFunctions):
    """Serialise to HTML5 using lxml elements.

    Equivalent to the ``pmf:*`` functions in ``html-functions.xql``.
    """

    def finish(self, config, nodes: list) -> list:
        """HTML pipeline has no ``pmf:finish`` normalisation; return *nodes* unchanged."""
        return nodes

    @staticmethod
    def _el(tag, cls, node):
        """Create an element with a class attribute and language attributes."""
        el = etree.Element(tag)
        el.set('class', classes(*cls))
        add_lang_attrs(el, node)
        return el

    def block(self, config, node, cls, content) -> PMResult:
        el = self._el('div', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def inline(self, config, node, cls, content) -> PMResult:
        el = self._el('span', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def paragraph(self, config, node, cls, content) -> PMResult:
        el = self._el('p', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def heading(self, config, node, cls, content, level) -> PMResult:
        try:
            lvl = int(level) if level is not None else 1
        except (TypeError, ValueError):
            lvl = 1
        el = self._el(f'h{max(1, min(6, lvl))}', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def section(self, config, node, cls, content) -> PMResult:
        el = self._el('section', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def body(self, config, node, cls, content) -> PMResult:
        el = self._el('body', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    @staticmethod
    def _append_style_once(head_el: etree._Element, css: str | None) -> None:
        if not css:
            return
        for child in head_el.findall('style'):
            if (child.text or '') == css:
                return
        st = etree.SubElement(head_el, 'style')
        st.set('type', 'text/css')
        st.text = css

    def _append_odd_css(self, config, head_el: etree._Element) -> None:
        self._append_style_once(head_el, config.get('odd_css'))

    def document(self, config, node, cls, content) -> PMResult:
        el = self._el('html', cls, node)
        # Create proper HTML structure with head and body
        head = etree.Element('head')
        meta = etree.SubElement(head, 'meta')
        meta.set('charset', 'utf-8')
        el.append(head)
        body = etree.SubElement(el, 'body')
        config['apply_children'](config, node, content, body)
        odd_css = config.get('odd_css')
        if odd_css:
            self._append_odd_css(config, head)
        return [el]

    def pass_through(self, config, node, cls, content) -> PMResult:
        """Render content without adding a wrapper element."""
        result = []
        for item in normalize(content):
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, etree._Element):
                sub = (config['apply'](config, child_nodes(node))
                       if item is node
                       else config['apply'](config, [item]))
                result.extend(sub)
        return result

    NSMAP = {'tei': TEI_NS}

    def list(self, config, node, cls, content, type=None) -> PMResult:
        # Output <dl> if node has tei:label children, else <ul>/<ol>
        if node.xpath('tei:label', namespaces=self.NSMAP):
            el = self._el('dl', cls, node)
            config['apply_children'](config, node, content, el)
            return [el]
        effective = type or node.get('type')
        tag = 'ol' if effective == 'ordered' else 'ul'
        el = self._el(tag, cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
        # Output <dt>/<dd> if parent has labels and this item has a preceding label
        parent = node.getparent()
        if parent is not None and parent.xpath('tei:label', namespaces=self.NSMAP):
            label = node.xpath('preceding-sibling::*[1][self::tei:label]', namespaces=self.NSMAP)
            if label or n is not None:
                dt = self._el('dt', cls, node)
                if label:
                    config['apply_children'](config, label[0], [label[0]], dt)
                elif n is not None:
                    dt.text = str(n)
                dd = self._el('dd', cls, node)
                config['apply_children'](config, node, content, dd)
                return [dt, dd]
        el = self._el('li', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def link(self, config, node, cls, content, uri, target, optional) -> PMResult:
        if isinstance(uri, etree._Element):
            href = uri.get(XLINK_HREF)
        else:
            href = uri
        el = etree.Element('a')
        el.set('class', classes(*cls))
        if href:
            el.set('href', str(href))
        if target:
            el.set('target', str(target))
        add_lang_attrs(el, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def table(self, config, node, cls, content) -> PMResult:
        el = self._el('table', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def row(self, config, node, cls, content) -> PMResult:
        el = self._el('tr', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def cell(self, config, node, cls, content, type=None) -> PMResult:
        el = etree.Element('th' if type == 'head' else 'td')
        el.set('class', classes(*cls))
        if node.get('cols'):
            el.set('colspan', node.get('cols'))
        if node.get('rows'):
            el.set('rowspan', node.get('rows'))
        add_lang_attrs(el, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def figure(self, config, node, cls, content, title=None) -> PMResult:
        el = etree.Element('figure')
        el.set('class', classes(*cls))
        config['apply_children'](config, node, content, el)
        if title:
            cap = etree.SubElement(el, 'figcaption')
            add_lang_attrs(cap, node)
            config['apply_children'](config, node, title, cap)
        return [el]

    def graphic(self, config, node, cls, content, url,
                width, height, scale, title) -> PMResult:
        _ = content
        el = etree.Element('img')
        el.set('class', classes(*cls))
        if isinstance(url, etree._Element):
            href = url.get(XLINK_HREF)
        else:
            href = str(url) if url else None
        if href:
            el.set('src', href)
        style = '; '.join(filter(None, [
            f'width: {width}'   if width  else None,
            f'height: {height}' if height else None,
            f'scale: {scale}'   if scale  else None,
        ]))
        if style:
            el.set('style', style)
        xml_id = node.get(XML_ID)
        if xml_id:
            el.set('id', xml_id)
        return [el]

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        """Emit note - margin notes as inline spans, others as footnotes."""
        from . import output_functions as of

        node_id = node.get(XML_ID) or node.get('id') or str(of._note_counter + 1)
        safe_id = re.sub(r'[-.]', '_', node_id)

        # Margin notes: output inline span(s), not footnotes
        if place == 'margin':
            result = []
            if label:
                # Label reference span
                ref_span = self._el('span', list(cls) + ['margin-note-ref'], node)
                config['apply_children'](config, node, [label], ref_span)
                result.append(ref_span)
                # Margin note content with label
                note_span = self._el('span', list(cls) + ['margin-note'], node)
                n_span = etree.SubElement(note_span, 'span')
                n_span.set('class', 'n')
                n_span.text = label if isinstance(label, str) else str(label)
                n_span.tail = ' '
                config['apply_children'](config, node, content, note_span)
                result.append(note_span)
            else:
                # Margin note without label
                note_span = self._el('span', list(cls) + ['margin-note'], node)
                note_span.set('id', f'margin_ref_{safe_id}')
                config['apply_children'](config, node, content, note_span)
                result.append(note_span)
            return result

        # Footnote handling (default)
        of._note_counter += 1
        nr = label if label is not None else of._note_counter

        ref_span = etree.Element('span')
        ref_span.set('id', f'fnref_{safe_id}')
        ref_span.set('style', 'display:inline-block')
        ref_span.set('class', classes(*cls))
        a = etree.SubElement(ref_span, 'a')
        a.set('class', 'note')
        a.set('rel', 'footnote')
        a.set('href', f'#fn_{safe_id}')
        a.text = str(nr)

        dl = etree.Element('dl')
        dl.set('class', 'footnote')
        dl.set('id', f'fn_{safe_id}')
        dt = etree.SubElement(dl, 'dt')
        dt.set('class', 'fn-number')
        dt.text = str(nr)
        dd = etree.SubElement(dl, 'dd')
        dd.set('class', 'fn-content')
        add_lang_attrs(dd, node)
        config['apply_children'](config, node, content, dd)
        back = etree.SubElement(dd, 'a')
        back.set('class', 'fn-back')
        back.set('href', f'#fnref_{safe_id}')
        back.text = '↩'

        config.setdefault('footnotes', []).append(dl)
        return [ref_span]

    def cit(self, config, node, cls, content, source=None) -> PMResult:
        el = self._el('blockquote', cls, node)
        config['apply_children'](config, node, content, el)
        if source:
            cite = etree.SubElement(el, 'cite')
            config['apply_children'](config, node, source, cite)
        return [el]

    def webcomponent(self, config, node, cls, content, name, optional=None) -> PMResult:
        el = etree.Element(name)
        el.set('class', classes(*cls))
        xml_id = node.get(XML_ID)
        if xml_id:
            el.set('id', xml_id)
        for k, v in (optional or {}).items():
            if isinstance(v, bool):
                if v:
                    el.set(k, k)
            else:
                el.set(k, str(v))
        config['apply_children'](config, node, content, el)
        return [el]

    def omit(self, config, node, cls, content) -> PMResult:
        return []

    def index(self, config, node, cls, content, type=None) -> PMResult:
        return []

    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult:
        if (type or '').lower() == 'page':
            el = self._el('span', cls, node)
            config['apply_children'](config, node, label if label is not None else [], el)
            return [el]
        br = etree.Element('br')
        br.set('class', classes(*cls))
        return [br]

    def anchor(self, config, node, cls, content, id=None) -> PMResult:
        el = etree.Element('span')
        if id:
            el.set('id', str(id))
        el.set('class', classes(*cls))
        add_lang_attrs(el, node)
        return [el]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        if config.get('webcomponents'):
            outer = etree.Element('pb-popover')
            if cls:
                outer.set('class', classes(*cls))
            d = etree.SubElement(outer, 'span')
            d.set('slot', 'default')
            config['apply_children'](config, node, default, d)
            if alternate is not None:
                a = etree.SubElement(outer, 'template')
                a.set('slot', 'alternate')
                config['apply_children'](config, node, alternate, a)
            return [outer]
        alt_parts = list(cls) + ['alternate'] if cls is not None else ['alternate']
        outer = self._el('span', alt_parts, node)
        d = etree.SubElement(outer, 'span')
        config['apply_children'](config, node, default, d)
        if alternate is not None:
            a = etree.SubElement(outer, 'span')
            a.set('class', 'altcontent')
            config['apply_children'](config, node, alternate, a)
        return [outer]

    def glyph(self, config, node, cls, content) -> PMResult:
        if content == 'char:EOLhyphen':
            return ['\u00ad']
        return []

    def text(self, config, node, cls, content) -> PMResult:
        out = []
        for item in normalize(content):
            if isinstance(item, str):
                out.append(item)
            else:
                out.append(str(item))
        return out

    def metadata(self, config, node, cls, content) -> PMResult:
        el = etree.Element('head')
        el.set('class', classes(*cls))
        title_el = node.find(f'.//{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title')
        if title_el is None:
            title_el = node.find('.//fileDesc/titleStmt/title')
        t = etree.SubElement(el, 'title')
        if title_el is not None:
            t.text = ''.join(title_el.itertext())
        meta = etree.SubElement(el, 'meta')
        meta.set('charset', 'utf-8')
        return [el]

    def title(self, config, node, cls, content) -> PMResult:
        el = etree.Element('title')
        el.set('class', classes(*cls))
        add_lang_attrs(el, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def match(self, config, node, cls, content) -> PMResult:
        el = etree.Element('mark')
        el.set('class', classes(*cls))
        add_lang_attrs(el, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def template(self, config, node, cls, template_str: str, params: dict) -> PMResult:
        return apply_pb_template(template_str, params, config)
