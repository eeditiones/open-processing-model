# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The output modes opm can compile an ODD for, in one table.

Everything that differs between output modes is
recorded here: which ODD models take part, which output functions render them
and with which text handling, whether web components may load, which template
wraps the result and where a project configures it, and how ``--preview``
shows it. The compiler, the generated modules, the transform entry points and
the CLI all look a mode up instead of testing its name.

JSON output records what another channel decided, so besides plain ``json``
(the web channel) there is a ``json-<channel>`` mode for each rendering channel,
derived from that channel's entry.

This module imports nothing from the runtime: output functions and text
handlers are named by dotted path and imported when a run needs them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from typing import Any

JSON = 'json'

#: The mode used when none is given.
DEFAULT_MODE = 'web'

_NORMALIZE_TEXT = 'opm.runtime.markdown_output_functions.normalize_markdown_xml_text'


@dataclass(frozen=True, slots=True)
class OutputMode:
    """One output mode; see the module docstring."""

    name: str
    #: ODD ``@output`` values whose models take part (``opm-`` prefixed too).
    accepts: tuple[str, ...]
    #: The ``ProcessingModelFunctions`` subclass rendering this mode, as a dotted path.
    functions: str
    #: :class:`~opm.runtime.context.RenderContext` fields the mode sets, each
    #: naming a callable by dotted path.
    settings: tuple[tuple[str, str], ...] = ()
    #: How the ODD's renditions are compiled: ``'css'`` or ``'typst'``.
    stylesheet: str = 'css'
    #: Whether tei-publisher web components may be enabled.
    webcomponents: bool = True
    #: JSON records: unmatched elements go through the output functions and
    #: the module carries an ``ODD_MODELS`` table.
    records: bool = False
    #: What ``--template`` and ``[transform.<type>] template`` supply: an HTML
    #: shell (``'html'``), a Typst shell (``'typst'``), a Word style template
    #: (``'docx'``), or nothing.
    template: str | None = None
    #: The :class:`~opm.config.ProjectConfig` attribute holding the project's template.
    template_setting: str | None = None
    #: The packaged template used when the project sets none.
    default_template: str | None = None
    #: Add the packaged paged-media stylesheet to the HTML shell.
    print_css: bool = False
    #: Collect ``metadata`` behaviour values for the template.
    collects_metadata: bool = False
    #: The output is packaged into chapters by :func:`opm.epub.build_epub`.
    packaged: bool = False
    #: The output is ``bytes``, not text.
    binary: bool = False
    #: File extension of the output.
    extension: str = ''
    #: How ``--preview`` shows the output: ``'browser'``, ``'markdown'``,
    #: ``'json'``, ``'app'`` (the platform's default application) or ``'text'``.
    #: A mode with a :attr:`compiler` previews the compiled PDF instead, when
    #: the compiler is installed.
    preview: str = 'text'
    #: Configured by ``opm init`` unless the user picks otherwise.
    scaffold: bool = False
    #: For a JSON mode, the rendering channel it records.
    channel: str | None = None
    #: A program that can compile the output to PDF: ``'typst'`` runs
    #: ``typst compile`` (see :mod:`opm.typst_compile`). ``opm transform``
    #: compiles for a ``.pdf`` output file and for ``--preview``.
    compiler: str | None = None

    @property
    def section(self) -> str:
        """The ``[transform.<type>]`` table configuring this mode."""
        return JSON if self.records else self.name

    def output_functions(self) -> type:
        """The output-functions class, imported on first use."""
        return _import(self.functions)

    def context_settings(self) -> dict[str, Callable]:
        """The :attr:`settings` resolved to their callables."""
        return {name: _import(path) for name, path in self.settings}


@cache
def _import(path: str) -> Any:
    module, _, attr = path.rpartition('.')
    return getattr(import_module(module), attr)


_WEB = OutputMode(
    name='web',
    accepts=('web',),
    functions='opm.runtime.html_output_functions.HtmlOutputFunctions',
    template='html',
    template_setting='document_template',
    default_template='default_document.html.j2',
    extension='.html',
    preview='browser',
    scaffold=True,
)

#: Every rendering channel, in the order help texts list them.
RENDER_MODES: dict[str, OutputMode] = {
    mode.name: mode
    for mode in (
        _WEB,
        OutputMode(
            name='print',
            accepts=('print', 'web'),
            functions='opm.runtime.print_output_functions.PrintOutputFunctions',
            # Paged media has no interactive UI.
            webcomponents=False,
            template='html',
            # Not the web shell: that brings navigation and web components.
            template_setting='print_template',
            default_template='default_print.html.j2',
            print_css=True,
            extension='.html',
            preview='browser',
        ),
        OutputMode(
            name='epub',
            accepts=('epub', 'web'),
            functions='opm.runtime.epub_output_functions.EpubOutputFunctions',
            # EPUB readers have no tei-publisher web-component runtime.
            webcomponents=False,
            packaged=True,
            binary=True,
            extension='.epub',
            preview='app',
        ),
        OutputMode(
            name='markdown',
            accepts=('markdown', 'plain'),
            functions='opm.runtime.markdown_output_functions.MarkdownOutputFunctions',
            settings=(('normalize_text', _NORMALIZE_TEXT),),
            extension='.md',
            preview='markdown',
            scaffold=True,
        ),
        OutputMode(
            name='docx',
            accepts=('docx',),
            functions='opm.runtime.docx_output_functions.DocxOutputFunctions',
            settings=(
                ('apply_children', 'opm.runtime.docx_output_functions.docx_apply_children'),
                ('normalize_text', _NORMALIZE_TEXT),
            ),
            # The packaged default is opm.resources.packaged_default_docx().
            template='docx',
            template_setting='document_docx_template',
            binary=True,
            extension='.docx',
            preview='app',
            scaffold=True,
        ),
        OutputMode(
            name='typst',
            accepts=('typst',),
            functions='opm.runtime.typst_output_functions.TypstOutputFunctions',
            settings=(
                ('normalize_text', _NORMALIZE_TEXT),
                ('text_escape', 'opm.runtime.typst_output_functions.escape_typst_text_node'),
            ),
            stylesheet='typst',
            template='typst',
            template_setting='typst_template',
            default_template='default_document.typ.j2',
            collects_metadata=True,
            extension='.typ',
            scaffold=True,
            compiler='typst',
        ),
    )
}


def _json_mode(channel: OutputMode) -> OutputMode:
    """The JSON mode recording *channel*'s decisions."""
    return OutputMode(
        name=JSON if channel is _WEB else f'{JSON}-{channel.name}',
        accepts=(JSON, *channel.accepts),
        functions='opm.runtime.json_output_functions.JsonOutputFunctions',
        # normalize_text keeps XML pretty-printing out of the text runs.
        settings=(('normalize_text', _NORMALIZE_TEXT),),
        webcomponents=False,
        records=True,
        extension='.json',
        preview='json',
        channel=channel.name,
    )


#: Every mode by name: the rendering channels, ``json`` and each ``json-<channel>``.
MODES: dict[str, OutputMode] = {
    **RENDER_MODES,
    JSON: _json_mode(_WEB),
    **{f'{JSON}-{name}': _json_mode(mode) for name, mode in RENDER_MODES.items()},
}

#: The ``[transform.<type>]`` tables ``opm.toml`` may declare.
CONFIG_SECTIONS: tuple[str, ...] = (*RENDER_MODES, JSON)


def output_mode(name: str | None) -> OutputMode:
    """The mode called *name* (case-insensitive; empty means :data:`DEFAULT_MODE`)."""
    key = (name or '').strip().lower() or DEFAULT_MODE
    try:
        return MODES[key]
    except KeyError:
        known = ', '.join(CONFIG_SECTIONS)
        raise ValueError(f'Unknown output mode {name!r}; expected one of {known}.') from None


def module_mode(mod: Any) -> OutputMode:
    """The mode a compiled transform module was generated for."""
    return output_mode(mod.OUTPUT_MODE)
