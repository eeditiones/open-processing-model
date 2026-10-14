# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Built-in orderings for the footnotes of one run.

An edition does not always print its notes in the order they are referenced. A
critical edition with two series — a lettered text-critical apparatus and
numbered commentary — prints the apparatus first, whatever order the two are
interleaved in the source.

Functions here can be referenced in ``opm.toml`` via the
``transform.footnote_order`` key, e.g.:

```toml
[transform]
footnote_order = "opm.runtime.footnote_order.labelled_first"
```

Each ordering callable has the signature:

```python
def my_order(footnotes: list[Footnote], config: RenderContext) -> list[Footnote]
```

It receives the run's [`Footnote`][opm.runtime.context.Footnote] records in
document order and returns the ones to emit — reordered, and filtered if it
likes. See
[`inject_cached_footnotes`][opm.runtime.pm_runtime.inject_cached_footnotes] for
the full contract, and [Footnotes](../guide/footnotes.md) for the guide.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Footnote, RenderContext


def labelled_first(footnotes: list[Footnote], config: RenderContext) -> list[Footnote]:
    """Notes with a non-numeric marker first, then the rest, each in document order.

    The two-series rule of a critical edition: a note carrying its own TEI
    ``@n`` (``a``, ``b``, … — the text-critical apparatus) comes before one
    numbered by the running counter (the commentary). A stable partition, not a
    sort, so the sequence within each series is the source's.
    """
    _ = config
    lettered = [fn for fn in footnotes if not fn.marker.isdigit()]
    numbered = [fn for fn in footnotes if fn.marker.isdigit()]
    return lettered + numbered


def by_place(footnotes: list[Footnote], config: RenderContext) -> list[Footnote]:
    """Notes grouped by TEI ``@place``: ``foot`` first, then ``end``, then the rest.

    For a text that mixes footnotes and endnotes in one flow and wants them
    kept apart where opm places them.
    """
    _ = config
    rank = {'foot': 0, 'end': 1}
    return sorted(footnotes, key=lambda fn: rank.get((fn.place or '').lower(), 2))


__all__ = ['labelled_first', 'by_place']
