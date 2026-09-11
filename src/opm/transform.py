# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Core transform API — import this to drive transforms from your own Python scripts.

Most callers want [`opm.Project.transform`][opm.project.Project.transform], which also compiles the
ODD and keeps the loaded module and registers between calls. The functions
here are the layer below it, at increasing levels of abstraction.

[`run_transform(mod, element, ...)`][opm.transform.run_transform] is the lowest
level. The caller supplies an already-loaded module and an already-selected
lxml element; the function serializes and optionally wraps the result in the
Jinja2 document template:

```python
from opm.odd_cache import ensure_compiled_module
from opm.resources import packaged_odd
from opm.transform import load_transform_module, run_transform
from lxml import etree

path, _ = ensure_compiled_module(packaged_odd('teipublisher'))
mod = load_transform_module(path)
root = etree.parse('document.xml').getroot()

html     = run_transform(mod, root)                 # full document
fragment = run_transform(mod, root.find('.//{*}div'))  # single element
```

[`transform_node(script_path, root, *, xpath=None, ...)`][opm.transform.transform_node]
is the mid level. It loads the module from *script_path* and, if *xpath* is
given, selects the target element before transforming:

```python
from opm.odd_cache import ensure_compiled_module
from opm.resources import packaged_odd
from opm.transform import transform_node
from lxml import etree

path, _ = ensure_compiled_module(packaged_odd('teipublisher'))
root = etree.parse('document.xml').getroot()
html = transform_node(path, root, xpath='//body/div[1]')
```

[`transform_file(module, xml_path, *, xpath=None, ...)`][opm.transform.transform_file]
is the highest level, and what ``opm transform`` runs. It also parses the XML
file and takes everything else from ``opm.toml``: parameters, registers,
extensions, web components, template:

```python
from opm.odd_cache import ensure_compiled_module
from opm.resources import packaged_odd
from opm.transform import transform_file

path, _ = ensure_compiled_module(packaged_odd('teipublisher'))
html = transform_file(path, Path('document.xml'), xpath='//body/div[1]')
```

[`xpath_select(root, expr, ...)`][opm.transform.xpath_select] evaluates XPath
against a parsed document without any namespace bookkeeping: unprefixed names
automatically match the document's namespace:

```python
from opm.transform import xpath_select
from lxml import etree

root = etree.parse('document.xml').getroot()
chapters = xpath_select(root, '//body/div')
```
"""

from __future__ import annotations

import importlib.util
from types import ModuleType
from pathlib import Path
from typing import Any, Sequence, TypedDict

from elementpath.tree_builders import get_node_tree
from lxml import etree

from opm.config import (
    ChunkingConfig,
    CollectionConfig,
    ProjectConfig,
    load_project_config,
)
from opm.output_modes import OutputMode, module_mode
from opm.runtime.pm_runtime import serialize as _default_serialize
from opm.runtime.xpath_env import XPathEnvironment
from opm.template_rendering import (
    DEFAULT_TEMPLATE_NAME,
    DEFAULT_TYPST_TEMPLATE_NAME,
    render_document_template,
    render_typst_document_template,
    resolve_template_path,
)

class TemplateArguments(TypedDict, total=False):
    """The [`run_transform`][opm.transform.run_transform] argument each kind of template goes to."""

    template_path: Path | None
    typst_template_path: Path | None
    docx_template: Path | None


def template_arguments(
    mode: OutputMode,
    config: ProjectConfig,
    override: Path | None = None,
) -> TemplateArguments:
    """The template argument [`run_transform`][opm.transform.run_transform] takes for a run in *mode*.

    *override* (``--template``) wins over the project's
    ``[transform.<type>] template``. Without either, an HTML or Typst shell
    falls back to its packaged default inside [`run_transform`][opm.transform.run_transform], and DOCX
    to the packaged Word style template. Modes that take no template get none.
    """
    if mode.template is None or mode.template_setting is None:
        return {}
    chosen = override if override is not None else getattr(config, mode.template_setting)
    if chosen is None and mode.template == 'docx':
        from opm.resources import packaged_default_docx

        chosen = packaged_default_docx()
    if mode.template == 'typst':
        return {'typst_template_path': chosen}
    if mode.template == 'docx':
        return {'docx_template': chosen}
    return {'template_path': chosen}


def load_transform_module(script_path: Path) -> ModuleType:
    """Load a ``.py`` file that defines ``transform()`` and ``OUTPUT_MODE``."""
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
    if not hasattr(mod, 'OUTPUT_MODE'):
        raise AttributeError(
            f'{path} has no OUTPUT_MODE — expected a compiled ODD transform module',
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
    *,
    xpath_env: XPathEnvironment | None = None,
) -> list:
    """Evaluate XPath 3.1 *expr* against *root*, returning a plain list.

    The document's default namespace URI (taken from *root*'s ``nsmap``) is set
    as the XPath default element namespace, so unprefixed element names match
    without any prefix mapping:

    ```python
    chapters = xpath_select(root, '//body/div')          # TEI, DocBook, …
    titles   = xpath_select(root, '//div/head/string()')  # atomic results
    ```

    Element results are returned as lxml `_Element` objects.
    Atomic expressions (``count(…)``, ``string(…)``) return the corresponding
    Python scalar.

    Args:
        root: Document root element; its namespace determines the default element namespace.
        expr: XPath 3.1 expression with unprefixed element names.
        params: Values bound as the XPath ``$parameters`` map.
        xpath_extensions: Dotted module paths for custom XPath functions in the ``tp:`` namespace.
        xpath_env: Evaluate in this environment instead of one built from the
            other arguments; its cached document trees are then reused.
    """
    env = xpath_env if xpath_env is not None else XPathEnvironment(
        base_uri=xpath_base_uri,
        documents=xpath_documents,
        collections=xpath_collections,
        variables=xpath_variables,
        namespaces=xpath_namespaces,
        extensions=xpath_extensions,
    )
    if params:
        env = env.with_parameters(params)
    return env.select_all(root, expr)


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
    dict lookup. Mirrors what [`wrapped`][opm.runtime.xpath_env.XPathEnvironment.wrapped]
    does for the main document.
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
    [`load_xpath_documents`][opm.transform.load_xpath_documents]) and registered in *both* returned maps. The
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


def load_project_documents(
    config: ProjectConfig,
) -> tuple[dict[str, Any], dict[str, list]]:
    """``(documents, collections)`` for the XPath dynamic context, from *config*.

    Parses ``[transform] documents`` and every ``[[transform.collections]]``
    member once. Pass the result to [`project_xpath_env`][opm.transform.project_xpath_env] to share the
    parsed registers across several documents.
    """
    documents = load_xpath_documents(config.xpath_documents)
    collections, documents = load_xpath_collections(config.xpath_collections, documents)
    return documents, collections


def project_xpath_env(
    config: ProjectConfig,
    xml_path: Path | None = None,
    *,
    extensions: Sequence[str] | None = None,
    documents: tuple[dict[str, Any], dict[str, list]] | None = None,
) -> XPathEnvironment:
    """The XPath environment a run over *xml_path* evaluates in.

    Registers, collections, variables, namespaces and extension modules all
    come from *config*; *extensions* replaces the configured modules when
    given. *xml_path* is the base URI ``doc()`` resolves against. *documents*
    is a [`load_project_documents`][opm.transform.load_project_documents] result to reuse instead of parsing the
    registers again.

    The config's ``[project] pythonpath`` goes on ``sys.path`` first, so its
    extension modules import from the Python API as they do from the CLI.
    """
    config.extend_sys_path()
    docs, collections = (
        documents if documents is not None else load_project_documents(config)
    )
    return XPathEnvironment(
        base_uri=xml_path.resolve().as_uri() if xml_path is not None else None,
        documents=docs,
        collections=collections,
        variables=dict(config.xpath_variables),
        namespaces=dict(config.xpath_namespaces),
        extensions=tuple(extensions) if extensions is not None else config.xpath_extensions,
    )


def _print_base_css() -> str:
    """Packaged paged-media baseline for the print channel, or ``''`` if absent.

    ``PrintOutputFunctions.note``/``alternate`` emit footnotes as inline spans
    for CSS ``float: footnote`` to pull out to the page-bottom footnote area —
    the packaged baseline is what actually declares that rule (plus
    ``::footnote-call``/``::footnote-marker``). Kept separate from the ODD's
    own generated CSS (rather than concatenated into it) so
    [`render_document_template`][opm.template_rendering.render_document_template]'s de-dup check —
    which drops ``odd_css`` when it is already embedded in the document's own
    ``<head>`` — still recognises an exact match instead of seeing a combined
    string it has never encountered before and emitting the ODD CSS twice.
    """
    from opm.resources import packaged_print_css

    base_path = packaged_print_css()
    if base_path is None or not base_path.is_file():
        return ''
    return base_path.read_text(encoding='utf-8').rstrip()


def run_transform(
    mod: ModuleType,
    root: etree._Element,
    *,
    parameters: dict[str, str] | None = None,
    webcomponents: bool = False,
    apply_template: bool = True,
    template_path: Path | None = None,
    template_context: dict[str, Any] | None = None,
    docx_template: Path | None = None,
    typst_template_path: Path | None = None,
    epub_chunking: ChunkingConfig | None = None,
    epub_css: Path | None = None,
    epub_skip_title: bool = False,
    xpath_env: XPathEnvironment | None = None,
) -> str | bytes:
    """Run *mod* against *root* and return the serialized output.

    For HTML output, if the result contains a full ``<html>`` document and
    *apply_template* is ``True``, the result is wrapped in the Jinja2 document
    template.  Fragment transforms (e.g. a single ``<div>``) skip this step.

    For DOCX / EPUB output, returns raw ``bytes`` (the package file content).

    Args:
        mod: A loaded transform module (from [`load_transform_module`][opm.transform.load_transform_module]).
        root: The lxml element to transform.
        parameters: XPath ``$parameters`` map passed to the transform.
        webcomponents: Enable TEI Publisher web-component mode.
        apply_template: Wrap full-document HTML output in the Jinja2 template.
        template_path: Override Jinja2 template (default: packaged template).
        template_context: Project ``[context]`` values exposed to the Jinja2
            template as ``context`` (see
            [`context_for`][opm.config.ProjectConfig.context_for]).
        docx_template: Path to a ``.docx`` file used as the Word style template.
        typst_template_path: Jinja2 template for Typst document shell.
        epub_chunking: Chapter selection for ``-t epub`` (defaults from TEI/DocBook).
        epub_css: Stylesheet appended last to the EPUB package.
        epub_skip_title: Omit the generated EPUB title page.
        xpath_env: The XPath environment to evaluate in (see
            [`project_xpath_env`][opm.transform.project_xpath_env]); an empty one when omitted.
    """
    serialize = getattr(mod, 'serialize', _default_serialize)

    env = xpath_env if xpath_env is not None else XPathEnvironment()
    transform_opts: dict[str, Any] = dict(parameters or {})
    if webcomponents:
        transform_opts['webcomponents'] = True
    if docx_template is not None:
        transform_opts['docx_template'] = docx_template

    mode = module_mode(mod)

    if mode.packaged:
        from opm.epub import build_epub

        input_path = None
        raw_input = (parameters or {}).get('input_path') if parameters else None
        if raw_input:
            input_path = Path(str(raw_input))
        return build_epub(
            mod,
            root,
            chunking=epub_chunking,
            odd_css=getattr(mod, 'ODD_GENERATED_CSS', '') or '',
            project_css=epub_css.read_text(encoding='utf-8') if epub_css else None,
            input_path=input_path,
            transform_opts=transform_opts,
            skip_title=epub_skip_title,
            xpath_env=env,
        )

    metadata: dict = {}
    if mode.collects_metadata:
        transform_opts['metadata'] = metadata

    result = mod.transform(root, transform_opts or None, xpath_env=env)

    # Binary output (e.g. docx) — finish() already packaged everything
    if result and isinstance(result[0], bytes):
        return result[0]

    is_document = any(
        isinstance(item, etree._Element) and etree.QName(item).localname == 'html'
        for item in result
    )
    out = serialize(result)

    if apply_template and mode.template == 'typst':
        tpl = resolve_template_path(
            typst_template_path,
            default_name=mode.default_template or DEFAULT_TYPST_TEMPLATE_NAME,
        )
        out = render_typst_document_template(
            content_typst=out,
            template_path=tpl,
            odd_typst=getattr(mod, 'ODD_GENERATED_TYPST', ''),
            parameters=parameters or {},
            metadata=metadata,
            context=template_context,
        )
    elif apply_template and is_document and mode.template == 'html':
        tpl = resolve_template_path(
            template_path, default_name=mode.default_template or DEFAULT_TEMPLATE_NAME,
        )
        out = render_document_template(
            serialized_html=out,
            template_path=tpl,
            odd_css=getattr(mod, 'ODD_GENERATED_CSS', ''),
            base_css=_print_base_css() if mode.print_css else None,
            parameters=parameters or {},
            context=template_context,
        )

    return out


def transform_node(
    script_path: Path | ModuleType,
    root: etree._Element,
    *,
    xpath: str | None = None,
    parameters: dict[str, str] | None = None,
    webcomponents: bool = False,
    apply_template: bool = True,
    template_path: Path | None = None,
    template_context: dict[str, Any] | None = None,
    docx_template: Path | None = None,
    typst_template_path: Path | None = None,
    epub_chunking: ChunkingConfig | None = None,
    epub_css: Path | None = None,
    epub_skip_title: bool = False,
    xpath_env: XPathEnvironment | None = None,
) -> str | bytes:
    """Load *script_path* as a transform module and apply it to *root*.

    If *xpath* is given it is evaluated against *root* via
    [`resolve_element`][opm.runtime.xpath_env.XPathEnvironment.resolve_element] to select the
    actual element to transform; unprefixed names use the document's default
    namespace.  Without *xpath*, *root* itself is the transform target.

    Args:
        script_path: Path to the compiled transform ``.py`` module, or an
            already-loaded one — callers that need to inspect the module first
            (to learn its output channel, say) pass it in rather than paying
            for a second exec.
        root: The lxml element that acts as the document root for XPath
            evaluation and (when *xpath* is ``None``) as the transform target.
        xpath: XPath 3.1 expression selecting a single child element to
            transform instead of *root*.
        parameters: XPath ``$parameters`` map passed to the transform.
        webcomponents: Enable TEI Publisher web-component mode.
        apply_template: Wrap full-document HTML output in the Jinja2 template.
        template_path: Override Jinja2 template (default: packaged template).
        template_context: Project ``[context]`` values exposed to the Jinja2
            template as ``context``.
        xpath_env: The XPath environment to evaluate in (see
            [`project_xpath_env`][opm.transform.project_xpath_env]); an empty one when omitted.
    """
    mod = (
        script_path
        if isinstance(script_path, ModuleType)
        else load_transform_module(script_path)
    )
    env = xpath_env if xpath_env is not None else XPathEnvironment()
    element = (
        env.with_parameters(parameters).resolve_element(root, xpath)
        if xpath
        else root
    )
    return run_transform(
        mod,
        element,
        parameters=parameters,
        webcomponents=webcomponents,
        apply_template=apply_template,
        template_path=template_path,
        template_context=template_context,
        docx_template=docx_template,
        typst_template_path=typst_template_path,
        epub_chunking=epub_chunking,
        epub_css=epub_css,
        epub_skip_title=epub_skip_title,
        xpath_env=env,
    )


def transform_file(
    module: Path | ModuleType,
    xml_path: Path,
    *,
    xpath: str | None = None,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool | None = None,
    template: Path | None = None,
    config: ProjectConfig | None = None,
    documents: tuple[dict[str, Any], dict[str, list]] | None = None,
) -> str | bytes:
    """Transform *xml_path* (or an XPath-selected element within it) with the project's settings.

    This is what ``opm transform`` runs. Everything the arguments leave open
    comes from the project config: ``$parameters``, registers and collections,
    XPath variables and extensions, web components, the template and its
    ``context``, and the EPUB chapter selection.

    Args:
        module: The compiled transform module, or the path to its ``.py`` file.
        xml_path: Path to the XML input file.
        xpath: XPath 3.1 expression selecting the transform root element.
            Unprefixed names use the document's default namespace.
        parameters: XPath ``$parameters``, over ``[transform.parameters]``.
            ``input_path`` defaults to *xml_path*.
        xpath_extensions: Dotted module paths for custom XPath functions.
            ``None`` uses ``[transform] xpath_extensions`` from config.
        webcomponents: Enable web-component mode.
            ``None`` uses ``[transform.web.webcomponents] enabled`` from config.
            Modes without web components (print, EPUB, JSON) ignore it.
        template: Template override (see [`template_arguments`][opm.transform.template_arguments]).
        config: Pre-loaded [`ProjectConfig`][opm.config.ProjectConfig].
            When ``None``, ``opm.toml`` is loaded from the CWD.
        documents: A [`load_project_documents`][opm.transform.load_project_documents] result to reuse instead
            of parsing the registers again.

    Returns ``str`` for text output modes (HTML, Markdown, Typst) and ``bytes``
    for binary ones (DOCX, EPUB). To get a PDF, pass Typst output to
    [`opm.typst_compile.compile_pdf`][opm.typst_compile.compile_pdf].
    """
    return transform_with_config(
        module if isinstance(module, ModuleType) else load_transform_module(module),
        etree.parse(str(xml_path)).getroot(),
        xml_path,
        config if config is not None else load_project_config(),
        xpath=xpath,
        parameters=parameters,
        xpath_extensions=xpath_extensions,
        webcomponents=webcomponents,
        template=template,
        documents=documents,
    )


def transform_with_config(
    mod: ModuleType,
    root: etree._Element,
    xml_path: Path | None,
    config: ProjectConfig,
    *,
    xpath: str | None = None,
    parameters: dict[str, str] | None = None,
    xpath_extensions: Sequence[str] | None = None,
    webcomponents: bool | None = None,
    template: Path | None = None,
    documents: tuple[dict[str, Any], dict[str, list]] | None = None,
) -> str | bytes:
    """Transform the already parsed *root* with *config*'s settings.

    The part of [`transform_file`][opm.transform.transform_file] after parsing, shared with
    [`opm.project.Project.transform`][opm.project.Project.transform]. *xml_path* is the file *root* was
    read from, if any: ``doc()`` resolves against it and it becomes
    ``$parameters?input_path``.
    """
    mode = module_mode(mod)

    enabled = webcomponents if webcomponents is not None else bool(config.webcomponents_enabled)
    effective_webcomponents = enabled and mode.webcomponents
    merged_parameters = dict(config.parameters)
    merged_parameters.update(parameters or {})
    if xml_path is not None:
        merged_parameters.setdefault('input_path', str(xml_path))

    return transform_node(
        mod,
        root,
        xpath=xpath,
        parameters=merged_parameters,
        webcomponents=effective_webcomponents,
        template_context=config.context_for(mode.name, webcomponents=effective_webcomponents),
        **template_arguments(mode, config, template),
        xpath_env=project_xpath_env(
            config, xml_path, extensions=xpath_extensions, documents=documents,
        ),
        epub_chunking=config.epub_chunking,
        epub_css=config.epub_css,
        epub_skip_title=config.epub_skip_title,
    )
