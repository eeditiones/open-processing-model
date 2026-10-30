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
RUN_OPTIONS = frozenset(
    {'webcomponents', 'docx_template', 'metadata', 'footnote_order'}
)


@dataclass(slots=True)
class Footnote:
    """One collected footnote, before it is placed at the end of a run.

    The backends that collect footnotes render the body eagerly but place it
    only when the run ends, so everything a
    [`footnote_order`][opm.runtime.context.RenderContext] hook
    might sort or filter on is kept here as data. A hook never has to read it
    back out of the markup.
    """

    #: The rendered body: a ``dl.footnote`` element (HTML) or a
    #: reference-definition string (Markdown). A hook must not mutate it.
    body: Any
    #: Running number from [`RunState.next_note`][opm.runtime.context.RunState.next_note],
    #: taken where the reference is emitted. ``0`` for a note that carries its
    #: own [`label`][opm.runtime.context.Footnote.label] and so draws no number
    #: — the two series of a critical edition number independently.
    number: int
    #: The ODD ``label`` param (TEI ``@n``); ``None`` when the note has none.
    label: str | None = None
    #: The id the reference links to (``fn_<id>``).
    anchor: str = ''
    #: The ODD ``place`` param (TEI ``@place``).
    place: str | None = None
    #: The source element, so a hook can read any attribute it needs.
    node: Any = None

    @property
    def marker(self) -> str:
        """What the reader sees: the label, else the running number."""
        return self.label if self.label else str(self.number)


#: Reorder one run's footnotes before they are placed; see
#: [`RenderContext.footnote_order`][opm.runtime.context.RenderContext].
FootnoteOrder = Callable[[list[Footnote], 'RenderContext'], list[Footnote]]


@dataclass(slots=True)
class RunState:
    """Mutable state shared by every view of one transform run."""

    #: Footnotes collected for the end of the document (HTML, Markdown).
    footnotes: list[Footnote] = field(default_factory=list)
    #: Header values collected by the ``metadata`` behaviour (Typst, DOCX).
    metadata: dict[str, list[str]] = field(default_factory=dict)
    note_counter: int = 0
    id_counter: int = 0

    def next_note(self) -> int:
        """Number the next footnote."""
        self.note_counter += 1
        return self.note_counter

    def add_note(
        self,
        body: Any,
        *,
        number: int,
        label: str | None = None,
        anchor: str = '',
        place: str | None = None,
        node: Any = None,
    ) -> None:
        """Collect a rendered footnote body for the end of the run."""
        self.footnotes.append(
            Footnote(
                body=body,
                number=number,
                label=label or None,
                anchor=anchor,
                place=place or None,
                node=node,
            )
        )

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
    #: Reorder a run's footnotes before they are placed; ``None`` keeps
    #: document order. See
    #: [`inject_cached_footnotes`][opm.runtime.pm_runtime.inject_cached_footnotes]
    #: for the contract, and [`opm.runtime.footnote_order`][opm.runtime.footnote_order]
    #: for the orderings that ship with opm.
    footnote_order: FootnoteOrder | None = None

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

    ``footnote_order`` may be given either as a callable or as the dotted path
    of one, so a project can name it in ``opm.toml``.
    """
    from opm.output_modes import load_callable, output_mode  # noqa: PLC0415

    from .xpath_env import XPathEnvironment  # noqa: PLC0415

    entry = output_mode(mode)
    opts = dict(options or {})
    env = xpath_env if xpath_env is not None else XPathEnvironment()
    parameters = {k: v for k, v in opts.items() if k not in RUN_OPTIONS}
    metadata = opts.get('metadata')
    order = opts.get('footnote_order')
    return RenderContext(
        output=entry.name,
        pmf=entry.output_functions()(),
        parameters=parameters,
        xpath=env.for_odd(odd_namespaces).with_parameters(parameters),
        webcomponents=bool(opts.get('webcomponents')) and entry.webcomponents,
        docx_template=opts.get('docx_template'),
        input_path=opts.get('input_path'),
        root=root,
        footnote_order=load_callable(order) if isinstance(order, str) else order,
        # The caller's dict, when it passes one, so it can read what was collected.
        state=RunState(metadata=metadata if isinstance(metadata, dict) else {}),
        **entry.context_settings(),
        **settings,
    )
