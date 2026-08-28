"""Mapping from chunk-copy nodes back to the nodes they were copied from.

``tei_pb_chunks`` and ``dbk_section_chunks`` rebuild a region of the document
as a **detached** tree, so document-order axes evaluated inside a chunk see only
the chunk: ``preceding::pb`` from a page's own ``pb`` finds nothing, and every
page would call itself page 1.

tei-publisher ODDs solve this by stepping back to the stored document first —
``count($get(.)/preceding::pb) + 1``, the page index a facsimile viewer needs.
``$get`` is XQuery's indirection for "the same node in the stored document", and
this registry is what makes it resolvable here: the chunkers record copy →
source as they build, and ``tp:source-node()`` — what ``$get(...)`` compiles to —
looks it up.

The map holds strong references to both trees, so :func:`clear` is called per
document (see :meth:`opm.chunking.ChunkProcessor.select_chunks`). Selectors that
return live document nodes, such as ``tei_div_chunks``, record nothing: their
chunks *are* the source nodes, and lookups fall through to identity.
"""

from __future__ import annotations

from lxml import etree

# Keyed by the lxml element object, whose hash follows C-level node identity.
# Never key by id(): lxml recycles proxy objects, so ids collide across nodes.
_SOURCE_NODES: dict[etree._Element, etree._Element] = {}
_BASE_URI: str | None = None


def clear() -> None:
    """Drop all recorded mappings (call once per source document)."""
    _SOURCE_NODES.clear()
    global _BASE_URI
    _BASE_URI = None


def set_base_uri(uri: str | None) -> None:
    """Record the URI of the document the current mappings point into.

    ``tp:source-node()`` needs it to hand back a node from the *same* wrapped
    tree the XPath context registered, so that ``root()`` and friends resolve.
    """
    global _BASE_URI
    _BASE_URI = uri


def base_uri() -> str | None:
    return _BASE_URI


def record(copy_el: etree._Element, source_el: etree._Element) -> None:
    """Map one rebuilt element to the element it stands for."""
    _SOURCE_NODES[copy_el] = source_el


def record_subtree(copy_el: etree._Element, source_el: etree._Element) -> None:
    """Map a deep copy and every descendant to their originals.

    ``copy.deepcopy`` preserves document order, so zipping the two ``iter()``
    walks pairs each copy with the node it came from. Comments and PIs are
    skipped: they are not addressable by the axes ``$get`` exists to support.
    """
    for copied, original in zip(copy_el.iter(), source_el.iter()):
        if isinstance(copied.tag, str) and isinstance(original.tag, str):
            _SOURCE_NODES[copied] = original


def source_of(el: etree._Element) -> etree._Element | None:
    """Return the stored-document node *el* was copied from, else ``None``."""
    return _SOURCE_NODES.get(el)
