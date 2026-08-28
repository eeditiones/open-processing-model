"""Built-in chunk-selection algorithms for TEI and DocBook documents.

Functions here can be referenced in ``opm.toml`` via the
``chunking.selector`` key, e.g.::

    [chunking]
    selector = "opm.navigation.tei_div_chunks"
    depth = 2

    # Or page-break milestones (Shakespeare plays, facsimiles, …):
    # selector = "opm.navigation.tei_pb_chunks"

Each selector callable has the signature::

    def my_selector(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]
"""

from __future__ import annotations

import copy
import re
from typing import Callable

from lxml import etree

from opm.config import ChunkingConfig
from opm.runtime import source_map
from opm.runtime.output_functions import XML_ID


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

    # Keep only leaf nodes: those that have no div child also in candidates.
    # Key by element object — lxml proxies recycle id(), so id(el) is unsafe.
    candidate_set = set(candidates)
    chunks = []
    for div in candidates:
        has_child_chunk = any(
            child in candidate_set
            for child in div
            if child.tag == div_tag
        )
        if not has_child_chunk:
            chunks.append(div)

    return chunks


def tei_pb_chunks(root: etree._Element, config: ChunkingConfig) -> list[etree._Element]:
    """Return one reconstructed page tree per TEI ``pb`` milestone.

    Ports ``nav:get-content`` for ``element(tei:pb)`` and
    ``nav:milestone-chunk`` from ``navigation-tei.xql`` (``view="page"``):

    * Each ``pb`` in document order starts a page.
    * Content runs from that ``pb`` up to (but not including) the next ``pb``.
    * The page is carved from the deepest common ancestor with the next ``pb``,
      or — on the last page — from the nearest ``div`` / ``text`` (or the whole
      ``text`` when the document has only one ``pb``).
    * The returned element is a synthetic tree preserving intervening structure
      (``sp``, ``p``, nested ``div``, …), not the bare ``pb``.

    Chunk roots are stamped with ``xml:id`` from the ``pb`` when present,
    otherwise ``page-{@n}`` or ``page-{index}``, so pb-view / file naming have a
    stable handle even though Folio ``pb`` elements often lack ``xml:id``.
    """
    _ = config  # depth/fill apply to by-division view only
    ns = root.nsmap.get(None, '')
    pb_tag = f'{{{ns}}}pb' if ns else 'pb'
    div_tag = f'{{{ns}}}div' if ns else 'div'
    text_tag = f'{{{ns}}}text' if ns else 'text'

    pbs: list[etree._Element] = [el for el in root.iter(pb_tag)]
    if not pbs:
        return []

    # Positions for every element and for .text / .tail slots (document order).
    el_pos, text_pos, tail_pos = _assign_document_positions(root)
    total_pbs_in_text = {
        text_el: sum(1 for _ in text_el.iter(pb_tag))
        for text_el in root.iter(text_tag)
    }

    chunks: list[etree._Element] = []
    used_ids: set[str] = {
        el.get(XML_ID)
        for el in root.iter()
        if isinstance(el, etree._Element) and el.get(XML_ID)
    }

    for index, pb in enumerate(pbs):
        next_pb = pbs[index + 1] if index + 1 < len(pbs) else None
        context = _pb_chunk_context(
            pb,
            next_pb,
            div_tag=div_tag,
            text_tag=text_tag,
            total_pbs_in_text=total_pbs_in_text,
        )
        if context is None:
            continue

        def descendant_check(
            node: etree._Element,
            ms1: etree._Element,
            ms2: etree._Element | None,
        ) -> bool:
            for desc in node.iter(pb_tag):
                if desc is ms1 or (ms2 is not None and desc is ms2):
                    return True
            return False

        carved = _milestone_chunk(
            pb,
            next_pb,
            context,
            el_pos=el_pos,
            text_pos=text_pos,
            tail_pos=tail_pos,
            descendant_check=descendant_check,
        )
        if carved is None:
            continue

        chunk_id = _pb_chunk_id(pb, index=index, used_ids=used_ids)
        carved.set(XML_ID, chunk_id)
        used_ids.add(chunk_id)
        chunks.append(carved)

    return chunks


def _assign_document_positions(
    root: etree._Element,
) -> tuple[
    dict[etree._Element, int],
    dict[etree._Element, int],
    dict[etree._Element, int],
]:
    """Assign monotonic positions to elements and to ``.text`` / ``.tail`` slots.

    Maps are keyed by the lxml element object (C-level identity). Do not use
    ``id(el)`` — Python proxy objects are recycled and collide across nodes.
    """
    el_pos: dict[etree._Element, int] = {}
    text_pos: dict[etree._Element, int] = {}
    tail_pos: dict[etree._Element, int] = {}
    counter = 0

    def walk(el: etree._Element) -> None:
        nonlocal counter
        el_pos[el] = counter
        counter += 1
        text_pos[el] = counter
        counter += 1
        for child in el:
            walk(child)
            tail_pos[child] = counter
            counter += 1

    walk(root)
    return el_pos, text_pos, tail_pos


def _pb_chunk_context(
    pb: etree._Element,
    next_pb: etree._Element | None,
    *,
    div_tag: str,
    text_tag: str,
    total_pbs_in_text: dict[etree._Element, int],
) -> etree._Element | None:
    """Return the ancestor subtree passed to ``nav:milestone-chunk``."""
    if next_pb is not None:
        next_ancestors = set(next_pb.iterancestors())
        for ancestor in pb.iterancestors():
            if ancestor in next_ancestors:
                return ancestor
        return None

    text_ancestor = next((a for a in pb.iterancestors() if a.tag == text_tag), None)
    if text_ancestor is not None and total_pbs_in_text.get(text_ancestor, 0) == 1:
        return text_ancestor

    for ancestor in pb.iterancestors():
        if ancestor.tag == div_tag or ancestor.tag == text_tag:
            return ancestor
    return pb.getroottree().getroot()


_SAFE_ID = re.compile(r'[^A-Za-z0-9_.-]+')


def _pb_chunk_id(pb: etree._Element, *, index: int, used_ids: set[str]) -> str:
    """Stable ``xml:id`` for a page chunk derived from the milestone ``pb``."""
    existing = pb.get(XML_ID)
    if existing:
        return existing

    raw_n = (pb.get('n') or '').strip()
    if raw_n:
        candidate = 'page-' + _SAFE_ID.sub('-', raw_n).strip('-')
        if candidate and candidate not in used_ids:
            return candidate
        base = candidate or f'page-{index + 1}'
    else:
        base = f'page-{index + 1}'

    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f'{base}-{suffix}'
        suffix += 1
    return candidate


def _milestone_chunk(
    ms1: etree._Element,
    ms2: etree._Element | None,
    node: etree._Element,
    *,
    el_pos: dict[etree._Element, int],
    text_pos: dict[etree._Element, int],
    tail_pos: dict[etree._Element, int],
    descendant_check: Callable[
        [etree._Element, etree._Element, etree._Element | None],
        bool,
    ],
) -> etree._Element | None:
    """Python port of ``nav:milestone-chunk`` for element subtrees."""
    ms1_i = el_pos[ms1]
    ms2_i = el_pos[ms2] if ms2 is not None else None

    def between(pos: int) -> bool:
        return pos > ms1_i and (ms2_i is None or pos < ms2_i)

    def carve(el: etree._Element) -> etree._Element | None:
        # End milestone is exclusive (content runs up to, not including, ms2).
        if ms2 is not None and el is ms2:
            return None
        if el is ms1:
            copied = copy.deepcopy(el)
            source_map.record_subtree(copied, el)
            return copied

        if descendant_check(el, ms1, ms2):
            out = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
            # A rebuilt ancestor: same element, minus the content outside the page.
            source_map.record(out, el)
            # Leading text of an ancestor of ms1 sits before ms1 → omit unless
            # the slot itself falls after ms1 (e.g. while carving toward ms2).
            if el.text and between(text_pos[el]):
                out.text = el.text

            last: etree._Element | None = None
            for child in el:
                carved_child = carve(child)
                if carved_child is not None:
                    out.append(carved_child)
                    last = carved_child
                if child.tail and between(tail_pos[child]):
                    if last is not None:
                        last.tail = (last.tail or '') + child.tail
                    else:
                        out.text = (out.text or '') + child.tail
            return out

        if between(el_pos[el]):
            copied = copy.deepcopy(el)
            source_map.record_subtree(copied, el)
            return copied

        return None

    return carve(node)


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

    candidate_set = set(candidates)
    chunks = []
    for section in candidates:
        # Direct section children that are themselves separate chunks.
        child_section_chunks = [
            child for child in section
            if child.tag == section_tag and child in candidate_set
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
                source_map.record(intro, section)
                intro.text = section.text
                for el in intro_elements:
                    copied = copy.deepcopy(el)
                    source_map.record_subtree(copied, el)
                    intro.append(copied)
                chunks.append(intro)

    return chunks
