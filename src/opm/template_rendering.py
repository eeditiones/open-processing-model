# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers for wrapping transform output in page templates (HTML and Typst).

A template whose name ends in ``.tpl`` (``page.html.tpl``, ``book.typ.tpl``)
is a jinks template ([`opm.jinks_templates`][opm.jinks_templates.environment]),
as all packaged defaults are; any other, e.g. ``page.html.j2``, is a Jinja2
template. Both get the same variables.
"""

from __future__ import annotations

import dataclasses
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, TemplateNotFound
from lxml import etree

from opm import jinks_templates as jinks
from opm.jinks_templates.environment import convert_results
from opm.output_modes import RENDER_MODES
from opm.runtime.xpath_env import XPathEnvironment
from opm.runtime.xpath_extensions import build_extension_parser, load_extension_callables
from opm.template_frontmatter import FrontmatterLoader, template_context

if TYPE_CHECKING:
    from opm.project import Project

DEFAULT_TEMPLATE_NAME: str = RENDER_MODES['web'].default_template  # type: ignore[assignment]
DEFAULT_PRINT_TEMPLATE_NAME: str = RENDER_MODES['print'].default_template  # type: ignore[assignment]
DEFAULT_TYPST_TEMPLATE_NAME: str = RENDER_MODES['typst'].default_template  # type: ignore[assignment]
DEFAULT_INDEX_TEMPLATE_NAME = 'default_index.html.tpl'


def default_template_path(template_name: str = DEFAULT_TEMPLATE_NAME) -> Path:
    """Return the path to a packaged default document template."""
    return Path(
        str(resources.files('opm').joinpath(f'resources/templates/{template_name}'))
    )


def resolve_template_path(
    template_path: Path | None,
    *,
    default_name: str = DEFAULT_TEMPLATE_NAME,
    project: Any = None,
) -> Path:
    """Resolve override template path or the default template.

    Without *template_path*, a template named *default_name* in one of
    *project*'s profiles replaces the packaged default; where several profiles
    ship one, the profile listed last wins.
    """
    path = template_path
    if path is None and project is not None:
        for _, profile_path in reversed(getattr(project, '_profiles', ())):
            candidate = profile_path / 'templates' / default_name
            if candidate.is_file():
                path = candidate
                break
    if path is None:
        path = default_template_path(default_name)
    if not path.is_file():
        raise FileNotFoundError(f'Template not found: {path}')
    return path


#: The stylesheet of the packaged page layout (``opm/layout.html.tpl``), in
#: ``resources/templates/opm/``.
LAYOUT_CSS_NAME = 'opm-layout.css'


def layout_css(templates_dir: Path | None = None) -> str:
    """The stylesheet behind ``opm/layout.html.tpl`` (and its Jinja2 twin).

    Chunking writes it to ``css/opm-layout.css`` and passes ``layout_css_url``;
    a single transformed page has no such file, so the layout inlines it.
    A copy at ``opm/opm-layout.css`` under *templates_dir* wins over the
    packaged one, as the template loader does for the inlined case.
    """
    if templates_dir is not None:
        local = templates_dir / 'opm' / LAYOUT_CSS_NAME
        if local.is_file():
            return local.read_text(encoding='utf-8')
    return (packaged_templates_dir() / 'opm' / LAYOUT_CSS_NAME).read_text(encoding='utf-8')


def packaged_templates_dir() -> Path:
    """The directory holding the packaged templates, ``opm/`` layouts included."""
    return default_template_path().parent


class TrimmedBlocks:
    """A template's blocks, each rendered on first use and trimmed.

    Templates get one through the ``trimmed`` global: ``{% set blocks =
    trimmed(self) %}``, then ``blocks.before`` is the rendered ``before``
    block, an empty string when it holds only whitespace. That lets a layout
    test whether a region has content before it writes the region's wrapper.
    """

    def __init__(self, template_ref: Any) -> None:
        self._ref = template_ref
        self._rendered: dict[str, str] = {}

    def __getattr__(self, name: str) -> str:
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in self._rendered:
            self._rendered[name] = str(self._ref[name]()).strip()
        return self._rendered[name]


#: Suffix of jinks templates; any other template is a Jinja2 template.
JINKS_SUFFIX = '.tpl'

#: Variables holding HTML opm rendered itself, written unescaped by jinks
#: templates in html mode.
_MARKUP_VARIABLES = ('content_html', 'head_html', 'odd_css', 'base_css')


def is_jinks_template(template_path: Path) -> bool:
    """Whether *template_path* is a jinks template (``.tpl``) rather than a Jinja2 one."""
    return template_path.name.endswith(JINKS_SUFFIX)


def _searchpaths(template_path: Path, project: Any = None) -> list[str]:
    """Build search paths for template loading.
    
    Args:
        template_path: The path to the template being loaded
        project: Optional Project instance to get profile template paths from
        
    Returns:
        List of directory paths to search for templates
    """
    # Use absolute paths for consistency
    searchpaths = [str(template_path.parent.resolve())]
    
    # Add profile template directories from project first
    # This allows profiles to override default templates
    if project is not None:
        for profile_config, profile_path in project._profiles:
            templates_dir = profile_path / "templates"
            if templates_dir.is_dir():
                searchpaths.append(str(templates_dir.resolve()))
    
    # Also check for a profiles/ directory in the project
    project_dir = template_path.parent.parent.resolve()  # templates/ -> project root
    profiles_dir = project_dir / "profiles"
    if profiles_dir.is_dir():
        for profile_dir in profiles_dir.iterdir():
            if profile_dir.is_dir():
                templates_dir = profile_dir / "templates"
                if templates_dir.is_dir() and str(templates_dir.resolve()) not in searchpaths:
                    searchpaths.append(str(templates_dir.resolve()))
    
    # Add packaged templates last
    packaged = str(packaged_templates_dir())
    if packaged not in searchpaths:
        searchpaths.append(packaged)
    
    return searchpaths


def _jinks_parser_factory(xpath_env: XPathEnvironment | None):
    """Parsers with the project's namespaces and ``tp:`` extension functions."""
    plain = jinks.Environment().parser(frozenset())
    callables: dict = {}
    project_ns: dict[str, str] = {}
    if xpath_env is not None:
        project_ns = xpath_env.namespaces
        for module in xpath_env.extensions:
            callables.update(load_extension_callables(module))
    callables = {name: convert_results(fn, plain) for name, fn in callables.items()}

    def factory(namespaces: dict[str, str]):
        return build_extension_parser('', callables, namespaces={**project_ns, **namespaces})
    return factory


class JinksPageTemplate:
    """A jinks template behind the ``render(**variables)`` call Jinja2 templates take.

    The variables opm passes (``content_html``, ``chunk``, ``fragments``, …)
    and ``context`` form one jinks context map, with the frontmatter merged
    over it by the engine. Where a key exists in both, the project's
    ``context`` wins, as Jinja2 templates prefer ``context.lang`` over
    ``lang``. HTML opm produced itself (``content_html``, ``head_html`` and the
    stylesheets) is marked as markup, so html mode writes it unescaped. Each
    fragment is a [`Fragment`][opm.jinks_templates.Fragment]: expressions see
    it as nodes, and writing it gives back the HTML unchanged.
    """

    def __init__(self, template: jinks.Template, use: tuple[str, ...] = ()) -> None:
        self.template = template
        #: Templates the profiles add to every page, before any the context names.
        self.use = use

    def render(self, **variables: Any) -> str:
        context = variables.pop('context', None) or {}
        if self.use:
            templating = dict(context.get('templating') or {})
            named = templating.get('use') or []
            named = [named] if isinstance(named, str) else list(named)
            templating['use'] = [*self.use, *(f for f in named if f not in self.use)]
            context = {**context, 'templating': templating}
        for name in _MARKUP_VARIABLES:
            if isinstance(variables.get(name), str):
                variables[name] = jinks.Markup(variables[name])
        if isinstance(variables.get('fragments'), dict):
            variables['fragments'] = _markup_fragments(variables['fragments'])
        if isinstance(variables.get('documents'), list):
            # Index entries carry the fragments of each document.
            variables['documents'] = [_index_entry_map(entry) for entry in variables['documents']]
        return self.template.render({**variables, **context})


def _markup_fragments(fragments: dict) -> dict:
    return {k: jinks.Fragment(v) if isinstance(v, str) else v for k, v in fragments.items()}


def _index_entry_map(entry: Any) -> Any:
    if dataclasses.is_dataclass(entry) and not isinstance(entry, type):
        entry = {f.name: getattr(entry, f.name) for f in dataclasses.fields(entry)}
    if isinstance(entry, dict) and isinstance(entry.get('fragments'), dict):
        entry = {**entry, 'fragments': _markup_fragments(entry['fragments'])}
    return entry


def template_environment(
    template_path: Path, xpath_env: XPathEnvironment | None = None, project: Any = None,
) -> Environment | jinks.Environment:
    """The environment for rendering *template_path*: Jinja2 or jinks.

    Templates are looked up in *template_path*'s directory first, then among
    the packaged ones, so a project template can extend
    ``opm/layout.html.tpl`` and can replace a packaged file by giving its
    own the same relative path. Frontmatter is removed from every source and
    feeds the template ``context`` (see
    [`template_context`][opm.template_frontmatter.template_context]). The
    Jinja2 global ``trimmed`` gives access to a template's rendered blocks
    (see [`TrimmedBlocks`][opm.template_rendering.TrimmedBlocks]).

    A jinks template (see
    [`is_jinks_template`][opm.template_rendering.is_jinks_template]) resolves
    ``extends``, ``use`` and includes along the same search path. Its XPath
    sees the project's namespaces and ``tp:`` extension functions from
    *xpath_env*.
    
    If *project* is provided, profile template directories are added to the
    search path, allowing templates to use profile templates via the ``use``
    directive.
    """
    searchpaths = _searchpaths(template_path, project)
    if is_jinks_template(template_path):
        env = jinks.Environment(searchpaths, parser_factory=_jinks_parser_factory(xpath_env))
        # HTML pages take the blocks of every profile's `use` templates; a
        # Typst template, sharing the context, must not.
        if project is not None and '.html' in template_path.name:
            env.profile_use = tuple(
                file for profile, _ in getattr(project, '_profiles', ()) for file in profile.use
            )
        return env
    env = Environment(loader=FrontmatterLoader(searchpaths), autoescape=False)
    env.globals['trimmed'] = TrimmedBlocks
    return env


def load_template(env: Environment | jinks.Environment, template_path: Path,
                  label: str = 'Template'):
    """Load *template_path* from *env*, raising ``FileNotFoundError`` if missing."""
    if isinstance(env, jinks.Environment):
        try:
            return JinksPageTemplate(
                env.get_template(template_path.name), use=getattr(env, 'profile_use', ()),
            )
        except jinks.TemplateNotFound as e:
            raise FileNotFoundError(f'{label} not found: {e}') from e
    try:
        template = env.get_template(template_path.name)
        if isinstance(env.loader, FrontmatterLoader):
            # Resolve the extends chain now, so a missing parent is reported
            # here rather than as a Jinja2 error halfway through rendering.
            env.loader.chain(env, template_path.name)
        return template
    except TemplateNotFound as e:
        missing = '' if e.name == template_path.name else f' (needed by {template_path.name})'
        raise FileNotFoundError(f'{label} not found: {e.name}{missing}') from e


def _inner_html(el: etree._Element | None) -> str:
    if el is None:
        return ''
    parts: list[str] = [el.text or '']
    for child in el:
        parts.append(etree.tostring(child, encoding='unicode', method='html'))  # type: ignore[arg-type]
    return ''.join(parts)


def _first_html_root(serialized_html: str) -> etree._Element | None:
    parser = etree.HTMLParser(encoding='utf-8')
    root = etree.fromstring(serialized_html.encode('utf-8'), parser=parser)
    if etree.QName(root).localname == 'html':
        return root
    return root.find('.//html')


def is_full_html_document(serialized_html: str) -> bool:
    """Whether serialized output contains a full ``<html>`` document element."""
    return _first_html_root(serialized_html) is not None


def render_document_template(
    *,
    serialized_html: str,
    template_path: Path,
    odd_css: str | None,
    parameters: dict[str, str],
    context: dict | None = None,
    base_css: str | None = None,
    assets: str = '',
    asset_styles: list[str] | None = None,
    fragments: dict[str, str] | None = None,
    xpath_env: XPathEnvironment | None = None,
    project: Any = None,
) -> str:
    """Render a full HTML document through the selected page template.

    *context* is the project's ``[context]`` table (see
    [`context_for`][opm.config.ProjectConfig.context_for]), exposed to the template
    under the single name ``context`` so a project key can never shadow a
    built-in like ``content_html``.

    *base_css* is a packaged baseline stylesheet (e.g. the print channel's
    paged-media rules) rendered via its own ``{{ base_css }}`` template slot,
    kept separate from *odd_css* rather than concatenated into it — so the
    ``<style>`` that ``HtmlOutputFunctions.document()`` embedded in the
    document's own ``<head>`` still matches *odd_css* exactly. That element is
    removed from ``head_html``; the template gets the stylesheet as
    ``odd_css`` instead and decides where it goes.

    *assets* and *asset_styles* are the URL prefix of the copied
    ``[transform.web] assets`` and the stylesheets among them, the same
    values chunk pages receive.

    *fragments* are the rendered global fragments of ``[chunking]`` (the
    title, a table of contents), under the same ``fragments`` name chunk pages
    get them, so one template serves both.

    *xpath_env* supplies namespaces and ``tp:`` functions to a jinks template.
    """
    html_root = _first_html_root(serialized_html)
    if html_root is None:
        return serialized_html

    head = html_root.find('head')
    body = html_root.find('body')
    # HtmlOutputFunctions.document() already puts the ODD CSS in <head>. Take
    # it out again and hand it over as odd_css, so a template places it where
    # it belongs in the cascade (opm/base.html.j2: after the page's own
    # stylesheets) and a template rendering both variables does not repeat it.
    if head is not None and odd_css:
        for style in head.findall('style'):
            if (style.text or '').strip() == odd_css.strip():
                head.remove(style)
    head_content = _inner_html(head)
    effective_odd_css = odd_css or ''
    env = template_environment(template_path, xpath_env, project)
    tpl = load_template(env, template_path)
    return tpl.render(
        head_html=head_content,
        content_html=_inner_html(body),
        odd_css=effective_odd_css,
        base_css=base_css or '',
        parameters=parameters or {},
        lang=html_root.get('lang', ''),
        context=template_context(env, template_path.name, context),
        assets=assets,
        asset_styles=asset_styles or [],
        fragments=fragments or {},
    )


def render_index_template(
    *,
    entries: list,
    template_path: Path,
    title: str,
    odd_css: str | None = None,
    odd_css_url: str = '',
    assets: str = '',
    asset_styles: list[str] | None = None,
    layout_css_url: str = '',
    context: dict | None = None,
    xpath_env: XPathEnvironment | None = None,
    project: Any = None,
    site_root: str = '',
) -> str:
    """Render a collection index listing chunked documents.

    The template receives ``documents`` (a list of
    [`IndexEntry`][opm.chunking.IndexEntry]), ``title``, the ``odd_css`` string, the
    ``odd_css_url`` file chunking writes, and — when
    an assets setting is configured — an ``assets`` URL prefix plus
    ``asset_styles``, the stylesheets among those assets in declared order. The
    index sits at the output root, so those URLs carry no ``../`` prefix.

    Each entry exposes ``fragments``, so a project controls what the index shows
    by declaring global fragments in ``opm.toml`` — no code change needed to add
    an author or date column.
    """
    env = template_environment(template_path, xpath_env, project)
    tpl = load_template(env, template_path)
    return tpl.render(
        documents=entries,
        # The index sits at the output root, so menu URLs need no prefix.
        site_root=site_root,
        title=title,
        odd_css=odd_css or '',
        odd_css_url=odd_css_url,
        assets=assets,
        asset_styles=asset_styles or [],
        layout_css_url=layout_css_url,
        context=template_context(env, template_path.name, context),
    )


def render_typst_document_template(
    *,
    content_typst: str,
    template_path: Path,
    odd_typst: str | None,
    parameters: dict[str, str],
    metadata: dict | None = None,
    context: dict | None = None,
    xpath_env: XPathEnvironment | None = None,
) -> str:
    """Render Typst body content through the selected document shell."""
    env = template_environment(template_path, xpath_env)
    tpl = load_template(env, template_path, 'Typst template')
    return tpl.render(
        content_typst=content_typst,
        odd_typst=odd_typst or '',
        parameters=parameters or {},
        metadata=metadata or {},
        context=template_context(env, template_path.name, context),
    )
