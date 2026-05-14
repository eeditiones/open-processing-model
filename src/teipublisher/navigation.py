"""Built-in chunk-selection algorithms for TEI documents.

Functions here can be referenced in ``teipublisher.toml`` via the
``chunking.selector`` key, e.g.::

    [chunking]
    selector = "teipublisher.navigation.tei_div_chunks"
    depth = 2

Each selector callable has the signature::

    def my_selector(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]
"""

from __future__ import annotations

from lxml import etree

from teipublisher.config import ChunkingConfig


def tei_div_chunks(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]:
    """Return chunk elements by walking TEI ``div`` divisions up to *config.depth*.

    Algorithm (mirrors ``nav:next-page`` / ``nav:previous-page`` in
    ``navigation-tei.xql``, pb-pagination excluded):

    * Walk every ``div`` in document order whose nesting level
      (``count(ancestor-or-self::div)``) is at most *depth*.
    * A div is included as a chunk only when it has **no** descendant ``div``
      within the same depth limit — i.e. it is a "leaf" at the configured
      depth.  Parent divs whose children are already enumerated as separate
      chunks are therefore skipped.

    With ``depth = 1`` the result is identical to ``//text/body/div``.
    With ``depth = 2`` top-level divs that contain child divs are replaced by
    those children; top-level divs without children are kept as-is.
    """
    depth = max(1, config.depth)
    ns = root.nsmap.get(None, '')
    div_tag = f'{{{ns}}}div' if ns else 'div'
    ns_map = {'tei': ns} if ns else {}
    prefix = 'tei:' if ns else ''

    # Collect every div at level <= depth (document order)
    candidates: list[etree._Element] = root.xpath(
        f'//{prefix}text/{prefix}body//{prefix}div'
        f'[count(ancestor-or-self::{prefix or ""}div) <= {depth}]',
        namespaces=ns_map,
    )

    # Keep only leaf nodes: those that have no div child also in candidates
    candidate_set = set(id(el) for el in candidates)
    chunks = []
    for div in candidates:
        has_child_chunk = any(
            id(child) in candidate_set
            for child in div
            if child.tag == div_tag
        )
        if not has_child_chunk:
            chunks.append(div)

    return chunks
