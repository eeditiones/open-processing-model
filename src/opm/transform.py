"""Core transform API — import this to drive transforms from your own Python scripts.

Three entry points at increasing levels of abstraction:

``run_transform(mod, element, ...)``
    Lowest level. Caller supplies an already-loaded module and an already-selected
    lxml element; the function serializes and optionally wraps the result in the
    Jinja2 document template::

        from opm.odd_cache import ensure_compiled_module
        from opm.transform import load_transform_module, run_transform
        from lxml import etree

        path, _ = ensure_compiled_module(Path('odd/teipublisher.odd'))
        mod = load_transform_module(path)
        root = etree.parse('document.xml').getroot()

        html     = run_transform(mod, root)                 # full document
        fragment = run_transform(mod, root.find('.//{*}div'))  # single element

``transform_node(script_path, root, *, xpath=None, ...)``
    Mid level. Loads the module from *script_path* and, if *xpath* is given,
    selects the target element before transforming::

        from opm.odd_cache import ensure_compiled_module
        from opm.transform import transform_node
        from lxml import etree

        path, _ = ensure_compiled_module(Path('odd/teipublisher.odd'))
        root = etree.parse('document.xml').getroot()
        html = transform_node(path, root, xpath='//body/div[1]')

``transform_file(module_path, xml_path, *, xpath=None, ...)``
    Highest level. Also parses the XML file and reads ``opm.toml``
    for defaults (extensions, webcomponents, template)::

        from opm.odd_cache import ensure_compiled_module
        from opm.transform import transform_file

        path, _ = ensure_compiled_module(Path('odd/teipublisher.odd'))
        html = transform_file(path, Path('document.xml'), xpath='//body/div[1]')

``xpath_select(root, expr, ...)``
    Utility for evaluating XPath against a parsed document without any
    namespace bookkeeping — unprefixed names automatically match the
    document's namespace::

        from opm.transform import xpath_select
        from lxml import etree

        root = etree.parse('document.xml').getroot()
        chapters = xpath_select(root, '//body/div')
"""

from __future__ import annotations

import importlib.util
from types import ModuleType
from pathlib import Path
from typing import Any, Sequence

from elementpath.tree_builders import get_node_tree
from lxml import etree

from opm.config import (
    DEFAULT_CDN_TEMPLATE,
    DEFAULT_VERSION,
    CollectionConfig,
    ProjectConfig,
    load_project_config,
)
from opm.runtime.pm_runtime import resolve_context_element, xpath_runtime_context
from opm.runtime.pm_runtime import serialize as _default_serialize
from opm.template_rendering import (
    DEFAULT_TYPST_TEMPLATE_NAME,
    render_document_template,
    render_typst_document_template,
    resolve_template_path,
)


def load_transform_module(script_path: Path) -> ModuleType:
    """Load a ``.py`` file that defines ``transform()`` and ``transform_output_channels()``."""
    path = script_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Not a file: {path}')
    name = f'tei_transform_{path.stem}'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load module from {path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, 'transform'):
        raise AttributeError(
            f'{path} has no transform() — expected a TEI Publisher transform module',
        )
    if not hasattr(mod, 'transform_output_channels'):
        raise AttributeError(
            f'{path} has no transform_output_channels() — expected a compiled ODD transform module',
        )
    return mod


def xpath_select(
    root: etree._Element,
    expr: str,
    params: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    xpath_base_uri: str | None = None,
    xpath_documents: dict[str, Any] | None = None,
    xpath_collections: dict[str, list] | None = None,
    xpath_variables: dict[str, Any] | None = None,
    xpath_namespaces: dict[str, str] | None = None,
) -> list:
    """Evaluate XPath 3.1 *expr* against *root*, returning a plain list.

    The document's default namespace URI (taken from *root*'s ``nsmap``) is set
    as the XPath default element namespace, so unprefixed element names match
    without any prefix mapping::

        chapters = xpath_select(root, '//body/div')          # TEI, DocBook, …
        titles   = xpath_select(root, '//div/head/string()')  # atomic results

    Element results are returned as lxml :class:`~lxml.etree._Element` objects.
    Atomic expressions (``count(…)``, ``string(…)``) return the corresponding
    Python scalar.

    Args:
        root: Document root element; its namespace determines the default element namespace.
        expr: XPath 3.1 expression with unprefixed element names.
        params: Values bound as the XPath ``$parameters`` map.
        xpath_extensions: Dotted module paths for custom XPath functions in the ``tp:`` namespace.
    """
    from opm.runtime.pm_runtime import xpath_select_nodes  # noqa: PLC0415

    effective_params: dict[str, Any] = dict(params or {})
    effective_params.update(
        xpath_runtime_context(
            base_uri=xpath_base_uri,
            documents=xpath_documents,
            collections=xpath_collections,
            variables=xpath_variables,
            namespaces=xpath_namespaces,
        ),
    )
    result = xpath_select_nodes(
        root,
        expr,
        effective_params or None,
        xpath_extensions=tuple(xpath_extensions) if xpath_extensions else None,
    )
    # xpath_select_nodes unwraps a single-item list to a scalar; normalise back to list
    return result if isinstance(result, list) else [result]


def load_xpath_documents(paths: Sequence[Path]) -> dict[str, Any]:
    """Parse configured XPath documents keyed by their absolute file URI.

    Each tree is wrapped in its elementpath node tree once, here, rather than
    left as a bare ``_ElementTree``. ``XPathContext.__init__`` runs
    ``get_node_tree()`` over every entry of ``documents`` on *each*
    construction, and for a bare lxml tree that means a full
    ``build_lxml_node_tree()`` walk every time — with a context built per
    ``doc()``-using predicate, the register documents were being re-wrapped
    thousands of times per chunked file. ``get_node_tree()`` short-circuits on
    an already-wrapped ``DocumentNode``, so pre-wrapping turns that back into a
    dict lookup. Mirrors what ``_xpath_root_wrapped()`` does for the main root.
    """
    documents: dict[str, Any] = {}
    for path in paths:
        resolved = path.resolve()
        uri = resolved.as_uri()
        documents[uri] = get_node_tree(etree.parse(str(resolved)), None, uri)
    return documents


def load_xpath_collections(
    collections: Sequence[CollectionConfig],
    documents: dict[str, Any] | None = None,
) -> tuple[dict[str, list], dict[str, Any]]:
    """Return ``(collections, documents)`` maps for the XPath dynamic context.

    Each member document is parsed and wrapped once (see
    :func:`load_xpath_documents`) and registered in *both* returned maps. The
    second registration is not redundant: ``fn:id`` resolves its target document
    through ``XPathContext.get_root()``, which searches ``root`` and
    ``documents`` but never ``collections``. Without it,
    ``collection($uri)/id($key)`` returns the empty sequence — silently, with no
    error — which is the shape most register lookups take.

    *documents* is merged into (and takes precedence in) the returned document
    map, so a file listed both in ``[transform] documents`` and in a collection
    is parsed once and shared as the same node object.
    """
    merged_documents: dict[str, Any] = dict(documents or {})
    result: dict[str, list] = {}
    for entry in collections:
        members: list = []
        for path in entry.documents:
            resolved = path.resolve()
            uri = resolved.as_uri()
            node = merged_documents.get(uri)
            if node is None:
                node = get_node_tree(etree.parse(str(resolved)), None, uri)
                merged_documents[uri] = node
            members.append(node)
        result.setdefault(entry.uri, []).extend(members)
    return result, merged_documents


def run_transform(
    mod: ModuleType,
    root: etree._Element,
    *,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool = False,
    apply_template: bool = True,
    template_path: Path | None = None,
    user_css: str | None = None,
    webcomponents_url: str | None = None,
    docx_template: Path | None = None,
    typst_template_path: Path | None = None,
    xpath_base_uri: str | None = None,
    xpath_documents: dict[str, Any] | None = None,
    xpath_collections: dict[str, list] | None = None,
    xpath_variables: dict[str, Any] | None = None,
    xpath_namespaces: dict[str, str] | None = None,
) -> str | bytes:
    """Run *mod* against *root* and return the serialized output.

    For HTML output, if the result contains a full ``<html>`` document and
    *apply_template* is ``True``, the result is wrapped in the Jinja2 document
    template.  Fragment transforms (e.g. a single ``<div>``) skip this step.

    For DOCX output, returns raw ``bytes`` (the ``.docx`` file content).

    Args:
        mod: A loaded transform module (from :func:`load_transform_module`).
        root: The lxml element to transform.
        parameters: XPath ``$parameters`` map passed to the transform.
        xpath_extensions: Dotted module paths for custom XPath functions.
        webcomponents: Enable TEI Publisher web-component mode.
        apply_template: Wrap full-document HTML output in the Jinja2 template.
        template_path: Override Jinja2 template (default: packaged template).
        user_css: CSS string injected into ``<head>`` of full-document output.
        webcomponents_url: CDN URL for ``pb-components`` script tag.
        docx_template: Path to a ``.docx`` file used as the Word style template.
        typst_template_path: Jinja2 template for Typst document shell.
    """
    serialize = getattr(mod, 'serialize', _default_serialize)

    transform_opts: dict[str, Any] = dict(parameters or {})
    transform_opts.update(
        xpath_runtime_context(
            base_uri=xpath_base_uri,
            documents=xpath_documents,
            collections=xpath_collections,
            variables=xpath_variables,
            namespaces=xpath_namespaces,
        ),
    )
    if xpath_extensions:
        transform_opts['xpath_extensions'] = list(xpath_extensions)
    if webcomponents:
        transform_opts['webcomponents'] = True
    if docx_template is not None:
        transform_opts['docx_template'] = docx_template

    channels = mod.transform_output_channels()
    primary = (channels[0] if channels else '') if isinstance(channels, (list, tuple)) else channels

    metadata: dict = {}
    if primary == 'typst':
        transform_opts['metadata'] = metadata

    result = mod.transform(root, transform_opts if transform_opts else None)

    # Binary output (e.g. docx) — finish() already packaged everything
    if result and isinstance(result[0], bytes):
        return result[0]

    is_document = any(
        isinstance(item, etree._Element) and etree.QName(item).localname == 'html'
        for item in result
    )
    out = serialize(result)

    if apply_template and primary == 'typst':
        tpl = resolve_template_path(
            typst_template_path, default_name=DEFAULT_TYPST_TEMPLATE_NAME
        )
        out = render_typst_document_template(
            content_typst=out,
            template_path=tpl,
            odd_typst=getattr(mod, 'ODD_GENERATED_TYPST', ''),
            parameters=parameters or {},
            metadata=metadata,
        )
    elif apply_template and is_document and primary == 'web':
        tpl = resolve_template_path(template_path)
        out = render_document_template(
            serialized_html=out,
            template_path=tpl,
            odd_css=getattr(mod, 'ODD_GENERATED_CSS', ''),
            user_css=user_css or '',
            parameters=parameters or {},
            webcomponents_url=webcomponents_url,
        )

    return out


def transform_node(
    script_path: Path,
    root: etree._Element,
    *,
    xpath: str | None = None,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool = False,
    apply_template: bool = True,
    template_path: Path | None = None,
    user_css: str | None = None,
    webcomponents_url: str | None = None,
    docx_template: Path | None = None,
    typst_template_path: Path | None = None,
    xpath_base_uri: str | None = None,
    xpath_documents: dict[str, Any] | None = None,
    xpath_collections: dict[str, list] | None = None,
    xpath_variables: dict[str, Any] | None = None,
    xpath_namespaces: dict[str, str] | None = None,
) -> str | bytes:
    """Load *script_path* as a transform module and apply it to *root*.

    If *xpath* is given it is evaluated against *root* via
    :func:`~opm.pm_runtime.resolve_context_element` to select the
    actual element to transform; unprefixed names use the document's default
    namespace.  Without *xpath*, *root* itself is the transform target.

    Args:
        script_path: Path to the compiled transform ``.py`` module.
        root: The lxml element that acts as the document root for XPath
            evaluation and (when *xpath* is ``None``) as the transform target.
        xpath: XPath 3.1 expression selecting a single child element to
            transform instead of *root*.
        parameters: XPath ``$parameters`` map passed to the transform.
        xpath_extensions: Dotted module paths for custom XPath functions.
        webcomponents: Enable TEI Publisher web-component mode.
        apply_template: Wrap full-document HTML output in the Jinja2 template.
        template_path: Override Jinja2 template (default: packaged template).
        user_css: CSS string injected into ``<head>`` of full-document output.
        webcomponents_url: CDN URL for the ``pb-components`` script tag.
    """
    mod = load_transform_module(script_path)
    effective_extensions: tuple[str, ...] = tuple(xpath_extensions) if xpath_extensions else ()
    effective_parameters: dict[str, Any] = dict(parameters or {})
    effective_parameters.update(
        xpath_runtime_context(
            base_uri=xpath_base_uri,
            documents=xpath_documents,
            collections=xpath_collections,
            variables=xpath_variables,
            namespaces=xpath_namespaces,
        ),
    )
    element = (
        resolve_context_element(
            root,
            xpath,
            effective_parameters or None,
            xpath_extensions=effective_extensions,
        )
        if xpath
        else root
    )
    return run_transform(
        mod,
        element,
        parameters=parameters,
        xpath_extensions=effective_extensions or None,
        webcomponents=webcomponents,
        apply_template=apply_template,
        template_path=template_path,
        user_css=user_css,
        webcomponents_url=webcomponents_url,
        docx_template=docx_template,
        typst_template_path=typst_template_path,
        xpath_base_uri=xpath_base_uri,
        xpath_documents=xpath_documents,
        xpath_collections=xpath_collections,
        xpath_variables=xpath_variables,
        xpath_namespaces=xpath_namespaces,
    )


def transform_file(
    module_path: Path,
    xml_path: Path,
    *,
    xpath: str | None = None,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool | None = None,
    template: Path | None = None,
    user_css: str | None = None,
    config: ProjectConfig | None = None,
) -> str | bytes:
    """Transform *xml_path* (or an XPath-selected element within it) and return the result.

    Reads ``opm.toml`` from the current directory for defaults unless
    *config* is supplied explicitly.

    Args:
        module_path: Path to the compiled transform ``.py`` module.
        xml_path: Path to the XML input file.
        xpath: XPath 3.1 expression selecting the transform root element.
            Unprefixed names use the document's default namespace.
        parameters: XPath ``$parameters`` passed to the transform.
        xpath_extensions: Dotted module paths for custom XPath functions.
            ``None`` uses ``[transform] xpath_extensions`` from config.
        webcomponents: Enable web-component mode.
            ``None`` uses ``[transform.web.webcomponents] enabled`` from config.
        template: Jinja2 template override for full-document HTML output.
        user_css: CSS string for full-document HTML output.
        config: Pre-loaded :class:`~opm.config.ProjectConfig`.
            When ``None``, ``opm.toml`` is loaded from the CWD.

    Returns ``str`` for text output modes (HTML, Markdown) and ``bytes`` for
    binary modes (DOCX).
    """
    cfg = config if config is not None else load_project_config()

    effective_webcomponents = webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False)
    effective_extensions: tuple[str, ...] = (
        tuple(xpath_extensions) if xpath_extensions is not None else cfg.xpath_extensions
    )
    webcomponents_url: str | None = None
    if effective_webcomponents:
        webcomponents_url = cfg.webcomponents_cdn or DEFAULT_CDN_TEMPLATE.replace('{version}', DEFAULT_VERSION)

    doc_root = etree.parse(str(xml_path)).getroot()
    xpath_base_uri = xml_path.resolve().as_uri()
    xpath_documents = load_xpath_documents(cfg.xpath_documents)
    xpath_collections, xpath_documents = load_xpath_collections(
        cfg.xpath_collections, xpath_documents,
    )
    xpath_variables = dict(cfg.xpath_variables)
    xpath_namespaces = dict(cfg.xpath_namespaces)

    return transform_node(
        module_path,
        doc_root,
        xpath=xpath,
        parameters=parameters,
        xpath_extensions=effective_extensions or None,
        webcomponents=effective_webcomponents,
        template_path=template if template is not None else cfg.document_template,
        user_css=user_css,
        webcomponents_url=webcomponents_url,
        docx_template=cfg.document_docx_template,
        typst_template_path=template if template is not None else cfg.typst_template,
        xpath_base_uri=xpath_base_uri,
        xpath_documents=xpath_documents,
        xpath_collections=xpath_collections,
        xpath_variables=xpath_variables,
        xpath_namespaces=xpath_namespaces,
    )
