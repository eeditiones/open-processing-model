# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Where each element starts in the original XML text.

``-t json`` exists to explain a transform, and the first thing you do with an
explanation is go and look at the source. A record's ``xpath`` finds the
element in a query; ``line`` and ``col`` find it in an editor.

lxml's ``sourceline`` is not good enough for this. It reports the line where a
start tag *ends*, so an element whose attributes wrap across lines is reported
one or more lines below its ``<`` — on ``examples/serafin`` that is 24 of 260
elements. It also has no column at all, and dense TEI puts many elements on one
line (53% of the elements in ``examples/tei-test.xml`` share a line with
another). So positions come from a second pass with `xml.parsers.expat`,
which reports the exact ``<``.

Correlation is by document order: expat fires ``StartElementHandler`` once per
element, and ``iter()`` yields them in the same order. If the two disagree on
count or name the map is discarded rather than guessed at — a position that
points at the wrong element is worse than no position.
"""

from __future__ import annotations

import xml.parsers.expat
from pathlib import Path

from lxml import etree

from opm.runtime import source_map

# Keyed by the element object, never by ``id()``: lxml recycles proxy objects,
# so ids collide across nodes (see `opm.runtime.source_map`).
PositionMap = dict[etree._Element, tuple[int, int]]


def _expat_starts(raw: bytes) -> list[tuple[str, int, int]]:
    """(local name, 1-based line, 1-based column) for every start tag."""
    parser = xml.parsers.expat.ParserCreate(namespace_separator='}')
    found: list[tuple[str, int, int]] = []

    def start(name: str, _attrs: dict) -> None:
        found.append((
            name.split('}')[-1],
            parser.CurrentLineNumber,
            # expat counts columns from 0; `file:line:col` conventions count
            # from 1, and that is what this is read as.
            parser.CurrentColumnNumber + 1,
        ))

    parser.StartElementHandler = start
    parser.Parse(raw, True)
    return found


def build(source: Path | bytes, root: etree._Element) -> PositionMap:
    """Map every element of *root*'s tree to its position in *source*.

    Returns an empty map when the source cannot be read or does not line up
    with the tree, so callers can treat positions as best-effort.
    """
    try:
        raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    except OSError:
        return {}

    elements = [
        el for el in root.getroottree().getroot().iter()
        if isinstance(el.tag, str)
    ]
    try:
        starts = _expat_starts(raw)
    except xml.parsers.expat.ExpatError:
        return {}

    if len(starts) != len(elements):
        return {}
    positions: PositionMap = {}
    for element, (name, line, col) in zip(elements, starts):
        if etree.QName(element).localname != name:
            # Entity expansion or a mismatched file: stop rather than attach
            # positions that point at the wrong elements.
            return {}
        positions[element] = (line, col)
    return positions


def lookup(element: etree._Element, positions: PositionMap) -> tuple[int, int] | None:
    """Position of *element*, following a chunk copy back to its original."""
    if not positions:
        return None
    hit = positions.get(element)
    if hit is not None:
        return hit
    origin = source_map.source_of(element)
    return positions.get(origin) if origin is not None else None
