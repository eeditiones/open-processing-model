"""HTML for paged-media CSS (``ext-printcss.xql`` equivalent).

Print extends web HTML: the same element tree and CSS pipeline, but notes and
alternates are inline spans that CSS paged media can ``float: footnote`` /
place in the margin — not interactive ``dl.footnote`` callouts or popovers.
"""

from __future__ import annotations

from opm.runtime.html_output_functions import HtmlOutputFunctions
from opm.runtime.output_functions import PMResult


class PrintOutputFunctions(HtmlOutputFunctions):
    """Serialise to HTML tuned for paged-media CSS (Prince, Paged.js, print).

    Equivalent to the ``pmf:*`` overrides in ``ext-printcss.xql``.
    """

    def note(self, config, node, cls, content, place=None, label=None) -> PMResult:
        """Emit note as an inline span for CSS ``float: footnote`` / margin notes.

        Unlike :meth:`HtmlOutputFunctions.note`, does not build callout links or
        append bodies to ``config['footnotes']``.
        """
        _ = label
        fn_class = 'margin-note' if place == 'margin' else 'footnote'
        el = self._el('span', list(cls) + [fn_class], node)
        config['apply_children'](config, node, content, el)
        return [el]

    def alternate(self, config, node, cls, content, default, alternate, optional=None) -> PMResult:
        """Emit the default reading plus the alternate as a print footnote.

        Ignores ``webcomponents`` / popovers — print has no interactive UI.
        """
        _ = content, optional
        outer = self._el('span', cls, node)
        config['apply_children'](config, node, default, outer)
        result: PMResult = [outer]
        if alternate is not None:
            result.extend(
                self.note(config, node, cls, alternate, place='footnote', label=None)
            )
        return result
