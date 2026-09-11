# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Evaluate ODD XPath against a document, with everything it depends on bound once.

An :class:`XPathEnvironment` holds what an expression may reach beyond the node
it is evaluated on: the source document's URI, the documents and collections
``doc()`` and ``collection()`` can open, project variables and namespace
prefixes, the ``tp:`` extension modules, the ``$parameters`` map, and the node
bound as ``$parameters?root``. It is built once per transform run. All of this
used to travel inside the ``$parameters`` dict under reserved keys and was
re-derived for every predicate: extension fingerprints, merged namespaces and
the parameters cache key are now computed when the environment is made.

The environment also owns the per-document caches — the elementpath node tree
wrapped around each lxml document, the ``$parameters`` maps, the index
``fn:id()`` answers from — so they are freed with the run instead of accumulating in
module globals for the life of the process. :meth:`XPathEnvironment.with_root`
and :meth:`XPathEnvironment.with_parameters` return cheap views sharing those
caches, which is how a chunked document binds each chunk's source node without
rebuilding anything.

Parsed expressions stay in a bounded module-level cache (:func:`compiled_xpath`):
they depend on strings only, never on a document.
"""

from __future__ import annotations

from contextvars import ContextVar
from functools import lru_cache
from typing import Any

import elementpath
from elementpath import XPathContext
from elementpath.tree_builders import get_node_tree
from elementpath.xpath_nodes import XPathNode
from elementpath.xpath31.xpath31_parser import XPath31Parser
from lxml import etree

from . import source_map
from .xpath_diagnostics import record_xpath_error
from .xpath_extensions import (
    build_extension_parser,
    fingerprint_for_module,
    load_extension_callables,
)
from .xpath_parser import IdIndex, build_id_index

#: Errors that mean "this project did not configure it": an unbound prefix, an
#: unbound variable, an unknown collection. See :meth:`XPathEnvironment.select_or_node`.
UNCONFIGURED_CODES = ('XPST0081', 'XPST0008', 'FODC0002')

# Minimal tree used only to parse ``map{...}`` into an XPathMap for ``$parameters``.
_PARAM_PARSE_ROOT = etree.fromstring(b'<e/>')
_PARAM_PARSE_CTX = XPathContext(
    root=_PARAM_PARSE_ROOT,  # type: ignore[arg-type]
    item=_PARAM_PARSE_ROOT,  # type: ignore[arg-type]
)

_CURRENT: ContextVar[XPathEnvironment | None] = ContextVar(
    'opm_xpath_environment', default=None,
)


def current_environment() -> XPathEnvironment | None:
    """The environment evaluating the expression that is running right now.

    For functions that need the run's caches while XPath runs, such as
    ``fn:id()`` and ``tp:source-node``. ``None`` outside an evaluation.
    """
    return _CURRENT.get()


# ── the $parameters map ──────────────────────────────────────────────────────


def _xpath_string_literal(s: str) -> str:
    """Single-quoted XPath string with '' escaping."""
    return "'" + s.replace("'", "''") + "'"


def params_cache_key(params: dict | None) -> tuple[tuple[str, str], ...]:
    """Hashable, order-independent form of a ``$parameters`` dict."""
    if not params:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in params.items()))


def _map_literal(params_key: tuple[tuple[str, str], ...], *extra: str) -> str:
    parts = [
        f'{_xpath_string_literal(k)}: {_xpath_string_literal(v)}' for k, v in params_key
    ]
    parts.extend(extra)
    return 'map{' + ', '.join(parts) + '}'


@lru_cache(maxsize=256)
def _parameters_map(params_key: tuple[tuple[str, str], ...]):
    """``$parameters`` without a ``root`` node; one XPathMap per distinct dict."""
    token = XPath31Parser().parse(_map_literal(params_key))
    return list(token.select(_PARAM_PARSE_CTX))[0]


def _parameters_map_with_root(params_key, root: etree._Element, wrapped_doc) -> Any:
    """``$parameters`` with *root* bound as the ``root`` entry.

    Built with ``"root": .`` evaluated on *root* itself, so the entry is a real
    node of *wrapped_doc* rather than a Python value: ``root($parameters?root)``
    then reaches the document it came from.
    """
    token = XPath31Parser().parse(_map_literal(params_key, '"root": .'))
    ctx = XPathContext(root=wrapped_doc, item=wrapped_doc.elements[root])  # type: ignore[arg-type,index]
    return list(token.select(ctx))[0]


# ── parsing ──────────────────────────────────────────────────────────────────


def default_element_namespace_uri(node: etree._Element) -> str:
    """Namespace URI used for unprefixed element names in XPath.

    XPath 3.1 binds unqualified names to this URI; TEI ``div`` lives in
    ``http://www.tei-c.org/ns/1.0``, not the empty namespace, so ``parent::div``
    only matches after setting this. Empty string means no default.
    """
    if isinstance(node, (etree._Comment, etree._ProcessingInstruction, etree._Entity)):
        return ''
    return etree.QName(node).namespace or ''


def _xpath_source_node(node):
    """``tp:source-node(x)`` — the stored-document node *x* was copied from.

    What ``$get(x)`` in a tei-publisher ODD compiles to. Inside a chunk the
    context node belongs to a rebuilt, detached tree, so document-order axes
    would see only that page; resolving to the source node first is what makes
    ``count($get(.)/preceding::pb) + 1`` count pages across the whole document.

    Returns a node from the environment's wrapped source tree (not a bare lxml
    element): elementpath rejects an atomic value as an intermediate path step,
    so ``$get(.)/preceding::pb`` would raise XPTY0019. Outside chunking nothing
    is recorded and the argument comes back untouched, which is the identity
    behaviour ``$get`` has on a whole document.
    """
    el = node.value if isinstance(node, XPathNode) else node
    if not isinstance(el, etree._Element):
        return node
    source = source_map.source_of(el)
    env = current_environment()
    if source is None or source is el or env is None:
        return node
    try:
        return env.wrapped(source).elements[source]  # type: ignore[union-attr,index]
    except (KeyError, TypeError):
        return node


# Registered on every parser, so an ODD may use $get() without the project
# having to configure any XPath extension module.
_BUILTIN_XPATH_CALLABLES = {'source-node': _xpath_source_node}


@lru_cache(maxsize=64)
def _loaded_extension_callables(ext_fp: str) -> dict:
    """Map a fingerprint string to the merged callables of its modules."""
    merged: dict = {}
    # ext_fp is one or more module fingerprints joined by '\x1f'.
    for item in ext_fp.split('\x1f'):
        module_path = item.split('\0', 1)[0]
        merged.update(load_extension_callables(module_path))
    return merged


@lru_cache(maxsize=8192)
def compiled_xpath(
    expr: str,
    default_element_ns: str = '',
    ext_fp: str = '',
    namespaces: frozenset[tuple[str, str]] | None = None,
    base_uri: str | None = None,
):
    """Parse each distinct expression and static context once."""
    callables = dict(_BUILTIN_XPATH_CALLABLES)
    if ext_fp:
        # A project extension of the same name wins over the built-in.
        callables.update(_loaded_extension_callables(ext_fp))
    parser = build_extension_parser(
        default_element_ns,
        callables,
        namespaces=dict(namespaces) if namespaces else {},
        base_uri=base_uri,
    )
    return parser.parse(expr)


def normalize_extensions(extensions) -> tuple[str, ...]:
    """Extension modules as a tuple of non-empty dotted paths."""
    if not extensions:
        return ()
    if isinstance(extensions, str):
        extensions = (extensions,)
    return tuple(m for m in (str(mod).strip() for mod in extensions) if m)


def extension_fingerprint(extensions: tuple[str, ...]) -> str:
    """Cache-key fragment for *extensions*: module paths plus source mtimes."""
    if not extensions:
        return ''
    # The separator does not appear in module paths.
    return '\x1f'.join(fingerprint_for_module(module) for module in extensions)


def _pipeline_values(raw: list) -> list:
    """Unwrap elementpath node wrappers to the lxml elements the pipeline handles.

    Attribute and other XPath nodes unwrap to their Python ``.value``.
    """
    return [item.value if isinstance(item, XPathNode) else item for item in raw]


def _unwrap_singleton(result: list):
    """One atomic (``count(...)``) or node comes back bare; anything else as a list."""
    return result[0] if len(result) == 1 else result


# ── caches ───────────────────────────────────────────────────────────────────


class DocumentCache:
    """Wrapped node trees, ``$parameters`` maps and xml:id indexes for one run.

    Keyed by the lxml element object, never by ``id()``: lxml recycles proxy
    objects, so ids collide across nodes (see :mod:`opm.runtime.source_map`).
    A wrapped tree keeps its document alive, so an entry stays valid for as
    long as the cache — and with it the run's environment — exists.
    """

    __slots__ = ('trees', 'parameter_maps', 'id_indexes')

    def __init__(self) -> None:
        self.trees: dict[tuple, Any] = {}
        self.parameter_maps: dict[tuple, Any] = {}
        # Keyed by id() of the root node, which the entry keeps alive.
        self.id_indexes: dict[int, tuple[XPathNode, IdIndex]] = {}

    def tree(self, doc_root: etree._Element, base_uri: str | None):
        key = (doc_root, base_uri)
        hit = self.trees.get(key)
        if hit is None:
            hit = get_node_tree(doc_root.getroottree(), uri=base_uri)  # type: ignore[arg-type]
            self.trees[key] = hit
        return hit


# ── the environment ──────────────────────────────────────────────────────────


class XPathEnvironment:
    """Everything an ODD expression can see beyond its context node.

    Args:
        base_uri: URI of the source document; ``document-uri()`` and relative
            ``doc()`` arguments resolve against it.
        documents: ``doc()`` targets by absolute URI, already wrapped (see
            :func:`opm.transform.load_xpath_documents`).
        collections: ``collection()`` members by URI.
        variables: XPath variables, keys in Clark notation (``{ns}local``).
        namespaces: Project prefixes (``[transform.namespaces]``); they win
            over the ODD's own declarations, see :meth:`for_odd`.
        extensions: Dotted module paths whose public callables become ``tp:``
            functions.
        parameters: Bound as ``$parameters``.
        root: Bound as ``$parameters?root``. ``None`` binds the document element
            of the context node, unless *parameters* has a ``root`` of its own.
        cache: Shared document caches; a fresh one by default.
    """

    __slots__ = (
        'base_uri', 'documents', 'collections', 'variables',
        'project_namespaces', 'odd_namespaces', 'extensions', 'parameters', 'root',
        '_cache', '_ext_fp', '_ns_key', '_params_key',
    )

    def __init__(
        self,
        *,
        base_uri: str | None = None,
        documents: dict[str, Any] | None = None,
        collections: dict[str, list] | None = None,
        variables: dict[str, Any] | None = None,
        namespaces: dict[str, str] | None = None,
        extensions=None,
        parameters: dict[str, Any] | None = None,
        root: etree._Element | None = None,
        cache: DocumentCache | None = None,
    ) -> None:
        self.base_uri = base_uri or None
        self.documents: dict[str, Any] = documents or {}
        self.collections: dict[str, list] = collections or {}
        self.variables: dict[str, Any] = dict(variables) if variables else {}
        self.project_namespaces: dict[str, str] = dict(namespaces) if namespaces else {}
        self.odd_namespaces: dict[str, str] = {}
        self.extensions = normalize_extensions(extensions)
        self.parameters: dict[str, Any] = dict(parameters) if parameters else {}
        self.root = root
        self._cache = cache if cache is not None else DocumentCache()
        self._ext_fp = extension_fingerprint(self.extensions)
        self._ns_key = self._namespaces_key(self.odd_namespaces, self.project_namespaces)
        self._params_key = params_cache_key(self.parameters)

    # ── views ───────────────────────────────────────────────────────────────

    @staticmethod
    def _namespaces_key(odd: dict, project: dict) -> frozenset | None:
        merged = {**odd, **project}
        return frozenset(merged.items()) if merged else None

    def _view(self, **changes) -> XPathEnvironment:
        view = object.__new__(XPathEnvironment)
        for name in XPathEnvironment.__slots__:
            object.__setattr__(view, name, getattr(self, name))
        for name, value in changes.items():
            object.__setattr__(view, name, value)
        return view

    def with_root(self, root: etree._Element | None) -> XPathEnvironment:
        """A view binding *root* as ``$parameters?root``."""
        return self._view(root=root)

    def with_parameters(self, parameters: dict[str, Any] | None) -> XPathEnvironment:
        """A view binding *parameters* as ``$parameters``."""
        params = dict(parameters) if parameters else {}
        return self._view(parameters=params, _params_key=params_cache_key(params))

    def for_odd(self, odd_namespaces: dict[str, str] | None) -> XPathEnvironment:
        """A view adding the prefixes the ODD root declares.

        Prefixes in XPath inside ODD attribute values are not XML names, so the
        ODD cannot be the only place to declare them: project prefixes win on a
        clash, and bind what the ODD leaves out (variable prefixes above all).
        """
        odd = dict(odd_namespaces) if odd_namespaces else {}
        return self._view(
            odd_namespaces=odd,
            _ns_key=self._namespaces_key(odd, self.project_namespaces),
        )

    @property
    def namespaces(self) -> dict[str, str]:
        """The prefixes in effect: the ODD's, overridden by the project's."""
        return {**self.odd_namespaces, **self.project_namespaces}

    # ── documents ───────────────────────────────────────────────────────────

    def wrapped(self, node: etree._Element):
        """The elementpath document node for *node*'s tree, built once per run.

        The base URI is attached to the document node, which is what makes
        ``document-uri()`` and ``base-uri()`` return the source file rather than
        the empty sequence. The parser's static base URI is a separate thing:
        it resolves relative arguments to ``doc()`` and ``collection()`` but
        never reaches the tree, so both are supplied.
        """
        return self._cache.tree(node.getroottree().getroot(), self.base_uri)

    def id_index(self, root: XPathNode) -> IdIndex:
        """``fn:id()``'s index of the node tree under *root*, built once per run.

        See :func:`~opm.runtime.xpath_parser.build_id_index`.
        """
        hit = self._cache.id_indexes.get(id(root))
        if hit is None:
            hit = (root, build_id_index(root))
            self._cache.id_indexes[id(root)] = hit
        return hit[1]

    # ── evaluation ──────────────────────────────────────────────────────────

    def compile(self, expr: str, node: etree._Element):
        """The parsed expression for *expr* in the static context of *node*."""
        return compiled_xpath(
            expr, default_element_namespace_uri(node), self._ext_fp, self._ns_key, self.base_uri,
        )

    def _view_root(self, node: etree._Element) -> etree._Element | None:
        """Node bound as ``$parameters?root``, or ``None`` to keep a string ``root``."""
        if self.root is not None:
            return self.root
        if 'root' in self.parameters:
            return None
        return node.getroottree().getroot()

    def context(self, node: etree._Element) -> XPathContext:
        """An XPathContext with *node* as context item and everything else bound.

        ``$parameters?root`` is the viewed node in the original document
        (tei-publisher-lib). An explicit string ``root`` in the parameters is
        left as a string.
        """
        tree_root = node.getroottree().getroot()
        wrapped = self.wrapped(tree_root)
        view_root = self._view_root(node)
        if view_root is None:
            pmap = _parameters_map(self._params_key)
        else:
            key = (self._params_key, view_root, self.base_uri)
            pmap = self._cache.parameter_maps.get(key)
            if pmap is None:
                pmap = _parameters_map_with_root(
                    self._params_key, view_root, self.wrapped(view_root),
                )
                self._cache.parameter_maps[key] = pmap
        # ODD-declared variables (e.g. $global:register-root) sit alongside
        # $parameters; a project variable never shadows the parameters map.
        variables: dict[str, Any] = {'parameters': pmap}
        for name, value in self.variables.items():
            if name != 'parameters':
                variables[name] = value

        documents: dict[str, Any] | None = self.documents or None
        if view_root is not None:
            view_tree_root = view_root.getroottree().getroot()
            if view_tree_root is not tree_root:
                # Chunking transforms a synthetic copy of the page, while
                # $parameters?root still points into the original document. The
                # two are separate lxml trees, and XPathContext.get_root() only
                # searches the context root's tree and `documents` — so without
                # registering the source document, root($parameters?root) is the
                # empty sequence, and every model reaching the teiHeader through
                # it (page titles, facsimile links) degrades on chunk output.
                # The wrapper is the cached one the parameters map took its root
                # from: get_root() compares by identity.
                documents = dict(documents) if documents else {}
                documents.setdefault(self.base_uri or '', self.wrapped(view_tree_root))

        return XPathContext(
            root=wrapped,  # type: ignore[arg-type]
            item=wrapped.elements[node],  # type: ignore[union-attr,index]
            variables=variables,
            documents=documents,
            collections=self.collections or None,
        )

    def evaluate(self, node: etree._Element, expr: str) -> list:
        """Raw elementpath results; raises :class:`elementpath.ElementPathError`."""
        token = self.compile(expr, node)
        context = self.context(node)
        reset = _CURRENT.set(self)
        try:
            return list(token.select(context))
        finally:
            _CURRENT.reset(reset)

    def test(self, node: etree._Element, expr: str) -> bool:
        """Boolean test for an ODD ``@predicate``; an error counts as false."""
        try:
            result = self.evaluate(node, expr)
        except elementpath.ElementPathError as exc:
            record_xpath_error(expr, exc, node, self.base_uri)
            return False
        if not result:
            return False
        if len(result) == 1 and isinstance(result[0], bool):
            return result[0]
        return True

    def count(self, node: etree._Element, expr: str) -> int:
        """Length of the sequence *expr* selects; an error counts as zero."""
        try:
            return len(self.evaluate(node, expr))
        except elementpath.ElementPathError as exc:
            record_xpath_error(expr, exc, node, self.base_uri)
            return 0

    def select(self, node: etree._Element, expr: str):
        """Evaluate a param ``@value``: nodes as a list, a lone item bare.

        ``count(ancestor::div)`` or ``string(.)`` give a single atomic; a path
        gives lxml elements. An error gives the empty sequence.
        """
        try:
            return _unwrap_singleton(_pipeline_values(self.evaluate(node, expr)))
        except elementpath.ElementPathError as exc:
            record_xpath_error(expr, exc, node, self.base_uri)
            return []

    def select_all(self, node: etree._Element, expr: str) -> list:
        """Like :meth:`select`, but always a list."""
        try:
            return _pipeline_values(self.evaluate(node, expr))
        except elementpath.ElementPathError as exc:
            record_xpath_error(expr, exc, node, self.base_uri)
            return []

    def select_or_node(self, node: etree._Element, expr: str):
        """Like :meth:`select`, but *node* itself when *expr* is unconfigured.

        Used for ODD params that read ``collection()`` or an external variable
        (``$global:register-root`` and friends), which resolve only once the
        project configures them. Without that configuration the expression
        raises one of :data:`UNCONFIGURED_CODES`, and the fallback to the
        context node is what the bundled teipublisher.odd relies on for its
        in-document listPerson register. Any other error gives the empty
        sequence, so a broken expression is not replaced by the whole element.
        """
        try:
            return _unwrap_singleton(_pipeline_values(self.evaluate(node, expr)))
        except elementpath.ElementPathError as exc:
            message = str(exc)
            if 'XPST0081' not in message:
                # An undeclared prefix means the ODD never opted in to project
                # variables (see PythonGenerator._param_tier_ok), and falling
                # back is then intended, not something to report. A declared
                # prefix with no value or collection behind it is.
                record_xpath_error(expr, exc, node, self.base_uri)
            if any(code in message for code in UNCONFIGURED_CODES):
                return node
            return []

    def resolve_element(self, document_root: etree._Element, expr: str) -> etree._Element:
        """The one element *expr* selects with *document_root* as context.

        Raises:
            ValueError: *expr* is invalid, or does not select exactly one element.
        """
        try:
            raw = self.evaluate(document_root, expr)
        except elementpath.ElementPathError as e:
            raise ValueError(f'Invalid XPath: {e}') from e
        elements = [
            item for item in _pipeline_values(raw) if isinstance(item, etree._Element)
        ]
        if len(elements) != 1:
            raise ValueError(
                f'XPath {expr!r} must select exactly one element; '
                f'got {len(elements)} element(s) from {len(raw)} value(s)',
            )
        return elements[0]


def clear_compiled_xpath_cache() -> None:
    """Drop parsed expressions and loaded extension modules (e.g. between tests)."""
    compiled_xpath.cache_clear()
    _loaded_extension_callables.cache_clear()
    _parameters_map.cache_clear()
