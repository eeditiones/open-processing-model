"""
Output format abstraction for TEI transformation.

Equivalent to html-functions.xql (and sibling format modules) in
tei-publisher-lib/content.  Each concrete subclass of
:class:`ProcessingModelFunctions` implements a specific serialisation
target (HTML, Markdown, …).  The generated transformation module
calls methods on ``config['pmf']`` and never imports a format-specific
module directly.

HTML and Markdown implementations live in :mod:`tei_publisher_py.html_output_functions` and
:mod:`tei_publisher_py.markdown_output_functions`; they are re-exported here for convenience.
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
    # XPath atomics (number(), count unwrapped elsewhere, booleans) from ``xpath_content``
    if isinstance(content, (int, float, bool)):
        return [str(content)]
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


# ── pb:template runtime engine ────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r'\[\[\s*([\w-]+)\s*\]\]')


def _to_str_param(val) -> str:
    """Stringify a param value for use in attribute values or plain text nodes."""
    if val is None:
        return ''
    if isinstance(val, etree._Element):
        return etree.tostring(val, encoding='unicode')
    if isinstance(val, list):
        return ''.join(
            etree.tostring(v, encoding='unicode') if isinstance(v, etree._Element) else str(v)
            for v in val
        )
    return str(val)


def _substitute_node(el: etree._Element, params: dict) -> None:
    """Recursively substitute [[param]] in *el*'s attributes, text, and descendant tails."""
    for k, v in list(el.attrib.items()):
        if '[[' in v:
            el.set(k, _PLACEHOLDER_RE.sub(lambda m: _to_str_param(params.get(m.group(1))), v))
    if el.text and '[[' in el.text:
        _substitute_mixed(el, is_text=True, ref_child=None, params=params)
    for child in list(el):
        _substitute_node(child, params)
        if child.tail and '[[' in child.tail:
            _substitute_mixed(el, is_text=False, ref_child=child, params=params)


def _substitute_mixed(
    parent: etree._Element,
    is_text: bool,
    ref_child,
    params: dict,
) -> None:
    """Replace [[param]] in a text or tail node; inserts element-valued params into the tree."""
    text = parent.text if is_text else ref_child.tail
    parts = _PLACEHOLDER_RE.split(text)
    # parts: [literal0, name1, literal1, name2, literal2, ...]

    has_elements = any(
        isinstance(params.get(parts[i]), list)
        for i in range(1, len(parts), 2)
    )

    if not has_elements:
        result = _PLACEHOLDER_RE.sub(
            lambda m: _to_str_param(params.get(m.group(1))), text
        )
        if is_text:
            parent.text = result or None
        else:
            ref_child.tail = result or None
        return

    # Mixed case: some params are element lists — splice them into the tree.
    children = list(parent)
    if is_text:
        insert_idx = 0
        parent.text = parts[0] or None
    else:
        insert_idx = children.index(ref_child) + 1
        ref_child.tail = parts[0] or None

    last_inserted = None

    for i in range(1, len(parts), 2):
        name = parts[i]
        after = parts[i + 1] if i + 1 < len(parts) else ''
        val = params.get(name)

        if isinstance(val, list):
            for item in val:
                if isinstance(item, etree._Element):
                    item.tail = None
                    parent.insert(insert_idx, item)
                    insert_idx += 1
                    last_inserted = item
                elif isinstance(item, str) and item:
                    if last_inserted is not None:
                        last_inserted.tail = (last_inserted.tail or '') + item
                    elif is_text:
                        parent.text = (parent.text or '') + item
                    elif ref_child is not None:
                        ref_child.tail = (ref_child.tail or '') + item
            if last_inserted is not None:
                last_inserted.tail = (last_inserted.tail or '') + after
            elif is_text:
                parent.text = (parent.text or '') + after
            elif ref_child is not None:
                ref_child.tail = (ref_child.tail or '') + after
        else:
            s = _to_str_param(val) + after
            if last_inserted is not None:
                last_inserted.tail = (last_inserted.tail or '') + s
            elif is_text:
                parent.text = (parent.text or '') + s
            else:
                ref_child.tail = (ref_child.tail or '') + s


def apply_pb_template(template_str: str, params: dict, config: dict | None = None) -> list:
    """Execute a pb:template: parse *template_str* as XML, substitute [[param]] placeholders,
    and return the resulting list of nodes (strings and lxml Elements).

    *config* is accepted for API symmetry but not currently used; element-valued params that
    appear in text positions are inserted directly into the result tree (they are expected to be
    already-rendered output nodes, as ``content`` always is when generated by the ODD compiler).
    """
    wrapped = f'<__w__>{template_str}</__w__>'
    try:
        root = etree.fromstring(wrapped.encode('utf-8'))
    except etree.XMLSyntaxError:
        return []
    _substitute_node(root, params)
    result = []
    if root.text:
        result.append(root.text)
    for child in root:
        tail = child.tail
        child.tail = None
        result.append(child)
        if tail:
            result.append(tail)
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
    def list(self, config, node, cls, content, type=None) -> PMResult: ...

    @abstractmethod
    def list_item(self, config, node, cls, content, n=None) -> PMResult: ...

    @abstractmethod
    def link(self, config, node, cls, content, uri, target, optional) -> PMResult: ...

    @abstractmethod
    def table(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def row(self, config, node, cls, content) -> PMResult: ...

    @abstractmethod
    def cell(self, config, node, cls, content, type=None) -> PMResult: ...

    @abstractmethod
    def figure(self, config, node, cls, content, title=None) -> PMResult: ...

    @abstractmethod
    def graphic(self, config, node, cls, content, url,
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
    def index(self, config, node, cls, content, type=None) -> PMResult: ...

    @abstractmethod
    def break_(self, config, node, cls, content, type=None, label=None) -> PMResult: ...

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
    def template(self, config, node, cls, template_str: str, params: dict) -> PMResult: ...

    def code(self, config, node, cls, content, language=None) -> PMResult:
        """Fallback code behaviour for output modes without dedicated formatting."""
        _ = language
        return self.pass_through(config, node, cls, content)

    def finish(self, config, nodes: list) -> list:
        """Post-process output after :func:`~tei_publisher_py.pm_runtime.apply`, before footnotes.

        Equivalent to ``pmf:finish`` in ``markdown-functions.xql`` / HTML siblings.
        Default: return *nodes* unchanged.
        """
        return nodes


from tei_publisher_py.html_output_functions import HtmlOutputFunctions
from tei_publisher_py.markdown_output_functions import MarkdownOutputFunctions

__all__ = [
    'HtmlOutputFunctions',
    'MarkdownOutputFunctions',
    'ProcessingModelFunctions',
    'PMResult',
    'TEI_NS',
    'XML_ID',
    'XLINK_HREF',
    'child_nodes',
    'normalize',
    'reset_counters',
    'map_rend_to_class',
    'classes',
]
