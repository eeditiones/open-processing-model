"""Built-in chunk-selection algorithms for TEI and DocBook documents.

Functions here can be referenced in ``opm.toml`` via the
``chunking.selector`` key, e.g.::

    [chunking]
    selector = "opm.navigation.tei_div_chunks"
    depth = 2

Each selector callable has the signature::

    def my_selector(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]
"""

from __future__ import annotations

import copy

from lxml import etree

from opm.config import ChunkingConfig


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


DBK_NS = 'http://docbook.org/ns/docbook'


def dbk_section_chunks(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]:
    """Return chunk elements by walking DocBook ``section`` elements up to *config.depth*.

    Mirrors ``nav:next-page`` / ``nav:fill`` in ``navigation-dbk.xql``:

    * Sections with no child sections within the depth limit are leaf chunks
      and are included as-is.
    * Sections whose child sections are themselves separate chunks are skipped
      — UNLESS they have content (elements or text) before their first child
      section.  In that case a shallow copy of the parent section containing
      only that pre-subsection content is inserted as an extra chunk immediately
      before the child-section chunks.  This mirrors the ``nav:fill`` logic
      (without the fill-size threshold).
    """
    depth = max(1, config.depth)
    section_tag = f'{{{DBK_NS}}}section'
    ns_map = {'dbk': DBK_NS}

    candidates: list[etree._Element] = root.xpath(
        f'//dbk:section[count(ancestor-or-self::dbk:section) <= {depth}]',
        namespaces=ns_map,
    )

    candidate_set = set(id(el) for el in candidates)
    chunks = []
    for section in candidates:
        # Direct section children that are themselves separate chunks.
        child_section_chunks = [
            child for child in section
            if child.tag == section_tag and id(child) in candidate_set
        ]

        if not child_section_chunks:
            chunks.append(section)
        else:
            # Collect elements before the first child-section chunk.
            first_child = child_section_chunks[0]
            intro_elements = []
            for child in section:
                if child is first_child:
                    break
                intro_elements.append(child)

            has_intro = bool(intro_elements) or bool(section.text and section.text.strip())
            if has_intro:
                # Build a section element containing only the intro content,
                # mirroring the element construction in nav:fill.
                # copy.copy() in lxml includes children, so construct explicitly.
                intro = etree.Element(section.tag, attrib=dict(section.attrib), nsmap=section.nsmap)
                intro.text = section.text
                for el in intro_elements:
                    intro.append(copy.deepcopy(el))
                chunks.append(intro)

    return chunks
