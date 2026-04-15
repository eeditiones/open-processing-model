"""
Output format abstraction for TEI transformation.

Equivalent to html-functions.xql (and sibling format modules) in
tei-publisher-lib/content.  Each concrete subclass of
:class:`ProcessingModelFunctions` implements a specific serialisation
target (HTML, Markdown, …).  The generated transformation module
calls methods on ``config['pmf']`` and never imports a format-specific
module directly.

Currently only HTML output is implemented (:class:`HtmlOutputFunctions`).
"""

import re
from abc import ABC, abstractmethod
from typing import Any

from lxml import etree

# ── Namespace constants ────────────────────────────────────────────────────────

XLINK_NS   = 'http://www.w3.org/1999/xlink'
MML_NS     = 'http://www.w3.org/1998/Math/MathML'
XML_NS     = 'http://www.w3.org/XML/1998/namespace'
XLINK_HREF = f'{{{XLINK_NS}}}href'
XML_LANG   = f'{{{XML_NS}}}lang'
XML_ID     = f'{{{XML_NS}}}id'
TEI_NS     = 'http://www.tei-c.org/ns/1.0'
PMResult = list[Any]

RTL_LANGUAGES = {
    "ar", "he", "kd", "fa", "ps", "ug", "ur", "yi",
    "ara", "heb", "syr", "syc", "kur", "fas", "per",
    "pus", "uig", "urd", "yid",
}

# ── Counters (equivalent to counters.xql) ─────────────────────────────────────

_note_counter = 0


def reset_counters():
    global _note_counter
    _note_counter = 0


# ── CSS helpers (equivalent to css.xql) ───────────────────────────────────────

def map_rend_to_class(node):
    """Map @rend attribute tokens to CSS class names, e.g. 'bold' → 'rend-bold'."""
    rend = node.get('rend')
    if rend:
        return ' '.join(f'rend-{r}' for r in rend.split())
    return None


def classes(*args):
    """Build a CSS class string, discarding None / empty entries."""
    return ' '.join(c for c in args if c)


# ── Language direction ─────────────────────────────────────────────────────────

def add_lang_attrs(el, source_node):
    """Copy @xml:lang from *source_node* as HTML lang/dir attributes on *el*."""
    lang = source_node.get(XML_LANG)
    if lang:
        base = lang.split('-')[0]
        el.set('lang', lang)
        el.set('dir', 'rtl' if base in RTL_LANGUAGES else 'ltr')


# ── Content normalisation (used by pass_through and apply_children) ────────────

def normalize(content):
    """Return content as a flat list of strings and lxml Elements."""
    if content is None:
        return []
    if isinstance(content, (str, etree._ElementUnicodeResult)):
        return [str(content)]
    if isinstance(content, etree._Element):
        return [content]
    return list(content)


def child_nodes(node):
    """All child content as a flat list of strings and elements.

    Equivalent to the XPath ``node()`` axis: preserves interleaved text and
    element children (including tail text of each child element).
    """
    result = []
    if node.text:
        result.append(node.text)
    for child in node:
        result.append(child)
        if child.tail:
            result.append(child.tail)
    return result


# ── Abstract base class ────────────────────────────────────────────────────────

class ProcessingModelFunctions(ABC):
    """Abstract base for output format implementations.

    Method names mirror the TEI Processing Model function vocabulary used by
    ``html-functions.xql`` / ``markdown-functions.xql`` etc.  The generated
    transformation module calls these methods via ``config['pmf']`` so that
    only the *config* construction needs to change
    when a different output format is required.

    Every method receives *config* as its first argument.  The config dict
    **must** carry the following callable entries so that output functions can
    delegate recursive processing without importing the dispatch module:

    ``config['apply']``            – ``apply(config, nodes) → list``
    ``config['apply_children']``   – ``apply_children(config, node, content,
                                       parent) → None``
    """

    @abstractmethod
    def block(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def inline(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def paragraph(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def heading(self, config, node, cls, content, level) -> PMResult: ...

    @abstractmethod
    def section(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def body(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def document(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def pass_through(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def list(self, config, node, cls, content, list_type=None) -> PMResult: ...

    @abstractmethod
    def list_item(self, config, node, cls, content, n=None) -> PMResult: ...

    @abstractmethod
    def link(self, config, node, cls, content, uri, target, optional) -> PMResult: ...

    @abstractmethod
    def table(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def row(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def cell(self, config, node, cls, content, cell_type=None) -> PMResult: ...

    @abstractmethod
    def figure(self, config, node, cls, content, title=None) -> PMResult: ...

    @abstractmethod
    def graphic(self, config, node, cls, content, url_node,
                width, height, scale, title) -> PMResult: ...

    @abstractmethod
    def note(self, config, node, cls, content, place=None, label=None) -> PMResult: ...

    @abstractmethod
    def cit(self, config, node, cls, content, source=None) -> PMResult: ...

    @abstractmethod
    def webcomponent(self, config, node, cls, content, name, optional=None) -> PMResult: ...

    @abstractmethod
    def omit(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def index(self, config, node, cls, content, index_type=None) -> PMResult: ...

    @abstractmethod
    def break_(self, config, node, cls, content, break_type=None, label=None) -> PMResult: ...

    @abstractmethod
    def anchor(self, config, node, cls, content, id=None) -> PMResult: ...

    @abstractmethod
    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult: ...

    @abstractmethod
    def glyph(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def text(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def metadata(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def title(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def match(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def template(self, config, node, cls, content) -> PMResult: ...


# ── HTML implementation (equivalent to html-functions.xql) ────────────────────

class HtmlOutputFunctions(ProcessingModelFunctions):
    """Serialise to HTML5 using lxml elements.

    Equivalent to the ``pmf:*`` functions in ``html-functions.xql``.
    """

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _el(tag, cls, node):
        """Create an element with a class attribute and language attributes."""
        el = etree.Element(tag)
        el.set('class', classes(*cls))
        add_lang_attrs(el, node)
        return el

    # ── ProcessingModelFunctions implementation ───────────────────────────────

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

    def _append_odd_css(self, config, head_el: etree._Element) -> None:
        css = config.get('odd_css')
        if not css:
            return
        st = etree.SubElement(head_el, 'style')
        st.set('type', 'text/css')
        st.text = css

    def document(self, config, node, cls, content) -> PMResult:
        el = self._el('html', cls, node)
        config['apply_children'](config, node, content, el)
        css = config.get('odd_css')
        if css and el.find('head') is None:
            head = etree.Element('head')
            self._append_odd_css(config, head)
            el.insert(0, head)
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

    def list(self, config, node, cls, content, list_type=None) -> PMResult:
        effective = list_type or node.get('type')
        tag = 'ol' if effective == 'ordered' else 'ul'
        el = self._el(tag, cls, node)
        config['apply_children'](config, node, content, el)
        return [el]

    def list_item(self, config, node, cls, content, n=None) -> PMResult:
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

    def cell(self, config, node, cls, content, cell_type=None) -> PMResult:
        el = etree.Element('th' if cell_type == 'head' else 'td')
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

    def graphic(self, config, node, cls, content, url_node,
                width, height, scale, title) -> PMResult:
        _ = content
        el = etree.Element('img')
        el.set('class', classes(*cls))
        href = url_node.get(XLINK_HREF) if url_node is not None else None
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
        """Emit inline call marker; append the ``dl.footnote`` body to ``config['footnotes']``."""
        global _note_counter
        _note_counter += 1
        nr = _note_counter

        node_id = node.get(XML_ID) or node.get('id') or str(nr)
        safe_id = re.sub(r'[-.]', '_', node_id)

        # Inline anchor
        ref_span = etree.Element('span')
        ref_span.set('id', f'fnref_{safe_id}')
        ref_span.set('style', 'display:inline-block')
        ref_span.set('class', classes(*cls))
        a = etree.SubElement(ref_span, 'a')
        a.set('class', 'note')
        a.set('rel', 'footnote')
        a.set('href', f'#fn_{safe_id}')
        a.text = str(nr)

        # Footnote body
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

    def index(self, config, node, cls, content, index_type=None) -> PMResult:
        return []

    def break_(self, config, node, cls, content, break_type=None, label=None) -> PMResult:
        if (break_type or '').lower() == 'page':
            el = self._el('span', cls, node)
            config['apply_children'](config, node, label or [], el)
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
        self._append_odd_css(config, el)
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

    def template(self, config, node, cls, content) -> PMResult:
        el = self._el('div', cls, node)
        config['apply_children'](config, node, content, el)
        return [el]
