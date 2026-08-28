"""
Shared processing-model runtime: XPath evaluation, apply / apply-children.

Used by ODD-generated modules and runtime helpers.

Performance:

- **Compiled XPath** and **``$parameters`` maps** are cached (see :func:`_compiled_xpath`,
  :func:`_cached_parameters_map`, and :func:`_loaded_extension_callables`). Parsed
  expressions are keyed by (*expr*, default element namespace, extension-module fingerprint).
  XPath is parsed with the context element’s namespace URI
  as **default element namespace** so ODD-style steps like ``parent::div`` match TEI/JATS
  namespaced elements (unprefixed names are not in “no namespace”).
- **Document tree**: elementpath’s wrapper from :func:`get_node_tree` is cached per
  document root (see :func:`_xpath_root_wrapped`) so each predicate does not rebuild
  the full lxml→XPath node tree.
"""

from __future__ import annotations

import elementpath
from functools import lru_cache
from typing import Any
from elementpath import XPathContext
from elementpath.tree_builders import get_node_tree
from elementpath.xpath_nodes import XPathNode
from elementpath.xpath31.xpath31_parser import XPath31Parser
from lxml import etree

from .output_functions import TemplateOutput, child_nodes, maybe_normalize_text, normalize
from .xpath_extensions import (
    build_extension_parser,
    fingerprint_for_module,
    load_extension_callables,
)

# One elementpath tree wrapper per document (key: id(document root element)).
# Reusing it avoids build_lxml_node_tree() on every xpath_test / xpath_select_nodes.
_document_xpath_roots: dict[tuple[int, str | None], object] = {}
_XPATH_DOCUMENTS_PARAM = '__opm_xpath_documents'
_XPATH_COLLECTIONS_PARAM = '__opm_xpath_collections'
_XPATH_VARIABLES_PARAM = '__opm_xpath_variables'
_XPATH_NAMESPACES_PARAM = '__opm_xpath_namespaces'
_XPATH_BASE_URI_PARAM = '__opm_xpath_base_uri'
# Original viewed node for ``$parameters?root`` (tei-publisher-lib convention).
_XPATH_ROOT_PARAM = '__opm_xpath_root'

# Minimal tree used only to parse ``map{{...}}`` into an XPathMap for ``$parameters``.
_PARAM_PARSE_ROOT = etree.fromstring(b'<e/>')
_PARAM_PARSE_CTX = XPathContext(
    root=_PARAM_PARSE_ROOT,  # type: ignore[arg-type]
    item=_PARAM_PARSE_ROOT,  # type: ignore[arg-type]
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
    return tuple(
        sorted(
            (str(k), str(v))
            for k, v in params.items()
            if k not in (
                _XPATH_DOCUMENTS_PARAM,
                _XPATH_COLLECTIONS_PARAM,
                _XPATH_VARIABLES_PARAM,
                _XPATH_NAMESPACES_PARAM,
                _XPATH_BASE_URI_PARAM,
                _XPATH_ROOT_PARAM,
            )
        )
    )


@lru_cache(maxsize=256)
def _cached_parameters_map(key: tuple[tuple[str, str], ...]):
    """One XPathMap per distinct runtime options dict (reused for every node)."""
    params = dict(key) if key else None
    return _parameters_xpath_map(params, _PARAM_PARSE_CTX)


# Cache: (params_key, id(root_element)) → XPathMap including root node.
_params_map_with_root_cache: dict[tuple, Any] = {}


def _parameters_map_with_root(
    params_key: tuple[tuple[str, str], ...],
    root: 'etree._Element',
    base_uri: str | None = None,
) -> Any:
    """Build a ``$parameters`` XPathMap that includes *root* as the ``root`` entry.

    Uses ``"root": .`` in the map literal with *root* as the XPath context item
    so the result is a proper XPathMap node value, not a plain Python dict.
    The wrapper is the document that contains *root*, so *root* may be the
    viewed chunk (tei-publisher-lib) rather than the document element.
    Cached by (params_key, id(root), base_uri) — one map per distinct
    (params, view node, document URI).
    """
    cache_key = (params_key, id(root), base_uri)
    hit = _params_map_with_root_cache.get(cache_key)
    if hit is not None:
        return hit
    params = dict(params_key) if params_key else {}
    parts = [
        f'{_xpath_string_literal(str(k))}: {_xpath_string_literal(str(v))}'
        for k, v in params.items()
    ]
    parts.append('"root": .')
    lit = 'map{' + ', '.join(parts) + '}'
    token = XPath31Parser().parse(lit)
    doc_root = root.getroottree().getroot()
    wrapped = _xpath_root_wrapped(doc_root, base_uri)
    ctx = XPathContext(root=wrapped, item=wrapped.elements[root])  # type: ignore[arg-type,index]
    result = list(token.select(ctx))[0]
    _params_map_with_root_cache[cache_key] = result
    return result


def _default_element_namespace_uri(node: etree._Element) -> str:
    """Namespace URI used for unprefixed element names in XPath (axis steps, kind tests).

    XPath 3.1 binds unqualified names to this URI; TEI ``div`` lives in
    ``http://www.tei-c.org/ns/1.0``, not the empty namespace, so ``parent::div`` only
    matches after setting this. Empty string means no default (legacy behaviour).
    """
    if isinstance(node, (etree._Comment, etree._ProcessingInstruction, etree._Entity)):
        return ''
    uri = etree.QName(node).namespace
    return uri or ''


def _parse_xpath(
    expr: str,
    default_element_ns: str,
    ext_fp: str,
    namespaces: dict[str, str] | None = None,
    base_uri: str | None = None,
):
    """Parse *expr*; *ext_fp* is ``fingerprint_for_module(...)`` or ``''``."""
    ns = namespaces or {}
    if ext_fp:
        callables = _loaded_extension_callables(ext_fp)
        parser = build_extension_parser(
            default_element_ns,
            callables,
            namespaces=ns,
            base_uri=base_uri,
        )
    elif default_element_ns or ns:
        parser = XPath31Parser(
            default_namespace=default_element_ns or None,
            namespaces=ns,
            base_uri=base_uri,
        )
    else:
        parser = XPath31Parser(base_uri=base_uri)
    return parser.parse(expr)


@lru_cache(maxsize=64)
def _loaded_extension_callables(ext_fp: str) -> dict:
    """Map fingerprint string to merged callables dict (cached per module set)."""
    merged: dict = {}
    # ext_fp is one or more module fingerprints joined by '\x1f'.
    for item in ext_fp.split('\x1f'):
        module_path = item.split('\0', 1)[0]
        merged.update(load_extension_callables(module_path))
    return merged


@lru_cache(maxsize=8192)
def _compiled_xpath(
    expr: str,
    default_element_ns: str = '',
    ext_fp: str = '',
    namespaces: frozenset[tuple[str, str]] | None = None,
    base_uri: str | None = None,
):
    """Parse each distinct XPath/static-context tuple once."""
    ns_dict = dict(namespaces) if namespaces else None
    return _parse_xpath(expr, default_element_ns, ext_fp, ns_dict, base_uri)


def _xpath_root_wrapped(root: etree._Element, base_uri: str | None = None):
    """Return cached elementpath ``EtreeDocumentNode`` for *root*.

    Wraps the ``_ElementTree`` so that ``root()`` returns the document node per
    the XPath spec, making ``root(.)/TEI/text/back`` style paths work correctly.
    Context items are resolved via ``wrapped.elements[lxml_element]``.

    *base_uri* is attached to the document node, which is what makes
    ``document-uri()`` and ``base-uri()`` return the source file rather than the
    empty sequence. The parser's static base URI is a separate thing — it
    resolves relative arguments to ``doc()`` and ``collection()`` but never
    reaches the tree — so both have to be supplied. teipublisher.odd derives
    facsimile and static-page links from ``document-uri(root($parameters?root))``,
    and gets nothing without this.
    """
    key = (id(root), base_uri)
    hit = _document_xpath_roots.get(key)
    if hit is not None:
        return hit
    wrapped = get_node_tree(root.getroottree(), uri=base_uri)  # type: ignore[arg-type]
    _document_xpath_roots[key] = wrapped
    return wrapped


def xpath_runtime_context(
    *,
    base_uri: str | None = None,
    documents: dict[str, Any] | None = None,
    collections: dict[str, list] | None = None,
    variables: dict[str, Any] | None = None,
    namespaces: dict[str, str] | None = None,
    root: 'etree._Element' | None = None,
) -> dict[str, Any]:
    """Return internal keys merged into the XPath ``$parameters`` map.

    *root* is the node bound as ``$parameters?root`` (tei-publisher-lib: the
    currently viewed element in the original document). Omit it to default to
    the document element of the context node. *base_uri* and *documents*
    populate ``doc()``.
    """
    out: dict[str, Any] = {}
    if base_uri:
        out[_XPATH_BASE_URI_PARAM] = base_uri
    if documents:
        out[_XPATH_DOCUMENTS_PARAM] = documents
    if collections:
        out[_XPATH_COLLECTIONS_PARAM] = collections
    if variables:
        out[_XPATH_VARIABLES_PARAM] = variables
    if namespaces:
        out[_XPATH_NAMESPACES_PARAM] = namespaces
    if root is not None:
        out[_XPATH_ROOT_PARAM] = root
    return out


def _xpath_base_uri(params: dict | None) -> str | None:
    if not params:
        return None
    value = params.get(_XPATH_BASE_URI_PARAM)
    return str(value) if value else None


def _xpath_documents(params: dict | None) -> dict[str, Any] | None:
    if not params:
        return None
    value = params.get(_XPATH_DOCUMENTS_PARAM)
    return value if isinstance(value, dict) else None


def _xpath_collections(params: dict | None) -> dict[str, list] | None:
    if not params:
        return None
    value = params.get(_XPATH_COLLECTIONS_PARAM)
    return value if isinstance(value, dict) else None


def _xpath_variables(params: dict | None) -> dict[str, Any] | None:
    if not params:
        return None
    value = params.get(_XPATH_VARIABLES_PARAM)
    return value if isinstance(value, dict) else None


def _xpath_config_namespaces(params: dict | None) -> dict[str, str] | None:
    if not params:
        return None
    value = params.get(_XPATH_NAMESPACES_PARAM)
    return value if isinstance(value, dict) else None


def _merged_namespaces(
    params: dict | None,
    namespaces: dict[str, str] | None,
) -> dict[str, str] | None:
    """Union the ODD's NSMAP with ``[transform.namespaces]``; config wins on clash.

    Prefixes used by XPath inside ODD attribute values are not XML names, so the
    ODD root cannot be the only place they may be declared — a project has to be
    able to bind them (variable prefixes above all) without editing the ODD.
    """
    config_ns = _xpath_config_namespaces(params)
    if not config_ns:
        return namespaces
    merged = dict(namespaces or {})
    merged.update(config_ns)
    return merged


def _xpath_view_root(
    params: dict | None,
    node: 'etree._Element',
) -> 'etree._Element' | None:
    """Node bound as ``$parameters?root``, or ``None`` to keep a string ``root``."""
    if params:
        explicit = params.get(_XPATH_ROOT_PARAM)
        if isinstance(explicit, etree._Element):
            return explicit
        if 'root' in params:
            return None
    return node.getroottree().getroot()


def clear_xpath_document_cache() -> None:
    """Drop cached elementpath document trees (e.g. between tests or documents)."""
    _document_xpath_roots.clear()
    _params_map_with_root_cache.clear()
    _compiled_xpath.cache_clear()
    _loaded_extension_callables.cache_clear()
    _cached_parameters_map.cache_clear()


def make_context(node: etree._Element, params: dict | None = None) -> XPathContext:
    """XPathContext with document root, context item *node*, and ``$parameters`` bound.

    Runtime options are passed as an XPath 3.1 map via ``variables`` so predicate
    strings from the ODD can use ``$parameters?key`` without rewriting the expression.

    ``$parameters?root`` is the viewed node in the original document
    (tei-publisher-lib). Callers pass it via :func:`xpath_runtime_context`
    ``root=``; otherwise it defaults to the document element of *node* so
    ``root($parameters?root)`` still works. An explicit string ``root`` key in
    *params* is left as a string (no node is injected).

    The document node tree and parameters map are cached; only XPathContext itself is
    constructed fresh each call (it is lightweight — the expensive parts are cached).
    """
    tree_root = node.getroottree().getroot()
    base_uri = _xpath_base_uri(params)
    wrapped = _xpath_root_wrapped(tree_root, base_uri)
    params_key = _params_cache_key(params)
    view_root = _xpath_view_root(params, node)
    if view_root is None:
        pmap = _cached_parameters_map(params_key)
    else:
        pmap = _parameters_map_with_root(params_key, view_root, base_uri)
    # ODD-declared variables (e.g. $global:register-root) sit alongside
    # $parameters; a config key never shadows the parameters map.
    variables: dict[str, Any] = {'parameters': pmap}
    extra_variables = _xpath_variables(params)
    if extra_variables:
        for name, value in extra_variables.items():
            if name != 'parameters':
                variables[name] = value

    documents = _xpath_documents(params)
    if view_root is not None:
        view_tree_root = view_root.getroottree().getroot()
        if view_tree_root is not tree_root:
            # Chunking transforms a synthetic copy of the page, while
            # $parameters?root still points into the original document. The two
            # are separate lxml trees, and XPathContext.get_root() searches only
            # the context root's tree and `documents` — so without registering
            # the source document here, root($parameters?root) is the empty
            # sequence. teipublisher.odd reaches the teiHeader through exactly
            # that expression (page titles, facsimile links, static page links),
            # so every one of those models silently degrades on chunk output.
            # _xpath_root_wrapped is cached, so this is the same wrapped tree the
            # $parameters map took its root node from — get_root() compares by
            # identity and would not match a second, equal-but-distinct wrapper.
            documents = dict(documents) if documents else {}
            documents.setdefault(
                base_uri or '', _xpath_root_wrapped(view_tree_root, base_uri),
            )

    return XPathContext(
        root=wrapped,  # type: ignore[arg-type]
        item=wrapped.elements[node],  # type: ignore[union-attr,index]
        variables=variables,
        documents=documents,
        collections=_xpath_collections(params),
    )


def _normalize_xpath_extensions(xpath_extensions: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not xpath_extensions:
        return ()
    if isinstance(xpath_extensions, str):
        mod = xpath_extensions.strip()
        return (mod,) if mod else ()
    out: list[str] = []
    for mod in xpath_extensions:
        cleaned = str(mod).strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def _extension_fingerprint(xpath_extensions: str | list[str] | tuple[str, ...] | None) -> str:
    modules = _normalize_xpath_extensions(xpath_extensions)
    if not modules:
        return ''
    # Separator does not appear in module paths; each item keeps its own mtime fingerprint.
    return '\x1f'.join(fingerprint_for_module(module) for module in modules)


def xpath_test(
    node: etree._Element,
    expr: str,
    params: dict | None = None,
    *,
    xpath_extensions: str | list[str] | tuple[str, ...] | None = None,
    namespaces: dict[str, str] | None = None,
) -> bool:
    """Boolean XPath 3.1 test against *node* (ODD @predicate strings)."""
    try:
        ext_fp = _extension_fingerprint(xpath_extensions)
        merged_ns = _merged_namespaces(params, namespaces)
        ns_key = frozenset(merged_ns.items()) if merged_ns else None
        base_uri = _xpath_base_uri(params)
        token = _compiled_xpath(
            expr,
            _default_element_namespace_uri(node),
            ext_fp,
            ns_key,
            base_uri,
        )
        result = list(token.select(make_context(node, params)))
        if not result:
            return False
        if len(result) == 1 and isinstance(result[0], bool):
            return result[0]
        return True
    except elementpath.ElementPathError:
        return False


def xpath_count(
    node: etree._Element,
    expr: str,
    params: dict | None = None,
    *,
    xpath_extensions: str | list[str] | tuple[str, ...] | None = None,
    namespaces: dict[str, str] | None = None,
) -> int:
    """Count nodes matched by *expr* from *node* (sequence length), not ``count()`` in XPath."""
    try:
        ext_fp = _extension_fingerprint(xpath_extensions)
        merged_ns = _merged_namespaces(params, namespaces)
        ns_key = frozenset(merged_ns.items()) if merged_ns else None
        base_uri = _xpath_base_uri(params)
        token = _compiled_xpath(
            expr,
            _default_element_namespace_uri(node),
            ext_fp,
            ns_key,
            base_uri,
        )
        return len(list(token.select(make_context(node, params))))
    except elementpath.ElementPathError:
        return 0


def _unwrap_singleton_xpath_result(result: list):
    """If *expr* yields one atomic (e.g. ``count(...)``), return it; else keep a list."""
    if len(result) != 1:
        return result
    return result[0]


def _xpath_raw_to_pipeline_values(raw: list) -> list:
    """Map elementpath results to values :func:`~opm.output_functions.normalize`
    and :func:`apply_children` understand.

    ``token.select`` returns :class:`~elementpath.xpath_nodes.XPathNode` wrappers around
    elements; those must become lxml elements or text is dropped when building HTML.
    Attribute and other XPath nodes unwrap to their Python ``.value``.
    """
    out: list = []
    for item in raw:
        if isinstance(item, XPathNode):
            out.append(item.value)
        else:
            out.append(item)
    return out


def xpath_select_nodes(
    node: etree._Element,
    expr: str,
    params: dict | None = None,
    *,
    xpath_extensions: str | list[str] | tuple[str, ...] | None = None,
    namespaces: dict[str, str] | None = None,
):
    """Evaluate XPath *expr* with *node* as context.

    Returns a list of nodes (possibly one) for path expressions, or a single atomic
    for expressions like ``count(ancestor::div)`` / ``string(.)``.
    """
    try:
        ext_fp = _extension_fingerprint(xpath_extensions)
        merged_ns = _merged_namespaces(params, namespaces)
        ns_key = frozenset(merged_ns.items()) if merged_ns else None
        base_uri = _xpath_base_uri(params)
        token = _compiled_xpath(
            expr,
            _default_element_namespace_uri(node),
            ext_fp,
            ns_key,
            base_uri,
        )
        raw = list(token.select(make_context(node, params)))
        raw = _xpath_raw_to_pipeline_values(raw)
        return _unwrap_singleton_xpath_result(raw)
    except elementpath.ElementPathError:
        return []


def xpath_select_nodes_or_node(
    node: etree._Element,
    expr: str,
    params: dict | None = None,
    *,
    xpath_extensions: str | list[str] | tuple[str, ...] | None = None,
    namespaces: dict[str, str] | None = None,
):
    """Like :func:`xpath_select_nodes`, but returns *node* when *expr* is unconfigured.

    Used for ODD params that reference ``collection()`` or an external variable
    (``$global:register-root`` and friends). Those resolve only when the project
    supplies ``[[transform.collections]]`` / ``[transform.variables.<ns>]`` /
    ``[transform.namespaces]``. Without that configuration the expression raises
    — unbound prefix, unbound variable, or an unknown collection URI — and the
    historical behaviour was to fall back to the context node, which the bundled
    teipublisher.odd still relies on for its in-document listPerson register.

    Only those three "not configured here" errors fall back. Any other XPath
    error keeps :func:`xpath_select_nodes` semantics (an empty sequence), so a
    genuinely broken expression is not silently replaced by the whole element.
    """
    try:
        ext_fp = _extension_fingerprint(xpath_extensions)
        merged_ns = _merged_namespaces(params, namespaces)
        ns_key = frozenset(merged_ns.items()) if merged_ns else None
        token = _compiled_xpath(
            expr,
            _default_element_namespace_uri(node),
            ext_fp,
            ns_key,
            _xpath_base_uri(params),
        )
        raw = _xpath_raw_to_pipeline_values(list(token.select(make_context(node, params))))
        return _unwrap_singleton_xpath_result(raw)
    except elementpath.ElementPathError as exc:
        # XPST0081 unbound prefix / XPST0008 unbound variable / FODC0002 unknown
        # collection all mean "this project did not configure it".
        if any(code in str(exc) for code in ('XPST0081', 'XPST0008', 'FODC0002')):
            return node
        return []


def resolve_context_element(
    document_root: etree._Element,
    xpath_expr: str,
    params: dict | None = None,
    *,
    xpath_extensions: str | list[str] | tuple[str, ...] | None = None,
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
        ext_fp = _extension_fingerprint(xpath_extensions)
        base_uri = _xpath_base_uri(params)
        token = _compiled_xpath(
            xpath_expr,
            _default_element_namespace_uri(document_root),
            ext_fp,
            base_uri=base_uri,
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
        elif isinstance(item, etree._Element):
            result = etree.tostring(item, encoding='utf-8', method='html')
            if isinstance(result, bytes):
                result = result.decode('utf-8')
            parent_el.append(result)
        return
    if isinstance(item, str):
        if len(parent_el) == 0:
            parent_el.text = (parent_el.text or '') + item
        else:
            last = parent_el[-1]
            last.tail = (last.tail or '') + item
    elif isinstance(item, etree._Element):
        parent_el.append(item)


def apply_children(config, source_node, content, parent_el) -> None:
    norm = config.get('normalize_text')
    text_escape = config.get('text_escape')
    for item in normalize(content):
        if isinstance(item, str):
            text = maybe_normalize_text(item, norm)
            if text_escape and not isinstance(item, TemplateOutput):
                text = text_escape(text)
            append_to(parent_el, text)
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
    norm = config.get('normalize_text')
    text_escape = config.get('text_escape')
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
    dispatch = config['dispatch']
    params = config.get('parameters', {})
    norm = config.get('normalize_text')
    text_escape = config.get('text_escape')
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


def inject_cached_footnotes(nodes: list, config: dict) -> list:
    """Append footnote bodies collected in ``config['footnotes']`` after the main flow.

    HTML: :class:`~opm.html_output_functions.HtmlOutputFunctions` stores
    ``dl.footnote`` elements. Markdown: stores reference-definition strings.
    """
    footnotes = config.get('footnotes')
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
