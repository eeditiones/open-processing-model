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
