"""
Shared processing-model runtime: XPath evaluation, apply / apply-children.

Used by ODD-generated modules and runtime helpers.

Performance:

- **Compiled XPath** and **``$parameters`` maps** are cached (see :func:`_compiled_xpath`,
  :func:`_cached_parameters_map`). XPath is parsed with the context element’s namespace URI
  as **default element namespace** so ODD-style steps like ``parent::div`` match TEI/JATS
  namespaced elements (unprefixed names are not in “no namespace”).
- **Document tree**: elementpath’s wrapper from :func:`get_node_tree` is cached per
  document root (see :func:`_xpath_root_wrapped`) so each predicate does not rebuild
  the full lxml→XPath node tree.
"""

from __future__ import annotations

import elementpath
from functools import lru_cache
from elementpath import XPathContext
from elementpath.tree_builders import get_node_tree
from elementpath.xpath_nodes import XPathNode
from elementpath.xpath31.xpath31_parser import XPath31Parser
from lxml import etree

from .output_functions import child_nodes, normalize

# One elementpath tree wrapper per document (key: id(document root element)).
# Reusing it avoids build_lxml_node_tree() on every xpath_test / xpath_select_nodes.
_document_xpath_roots: dict[int, object] = {}

# Minimal tree used only to parse ``map{{...}}`` into an XPathMap for ``$parameters``.
_PARAM_PARSE_ROOT = etree.fromstring(b'<e/>')
_PARAM_PARSE_CTX = XPathContext(
    root=_PARAM_PARSE_ROOT,
    item=_PARAM_PARSE_ROOT,
)


def _xpath_string_literal(s: str) -> str:
    """Single-quoted XPath string with '' escaping."""
    return "'" + s.replace("'", "''") + "'"


def _parameters_xpath_map(params: dict | None, parse_ctx: XPathContext):
    """Build an XPath 3.1 map value for the ``$parameters`` variable."""
    if not params:
        lit = 'map{}'
    else:
        parts = [
            f'{_xpath_string_literal(str(k))}: {_xpath_string_literal(str(v))}'
            for k, v in params.items()
        ]
        lit = 'map{' + ', '.join(parts) + '}'
    token = XPath31Parser().parse(lit)
    return list(token.select(parse_ctx))[0]


def _params_cache_key(params: dict | None) -> tuple[tuple[str, str], ...]:
    if not params:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in params.items()))


@lru_cache(maxsize=256)
def _cached_parameters_map(key: tuple[tuple[str, str], ...]):
    """One XPathMap per distinct runtime options dict (reused for every node)."""
    params = dict(key) if key else None
    return _parameters_xpath_map(params, _PARAM_PARSE_CTX)


def _default_element_namespace_uri(node: etree._Element) -> str:
    """Namespace URI used for unprefixed element names in XPath (axis steps, kind tests).

    XPath 3.1 binds unqualified names to this URI; TEI ``div`` lives in
    ``http://www.tei-c.org/ns/1.0``, not the empty namespace, so ``parent::div`` only
    matches after setting this. Empty string means no default (legacy behaviour).
    """
    uri = etree.QName(node).namespace
    return uri or ''


@lru_cache(maxsize=8192)
def _compiled_xpath(expr: str, default_element_ns: str = ''):
    """Parse each distinct (*expr*, *default_element_ns*) pair once."""
    if default_element_ns:
        return XPath31Parser(default_namespace=default_element_ns).parse(expr)
    return XPath31Parser().parse(expr)


def _xpath_root_wrapped(root: etree._Element):
    """Return cached elementpath root (ElementNode / DocumentNode) for *root*.

    ``XPathContext`` passes this to :func:`get_node_tree`, which returns the same
    instance without calling :func:`build_lxml_node_tree` again. Context items are
    then resolved via ``root.elements[lxml_element]``.
    """
    key = id(root)
    hit = _document_xpath_roots.get(key)
    if hit is not None:
        return hit
    wrapped = get_node_tree(root)
    _document_xpath_roots[key] = wrapped
    return wrapped


def clear_xpath_document_cache() -> None:
    """Drop cached elementpath document trees (e.g. between tests or documents)."""
    _document_xpath_roots.clear()
    _compiled_xpath.cache_clear()
    _cached_parameters_map.cache_clear()


def make_context(node: etree._Element, params: dict | None = None) -> XPathContext:
    """XPathContext with document root, context item *node*, and ``$parameters`` bound.

    Runtime options are passed as an XPath 3.1 map via ``variables`` so predicate
    strings from the ODD can use ``$parameters?key`` without rewriting the expression.
    """
    root = node.getroottree().getroot()
    pmap = _cached_parameters_map(_params_cache_key(params))
    wrapped = _xpath_root_wrapped(root)
    return XPathContext(
        root=wrapped,
        item=node,
        variables={'parameters': pmap},
    )


def xpath_test(node: etree._Element, expr: str, params: dict | None = None) -> bool:
    """Boolean XPath 3.1 test against *node* (ODD @predicate strings)."""
    try:
        token = _compiled_xpath(expr, _default_element_namespace_uri(node))
        result = list(token.select(make_context(node, params)))
        if not result:
            return False
        if len(result) == 1 and isinstance(result[0], bool):
            return result[0]
        return True
    except elementpath.ElementPathError:
        return False


def xpath_count(node: etree._Element, expr: str, params: dict | None = None) -> int:
    """Count nodes matched by *expr* from *node* (sequence length), not ``count()`` in XPath."""
    try:
        token = _compiled_xpath(expr, _default_element_namespace_uri(node))
        return len(list(token.select(make_context(node, params))))
    except elementpath.ElementPathError:
        return 0


def _unwrap_singleton_xpath_result(result: list):
    """If *expr* yields one atomic (e.g. ``count(...)``), return it; else keep a list.

    Node-like values (:class:`~elementpath.xpath_nodes.XPathNode`) stay wrapped so
    ``xpath_content`` still receives ``[element]`` for single-node paths.
    """
    if len(result) != 1:
        return result
    item = result[0]
    if isinstance(item, XPathNode):
        return result
    return item


def xpath_select_nodes(node: etree._Element, expr: str, params: dict | None = None):
    """Evaluate XPath *expr* with *node* as context.

    Returns a list of nodes (possibly one) for path expressions, or a single atomic
    for expressions like ``count(ancestor::div)`` / ``string(.)``.
    """
    try:
        token = _compiled_xpath(expr, _default_element_namespace_uri(node))
        raw = list(token.select(make_context(node, params)))
        return _unwrap_singleton_xpath_result(raw)
    except elementpath.ElementPathError:
        return []


def resolve_context_element(
    document_root: etree._Element,
    xpath_expr: str,
    params: dict | None = None,
) -> etree._Element:
    """Evaluate *xpath_expr* with *document_root* as the context item; return that element.

    Unprefixed names in *xpath_expr* use the default element namespace taken from
    *document_root* (same rule as :func:`xpath_test` and ODD ``@predicate`` XPath).
    ``$parameters`` is bound from *params* like :func:`make_context`.

    Raises:
        ValueError: XPath is invalid, or the expression does not select exactly one
            element node.
    """
    try:
        token = _compiled_xpath(
            xpath_expr,
            _default_element_namespace_uri(document_root),
        )
        raw = list(token.select(make_context(document_root, params)))
    except elementpath.ElementPathError as e:
        raise ValueError(f'Invalid XPath: {e}') from e

    elements: list[etree._Element] = []
    for item in raw:
        if isinstance(item, XPathNode):
            v = item.value
            if isinstance(v, etree._Element):
                elements.append(v)
        elif isinstance(item, etree._Element):
            elements.append(item)

    if len(elements) != 1:
        raise ValueError(
            f'XPath {xpath_expr!r} must select exactly one element; '
            f'got {len(elements)} element(s) from {len(raw)} value(s)',
        )
    return elements[0]


def tag(node: etree._Element) -> str:
    return etree.QName(node).localname


def ns(node: etree._Element) -> str:
    return etree.QName(node).namespace or ''


def optional_item(item):
    return [item] if item is not None else []


def append_to(parent_el: etree._Element, item) -> None:
    if isinstance(item, str):
        if len(parent_el) == 0:
            parent_el.text = (parent_el.text or '') + item
        else:
            last = parent_el[-1]
            last.tail = (last.tail or '') + item
    elif isinstance(item, etree._Element):
        parent_el.append(item)


def apply_children(config, source_node, content, parent_el) -> None:
    for item in normalize(content):
        if isinstance(item, str):
            append_to(parent_el, item)
        elif isinstance(item, etree._Element):
            dispatch = config['dispatch']
            sub = (
                apply(config, child_nodes(source_node), dispatch)
                if item is source_node
                else apply(config, [item], dispatch)
            )
            for r in sub:
                append_to(parent_el, r)


def apply(config, nodes, dispatch):
    """Transform nodes via *dispatch(config, node, params)*."""
    params = config.get('parameters', {})
    result = []
    for node in nodes:
        if isinstance(node, (str, etree._ElementUnicodeResult)):
            result.append(str(node))
        elif isinstance(node, etree._Element):
            result.extend(dispatch(config, node, params))
    return result


def serialize(nodes) -> str:
    parts = []
    for item in nodes:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, etree._Element):
            parts.append(etree.tostring(item, encoding='unicode', method='html'))
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


def inject_cached_footnotes(nodes: list, config: dict) -> list:
    """Append ``dl.footnote`` bodies collected in ``config['footnotes']`` to the document end.

    :class:`~tei_publisher_py.output_functions.HtmlOutputFunctions` stores each
    footnote body there during :meth:`~tei_publisher_py.output_functions.HtmlOutputFunctions.note`
    and only emits the inline marker in flow; call this after ``apply`` completes.
    """
    footnotes = config.get('footnotes')
    if not footnotes:
        return nodes
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
