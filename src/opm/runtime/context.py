# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The context one transform run passes to every output function as ``config``.

A [`RenderContext`][opm.runtime.context.RenderContext] replaces the plain dict the runtime used to thread
through ``apply``, the generated ``_dispatch`` and every ``pmf`` method. It has
three kinds of content, kept apart:

* **Run settings** — output functions, dispatch, stylesheet, templates, the
  ``$parameters`` dict, the [`XPathEnvironment`][opm.runtime.xpath_env.XPathEnvironment].
  Fixed for the run.
* **Shared run state** — footnotes, collected metadata, counters — in one
  [`RunState`][opm.runtime.context.RunState] that every view of the run holds by reference, so nothing
  is lost when a view is derived.
* **Per-call settings** — ``indent``, ``list_type``, ``template`` and the like,
  which a behaviour changes for its children only. [`RenderContext.derive`][opm.runtime.context.RenderContext.derive]
  returns a new view for that; a context is never mutated in place.

Backend-private caches (DOCX images and numbering, JSON source positions) live
on the output-functions instance, which a run creates for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .output_functions import ProcessingModelFunctions
    from .xpath_env import XPathEnvironment

#: Options of a generated ``transform()`` that configure the run rather than
#: being ``$parameters``. ``input_path`` is both: models may read it too.
RUN_OPTIONS = frozenset({'webcomponents', 'docx_template', 'metadata'})


@dataclass(slots=True)
class RunState:
    """Mutable state shared by every view of one transform run."""

    #: Footnote bodies collected for the end of the document (HTML, Markdown).
    footnotes: list = field(default_factory=list)
    #: Header values collected by the ``metadata`` behaviour (Typst, DOCX).
    metadata: dict[str, list[str]] = field(default_factory=dict)
    note_counter: int = 0
    id_counter: int = 0

    def next_note(self) -> int:
        """Number the next footnote."""
        self.note_counter += 1
        return self.note_counter

    def next_id(self) -> int:
        """A fresh number for a synthetic fragment id."""
        self.id_counter += 1
        return self.id_counter


def _hand_on(config, node, params):
    """Default dispatch: hand the element on untouched."""
    return [node]


def _apply(config, nodes):
    from .pm_runtime import apply  # noqa: PLC0415

    return apply(config, nodes, config.dispatch)


@dataclass(slots=True)
class RenderContext:
    """Everything a behaviour needs; see the module docstring."""

    output: str = 'web'
    pmf: ProcessingModelFunctions | None = None
    dispatch: Callable = _hand_on
    #: ``apply(config, nodes)``; defaults to the runtime's, with [`dispatch`][opm.runtime.context.RenderContext.dispatch].
    apply: Callable = _apply
    #: ``apply_children(config, node, content, parent)``; ``None`` means the runtime's.
    apply_children: Callable | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    xpath: XPathEnvironment | None = None
    webcomponents: bool = False
    odd_css: str = ''
    normalize_text: Callable[[str], str] | None = None
    text_escape: Callable[[str], str] | None = None
    input_path: str | None = None
    docx_template: Any = None
    typst_functions: frozenset[str] = frozenset()
    #: The compiled ``ODD_MODELS`` table (JSON output).
    models: dict | None = None
    #: The element the run transforms.
    root: Any = None

    # Per-call settings, changed through derive().
    #: Set inside a ``pb:template``: its output is finished markup, not source.
    template: bool = False
    indent: str = ''
    list_type: str | None = None
    list_depth: int = -1
    list_id: int | None = None
    table_rows: list | None = None

    state: RunState = field(default_factory=RunState)

    def __post_init__(self) -> None:
        if self.apply_children is None:
            from .pm_runtime import apply_children  # noqa: PLC0415

            self.apply_children = apply_children
        if self.xpath is None:
            from .xpath_env import XPathEnvironment  # noqa: PLC0415

            self.xpath = XPathEnvironment(parameters=self.parameters)

    def derive(self, **changes) -> RenderContext:
        """A view with *changes* applied; the [`RunState`][opm.runtime.context.RunState] stays shared."""
        return replace(self, **changes)


def build_context(
    root,
    options: dict | None = None,
    *,
    mode: str,
    xpath_env: XPathEnvironment | None = None,
    odd_namespaces: dict[str, str] | None = None,
    **settings,
) -> RenderContext:
    """The context a generated module's ``transform()`` runs with.

    *mode* names the output mode; its entry in [`opm.output_modes`][opm.output_modes]
    supplies the output functions and the text handling. *options* holds the
    ``$parameters`` plus the run options in `RUN_OPTIONS`. *xpath_env*
    supplies everything else XPath can see; an empty environment when omitted.
    *settings* are [`RenderContext`][opm.runtime.context.RenderContext] fields the module fixes: dispatch,
    stylesheet and the like.
    """
    from opm.output_modes import output_mode  # noqa: PLC0415

    from .xpath_env import XPathEnvironment  # noqa: PLC0415

    entry = output_mode(mode)
    opts = dict(options or {})
    env = xpath_env if xpath_env is not None else XPathEnvironment()
    parameters = {k: v for k, v in opts.items() if k not in RUN_OPTIONS}
    metadata = opts.get('metadata')
    return RenderContext(
        output=entry.name,
        pmf=entry.output_functions()(),
        parameters=parameters,
        xpath=env.for_odd(odd_namespaces).with_parameters(parameters),
        webcomponents=bool(opts.get('webcomponents')) and entry.webcomponents,
        docx_template=opts.get('docx_template'),
        input_path=opts.get('input_path'),
        root=root,
        # The caller's dict, when it passes one, so it can read what was collected.
        state=RunState(metadata=metadata if isinstance(metadata, dict) else {}),
        **entry.context_settings(),
        **settings,
    )
