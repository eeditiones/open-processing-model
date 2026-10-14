# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTML for paged-media CSS (``ext-printcss.xql`` equivalent).

Print extends web HTML: the same element tree and CSS pipeline, but notes and
alternates are inline spans that CSS paged media can ``float: footnote`` /
place in the margin — not interactive ``dl.footnote`` callouts or popovers.
"""

from __future__ import annotations

from lxml import etree

from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.output_functions import (
    PMResult,
    classes,
    is_lemma_range_note,
    lemma_range_markers,
    param_str,
)


class PrintOutputFunctions(HtmlOutputFunctions):
    """Serialise to HTML tuned for paged-media CSS (Prince, Paged.js, print).

    Equivalent to the ``pmf:*`` overrides in ``ext-printcss.xql``.
    """

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        """Emit note as an inline span for CSS ``float: footnote`` / margin notes.

        Unlike [`HtmlOutputFunctions.note`][opm.runtime.html_output_functions.HtmlOutputFunctions.note], does not build callout links or
        append bodies to ``config.state.footnotes``. A label (TEI ``@n``) is kept
        as ``data-n`` so print CSS can show a, b, … instead of the running number.

        Lemma ranges: ``place="start"`` emits a plain ``a-`` marker; a note with
        ``@target`` pointing at that anchor gets ``data-range`` so print CSS can
        show ``-a`` as the call and ``a-a`` as the footnote marker.
        """
        label_s = param_str(label) or None
        place_s = param_str(place) or None

        if place_s == 'start':
            if not label_s:
                return []
            start_marker, _end, _fn = lemma_range_markers(label_s)
            el = etree.Element('span')
            el.set('class', classes(*cls, 'note-range-start'))
            el.set('data-n', label_s)
            el.set('data-range', 'start')
            el.text = start_marker
            return [el]

        fn_class = 'margin-note' if place_s == 'margin' else 'footnote'
        el = self._el('span', list(cls) + [fn_class], node)
        if label_s:
            el.set('data-n', ' '.join(label_s.split()))
            if is_lemma_range_note(node):
                el.set('data-range', 'end')
        config.apply_children(config, node, content, el)
        return [el]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        """Emit the default reading plus the alternate as a print footnote.

        Ignores ``webcomponents`` / popovers — print has no interactive UI.
        """
        _ = content, optional
        outer = self._el('span', cls, node)
        config.apply_children(config, node, default, outer)
        result: PMResult = [outer]
        if alternate is not None:
            result.extend(
                self.note(config, node, cls, alternate, place='footnote', label=None)
            )
        return result
