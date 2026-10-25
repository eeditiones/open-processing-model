# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: CC0-1.0

"""Facsimile regions of a letter's lines, exposed to the ODD as ``tp:``.

The edition records where each manuscript line sits on its page image in a
mapping table per letter, ``data/regions/<letter id>_mapping.xml``::

    <mappingtable>
      <doc id="K_0096" n="1" image="K_0096_1r_crop.jpg">
        <area shape="rect" coords="111,427,1136,504" target="p1-l7"/>

A line's ``xml:id`` names its page (``p1-l7`` is on page 1). Each table is
read the first time one of its letter's lines asks, and kept while that
letter is processed: a line costs a dictionary lookup, however large the
edition. Reading the tables as a ``[[transform.collections]]`` instead would
parse all of them up front, for every letter.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree as _etree

from opm.runtime.xpath_extensions import expect_string as _expect_string

#: Beside the letters, in the project this module belongs to.
REGIONS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'regions'


@lru_cache(maxsize=8)
def _regions(letter: str) -> dict[str, tuple[str, dict[str, str]]]:
    """Page number → (image, line id → coords) for *letter*; empty without a table."""
    path = REGIONS_DIR / f'{letter}_mapping.xml'
    if not letter or not path.is_file():
        return {}
    pages: dict[str, tuple[str, dict[str, str]]] = {}
    for doc in _etree.parse(str(path)).getroot().iter('doc'):
        if doc.get('id') != letter:
            continue
        areas = {
            area.get('target', ''): area.get('coords', '')
            for area in doc.iter('area')
            if area.get('type') != 'thumbnail'
        }
        pages[doc.get('n', '')] = (doc.get('image', ''), areas)
    return pages


def _page(line: str) -> str:
    """``p12-l3`` → ``12``."""
    head = line.split('-', 1)[0]
    return head[1:] if head.startswith('p') else ''


def region_image(letter: Any, line: Any) -> str:
    """The page image *line* of *letter* is on, or ``''`` if none is recorded.

    ``tp:region_image('K_0096', 'p1-l7')`` → ``K_0096_1r_crop.jpg``.
    """
    letter_s = _expect_string(letter, arg_name='region_image(letter)').strip()
    line_s = _expect_string(line, arg_name='region_image(line)').strip()
    page = _regions(letter_s).get(_page(line_s))
    return page[0] if page else ''


def region_coords(letter: Any, line: Any) -> str:
    """The rectangle of *line* on its page image, ``x1,y1,x2,y2``, or ``''``.

    ``tp:region_coords('K_0096', 'p1-l7')`` → ``111,427,1136,504``.
    """
    letter_s = _expect_string(letter, arg_name='region_coords(letter)').strip()
    line_s = _expect_string(line, arg_name='region_coords(line)').strip()
    page = _regions(letter_s).get(_page(line_s))
    return page[1].get(line_s, '') if page else ''
