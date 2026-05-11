"""Core transform API — import this to drive transforms from your own Python scripts.

Three entry points at increasing levels of abstraction:

``run_transform(mod, element, ...)``
    Lowest level. Caller supplies an already-loaded module and an already-selected
    lxml element; the function serializes and optionally wraps the result in the
    Jinja2 document template::

        from teipublisher.transform import load_transform_module, run_transform
        from lxml import etree

        mod = load_transform_module(Path('modules/teipublisher-web.py'))
        root = etree.parse('document.xml').getroot()

        html     = run_transform(mod, root)                 # full document
        fragment = run_transform(mod, root.find('.//{*}div'))  # single element

``transform_node(script_path, root, *, xpath=None, ...)``
    Mid level. Loads the module from *script_path* and, if *xpath* is given,
    selects the target element before transforming::

        from teipublisher.transform import transform_node
        from lxml import etree

        root = etree.parse('document.xml').getroot()
        html = transform_node(
            Path('modules/teipublisher-web.py'),
            root,
            xpath='//body/div[1]',
        )

``transform_file(module_path, xml_path, *, xpath=None, ...)``
    Highest level. Also parses the XML file and reads ``teipublisher.toml``
    for defaults (extensions, webcomponents, template)::

        from teipublisher.transform import transform_file

        html = transform_file(
            Path('modules/teipublisher-web.py'),
            Path('document.xml'),
            xpath='//body/div[1]',
        )

``xpath_select(root, expr, ...)``
    Utility for evaluating XPath against a parsed document without any
    namespace bookkeeping — unprefixed names automatically match the
    document's namespace::

        from teipublisher.transform import xpath_select
        from lxml import etree

        root = etree.parse('document.xml').getroot()
        chapters = xpath_select(root, '//body/div')
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Sequence

from lxml import etree

from teipublisher.config import (
    DEFAULT_CDN_TEMPLATE,
    DEFAULT_VERSION,
    ProjectConfig,
    load_project_config,
)
from teipublisher.runtime.pm_runtime import resolve_context_element
from teipublisher.runtime.pm_runtime import serialize as _default_serialize
from teipublisher.template_rendering import render_document_template, resolve_template_path


def load_transform_module(script_path: Path):
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
            f'{path} has no transform_output_channels() — expected a module emitted by teipublisher compile',
        )
    return mod


def xpath_select(
    root: etree._Element,
    expr: str,
    params: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
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
    from teipublisher.runtime.pm_runtime import xpath_select_nodes  # noqa: PLC0415

    result = xpath_select_nodes(
        root, expr, params,
        xpath_extensions=tuple(xpath_extensions) if xpath_extensions else None,
    )
    # xpath_select_nodes unwraps a single-item list to a scalar; normalise back to list
    return result if isinstance(result, list) else [result]


def run_transform(
    mod,
    root: etree._Element,
    *,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool = False,
    apply_template: bool = True,
    template_path: Path | None = None,
    user_css: str | None = None,
    webcomponents_url: str | None = None,
) -> str:
    """Run *mod* against *root* and return the serialized output string.

    For HTML output, if the result contains a full ``<html>`` document and
    *apply_template* is ``True``, the result is wrapped in the Jinja2 document
    template.  Fragment transforms (e.g. a single ``<div>``) skip this step.

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
    """
    serialize = getattr(mod, 'serialize', _default_serialize)

    transform_opts: dict[str, Any] = dict(parameters or {})
    if xpath_extensions:
        transform_opts['xpath_extensions'] = list(xpath_extensions)
    if webcomponents:
        transform_opts['webcomponents'] = True

    result = mod.transform(root, transform_opts if transform_opts else None)

    is_document = any(
        isinstance(item, etree._Element) and etree.QName(item).localname == 'html'
        for item in result
    )
    out = serialize(result)

    if apply_template and is_document:
        channels = mod.transform_output_channels()
        primary = (channels[0] if channels else '') if isinstance(channels, (list, tuple)) else channels
        if primary == 'web':
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
) -> str:
    """Load *script_path* as a transform module and apply it to *root*.

    If *xpath* is given it is evaluated against *root* via
    :func:`~teipublisher.pm_runtime.resolve_context_element` to select the
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
    element = (
        resolve_context_element(root, xpath, parameters or None, xpath_extensions=effective_extensions)
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
) -> str:
    """Transform *xml_path* (or an XPath-selected element within it) and return the result string.

    Reads ``teipublisher.toml`` from the current directory for defaults unless
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
            ``None`` uses ``[webcomponents] enabled`` from config.
        template: Jinja2 template override for full-document HTML output.
        user_css: CSS string for full-document HTML output.
        config: Pre-loaded :class:`~teipublisher.config.ProjectConfig`.
            When ``None``, ``teipublisher.toml`` is loaded from the CWD.
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
    )
