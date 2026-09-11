# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Processing-model runtime: apply / apply-children and the node helpers.

Used by ODD-generated modules and runtime helpers. A run's settings and state
travel in a :class:`~opm.runtime.context.RenderContext` (``config``), and its
XPath is evaluated by the context's
:class:`~opm.runtime.xpath_env.XPathEnvironment`.
"""

from __future__ import annotations

from lxml import etree

from .output_functions import TemplateOutput, child_nodes, maybe_normalize_text, normalize


# ── node helpers ─────────────────────────────────────────────────────────────


def tag(node: etree._Element) -> str:
    """Local name for *node*.

    lxml comments, PIs, and entities use a Cython factory object as ``.tag``, not a
    string, so :func:`etree.QName` cannot be used on them directly.
    """
    if isinstance(node, etree._Comment):
        return 'comment'
    if isinstance(node, etree._ProcessingInstruction):
        return 'processing-instruction'
    if isinstance(node, etree._Entity):
        return 'entity'
    return etree.QName(node).localname


def ns(node: etree._Element) -> str:
    if isinstance(node, (etree._Comment, etree._ProcessingInstruction, etree._Entity)):
        return ''
    return etree.QName(node).namespace or ''


def optional_item(item):
    return [item] if item is not None else []


def append_to(parent_el: etree._Element | list, item) -> None:
    if isinstance(parent_el, list):
        if isinstance(item, str):
            parent_el.append(item)
        elif isinstance(item, dict):
            # JSON output records; every other mode produces str / Element only,
            # so without this arm they would be dropped here without a trace.
            parent_el.append(item)
        elif isinstance(item, etree._Element):
            result = etree.tostring(item, encoding='utf-8', method='html')
            if isinstance(result, bytes):
                result = result.decode('utf-8')
            parent_el.append(result)
        return
    if isinstance(item, str):
        if len(parent_el) == 0:
            parent_el.text = _join_text(parent_el.text, item)
        else:
            last = parent_el[-1]
            last.tail = _join_text(last.tail, item)
    elif isinstance(item, etree._Element):
        parent_el.append(item)


def _join_text(existing: str | None, item: str) -> str:
    """Concatenate two adjacent text runs of the same output element.

    A soft hyphen left at the seam is a word the source broke across lines, so
    the indentation opening the next run is not a word separator — see
    :func:`~opm.runtime.output_functions.join_eol_hyphen`, which handles the
    common case where both halves sit in one text node. Here the runs are
    separated by an omitted element (``daugh­<lb/>\n(ter``).
    """
    base = existing or ''
    if base.endswith('­'):
        item = item.lstrip(' \t\r\n')
    return base + item


# ── apply / apply-children ───────────────────────────────────────────────────


def template_config(config):
    """*config* as seen inside a ``pb:template``.

    A behaviour combined with a ``pb:template`` receives the already-rendered
    template nodes as its content, so :func:`apply` and :func:`apply_children`
    must hand them straight on instead of dispatching them again. Mirrors
    ``map:entry("template", true())`` in ``model.xql``, which is what stops
    tei-publisher-lib from reprocessing template output.

    Without it an ODD whose ``schemaSpec`` has ``ns=""`` (JATS, and any other
    vocabulary in no namespace) loses every element a template builds: the
    generated ``_dispatch`` passes foreign-namespace nodes through untouched,
    but for those ODDs the template's ``<li>`` looks exactly like a source
    element and falls through to "apply children", dropping the wrapper.
    """
    return config.derive(template=True)


def apply_children(config, source_node, content, parent_el) -> None:
    if config.template:
        # Template output is finished markup — see :func:`template_config`.
        for item in normalize(content):
            append_to(parent_el, item)
        return
    norm = config.normalize_text
    text_escape = config.text_escape
    for item in normalize(content):
        if isinstance(item, str):
            text = maybe_normalize_text(item, norm)
            if text_escape and not isinstance(item, TemplateOutput):
                text = text_escape(text)
            append_to(parent_el, text)
        elif isinstance(item, etree._Element):
            dispatch = config.dispatch
            sub = (
                apply(config, child_nodes(source_node), dispatch)
                if item is source_node
                else apply(config, [item], dispatch)
            )
            for r in sub:
                append_to(parent_el, r)


def apply(config, nodes, dispatch):
    """Transform nodes via *dispatch(config, node, params)*."""
    if config.template:
        # Template output is finished markup — see :func:`template_config`.
        return list(normalize(nodes))
    params = config.parameters
    norm = config.normalize_text
    text_escape = config.text_escape
    result = []
    for node in nodes:
        if isinstance(node, (str, etree._ElementUnicodeResult)):
            text = maybe_normalize_text(str(node), norm)
            if text_escape and not isinstance(node, TemplateOutput):
                text = text_escape(text)
            result.append(text)
        elif isinstance(node, etree._Element) and not callable(node.tag):
            result.extend(dispatch(config, node, params))
    return result


def apply_template_param_value(config, source_node, raw):
    """Normalize and dispatch *raw* for ``pb:template`` ``[[param]]`` substitution.

    XPath (or a literal ``.`` param) may yield the context element itself. Passing
    that element through :func:`apply` would re-dispatch the same TEI node and, in
    templates, often stringifies it. When an item **is** *source_node*, recurse on
    ``child_nodes(source_node)`` instead (same rule as :func:`apply_children`).
    """
    dispatch = config.dispatch
    norm = config.normalize_text
    text_escape = config.text_escape
    result = []
    for item in normalize(raw):
        if isinstance(item, (str, etree._ElementUnicodeResult)):
            text = maybe_normalize_text(str(item), norm)
            if text_escape and not isinstance(item, TemplateOutput):
                text = text_escape(text)
            result.append(text)
        elif isinstance(item, etree._Element):
            if item is source_node:
                result.extend(apply(config, child_nodes(source_node), dispatch))
            else:
                result.extend(apply(config, [item], dispatch))
        else:
            result.append(str(item))
    return result


def serialize(nodes) -> str:
    parts = []
    for item in nodes:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element):
            result = etree.tostring(item, encoding='utf-8', method='html')
            if isinstance(result, bytes):
                result = result.decode('utf-8')
            parts.append(result)
    return '\n'.join(parts)


def _footnote_injection_target(element_roots: list[etree._Element]) -> etree._Element | None:
    html_el = next(
        (r for r in element_roots if etree.QName(r).localname == 'html'),
        None,
    )
    if html_el is not None:
        body = html_el.find('body')
        return body if body is not None else html_el
    if element_roots:
        return element_roots[-1]
    return None


def inject_cached_footnotes(nodes: list, config) -> list:
    """Append the footnote bodies collected in ``config.state`` after the main flow.

    HTML: :class:`~opm.html_output_functions.HtmlOutputFunctions` stores
    ``dl.footnote`` elements. Markdown: stores reference-definition strings.
    """
    footnotes = config.state.footnotes
    if not footnotes:
        return nodes
    if isinstance(footnotes[0], str):
        out = list(nodes) + list(footnotes)
        footnotes.clear()
        return out
    roots = [x for x in nodes if isinstance(x, etree._Element)]
    if not roots:
        return nodes
    target = _footnote_injection_target(roots)
    if target is None:
        return nodes
    for dl in footnotes:
        target.append(dl)
    footnotes.clear()
    return nodes
