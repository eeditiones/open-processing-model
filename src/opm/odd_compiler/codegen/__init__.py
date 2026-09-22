# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Code generator abstraction for ODD compilation.

Provides an abstract base class for target-language code generators
and shared ODD traversal utilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from lxml import etree

from ...output_modes import output_mode as _mode_named

if TYPE_CHECKING:
    from ..parse_odd import ParsedOdd

TEI_NS = 'http://www.tei-c.org/ns/1.0'
PB_NS = 'http://teipublisher.com/1.0'


class CodeGenerator(ABC):
    """Abstract base class for ODD-to-target-language code generators."""

    @abstractmethod
    def generate_module(
        self,
        parsed: ParsedOdd,
        module_name: str,
        *,
        output_mode: str = 'web',
        base_css: str | None = None,
    ) -> str:
        """Generate target language source code from a parsed ODD.

        Args:
            parsed: The parsed ODD structure
            module_name: Logical name for the generated module
            output_mode: Output channel (web, markdown, print, etc.)

        Returns:
            Complete source code as a string
        """
        ...

    @property
    @abstractmethod
    def target_name(self) -> str:
        """Target language identifier (e.g., 'python', 'rust')."""
        ...

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """File extension for generated files (e.g., '.py', '.rs')."""
        ...


# ── Common ODD traversal utilities ─────────────────────────────────────────────


def _local(tag: str) -> str:
    """Get local name of an XML tag."""
    return etree.QName(tag).localname


def _sanitize_ident(ident: str) -> str:
    """Sanitize identifier for CSS class names."""
    return ident.replace(':', '_')


def _pb_template(parent) -> etree._Element | None:
    """Find pb:template child element if present."""
    for child in parent:
        if child.tag == f'{{{PB_NS}}}template':
            return child
    return None


def _serialize_template_content(tmpl_el) -> str:
    """Return the inner XML content of a pb:template element as a plain string.

    Namespace declarations from the ODD parent scope are stripped so the embedded
    string stays compact and readable; the template engine does not need them.
    """
    import re

    parts = []
    if tmpl_el.text:
        parts.append(tmpl_el.text)
    for child in tmpl_el:
        s = etree.tostring(child, encoding='unicode')
        # Strip all xmlns declarations lxml inherits from the ODD parent scope
        s = re.sub(r'\s*xmlns(?::\w+)?="[^"]*"', '', s)
        parts.append(s)
        if child.tail:
            parts.append(child.tail)
    return ''.join(parts)


def _all_models_in_spec(spec_el) -> list:
    """Get all model elements from an elementSpec."""
    return list(spec_el.iter(f'{{{TEI_NS}}}model'))


def _model_ordinal(spec_el, model_el) -> int:
    """Get 1-based ordinal of a model within its spec (for CSS class generation)."""
    models = _all_models_in_spec(spec_el)
    for i, m in enumerate(models):
        if m is model_el:
            return i + 1
    return 1


def model_key(ident: str, spec_el, model_el) -> str:
    """The key a JSON record's ``model`` field carries (``tei-div11``).

    Generated code puts it in ``cls[1]``, the ``ODD_MODELS`` table is keyed by
    it, and ``opm odd coverage`` joins static findings onto the same key — so all
    three have to agree on how it is built.
    """
    return f'tei-{_sanitize_ident(ident)}{_model_ordinal(spec_el, model_el)}'


OPM_OUTPUT_PREFIX = 'opm-'


def _model_matches_output_mode(el, output_mode: str) -> bool:
    """Whether *el* participates in the given ODD output channel (``@output`` on models).

    Models without ``@output`` are generic and apply to all modes.  Mode-specific
    models override them via the predicate/ordering rules in ``_top_level_models``.

    Some modes build upon other modes (see ``accepts`` in
    [`opm.output_modes`][opm.output_modes]): e.g. ``print`` matches ``@output="print"`` and
    ``@output="web"``; ``markdown`` and ``typst`` match their own name and
    ``@output="plain"``.

    Values prefixed with ``opm-`` (e.g. ``opm-web``) are recognised only by this
    Python compiler; tei-publisher-lib ignores them.
    """
    o = el.get('output')
    if o is None:
        return True
    accepted = _mode_named(output_mode).accepts
    if o in accepted:
        return True
    return any(o == f'{OPM_OUTPUT_PREFIX}{mode}' for mode in accepted)


def _filter_by_output_mode(elements: list, output_mode: str) -> list:
    """Filter elements by output mode, preserving ODD document order."""
    return [el for el in elements if _model_matches_output_mode(el, output_mode)]


def _top_level_models(spec_el, output_mode: str) -> list:
    """Get top-level model/modelSequence/modelGrp children of an elementSpec."""
    kids = []
    for child in spec_el:
        if not isinstance(child.tag, str):
            continue  # skip XML comments / processing instructions
        loc = _local(child.tag)
        if loc in ('model', 'modelSequence', 'modelGrp'):
            kids.append(child)
    return _filter_by_output_mode(kids, output_mode)


def _model_children(seq_or_grp, output_mode: str) -> list:
    """Get model/modelSequence/modelGrp children of a modelSequence or modelGrp."""
    kids = []
    for child in seq_or_grp:
        if not isinstance(child.tag, str):
            continue  # skip XML comments / processing instructions
        loc = _local(child.tag)
        if loc in ('model', 'modelSequence', 'modelGrp'):
            kids.append(child)
    return _filter_by_output_mode(kids, output_mode)


def _gather_params(model_el, *, default_content: str = '.') -> dict[str, str]:
    """Extract parameter names and values from a model element.

    Returns a dict mapping param names to their XPath expression values.
    """
    out: dict[str, str] = {}
    for p in model_el.findall(f'{{{TEI_NS}}}param'):
        name = p.get('name')
        if not name or list(p):
            continue
        val = p.get('value')
        if val is not None:
            out[name] = val
    if 'content' not in out:
        out['content'] = default_content
    return out


def _model_desc(model_el) -> str:
    """Normalized text content from optional child <desc>."""
    desc_el = model_el.find(f'{{{TEI_NS}}}desc')
    if desc_el is None:
        return ''
    text = ' '.join(' '.join(desc_el.itertext()).split())
    return text
