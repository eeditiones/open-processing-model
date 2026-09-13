# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

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

The registry is held in a context variable, so each thread (and each task that
sets its own) has its own and concurrent runs cannot see one another's copies.
It holds strong references to both trees, so [`clear`][opm.runtime.source_map.clear] is called per
document (see [`opm.chunking.ChunkProcessor.select_chunks`][opm.chunking.ChunkProcessor.select_chunks]). Selectors
that return live document nodes, such as ``tei_div_chunks``, record nothing:
their chunks *are* the source nodes, and lookups fall through to identity.
"""

from __future__ import annotations

from contextvars import ContextVar

from lxml import etree


class _SourceMap:
    __slots__ = ('nodes', 'base_uri')

    def __init__(self) -> None:
        # Keyed by the lxml element object, whose hash follows C-level node
        # identity. Never key by id(): lxml recycles proxy objects, so ids
        # collide across nodes.
        self.nodes: dict[etree._Element, etree._Element] = {}
        self.base_uri: str | None = None


_CURRENT: ContextVar[_SourceMap] = ContextVar('opm_source_map')


def _current() -> _SourceMap:
    try:
        return _CURRENT.get()
    except LookupError:
        mapping = _SourceMap()
        _CURRENT.set(mapping)
        return mapping


def clear() -> None:
    """Drop all recorded mappings (call once per source document)."""
    mapping = _current()
    mapping.nodes.clear()
    mapping.base_uri = None


def set_base_uri(uri: str | None) -> None:
    """Record the URI of the document the current mappings point into."""
    _current().base_uri = uri


def base_uri() -> str | None:
    return _current().base_uri


def record(copy_el: etree._Element, source_el: etree._Element) -> None:
    """Map one rebuilt element to the element it stands for."""
    _current().nodes[copy_el] = source_el


def record_subtree(copy_el: etree._Element, source_el: etree._Element) -> None:
    """Map a deep copy and every descendant to their originals.

    ``copy.deepcopy`` preserves document order, so zipping the two ``iter()``
    walks pairs each copy with the node it came from. Comments and PIs are
    skipped: they are not addressable by the axes ``$get`` exists to support.
    """
    nodes = _current().nodes
    for copied, original in zip(copy_el.iter(), source_el.iter()):
        if isinstance(copied.tag, str) and isinstance(original.tag, str):
            nodes[copied] = original


def source_of(el: etree._Element) -> etree._Element | None:
    """Return the stored-document node *el* was copied from, else ``None``."""
    return _current().nodes.get(el)
