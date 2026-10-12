# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers for wrapping transform output in Jinja2 templates (HTML and Typst)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, TemplateNotFound
from lxml import etree

from opm.output_modes import RENDER_MODES
from opm.template_frontmatter import FrontmatterLoader, template_context

DEFAULT_TEMPLATE_NAME: str = RENDER_MODES['web'].default_template  # type: ignore[assignment]
DEFAULT_PRINT_TEMPLATE_NAME: str = RENDER_MODES['print'].default_template  # type: ignore[assignment]
DEFAULT_TYPST_TEMPLATE_NAME: str = RENDER_MODES['typst'].default_template  # type: ignore[assignment]
DEFAULT_INDEX_TEMPLATE_NAME = 'default_index.html.j2'


def default_template_path(template_name: str = DEFAULT_TEMPLATE_NAME) -> Path:
    """Return the path to a packaged default document template."""
    return Path(
        str(resources.files('opm').joinpath(f'resources/templates/{template_name}'))
    )


def resolve_template_path(
    template_path: Path | None,
    *,
    default_name: str = DEFAULT_TEMPLATE_NAME,
) -> Path:
    """Resolve override template path or packaged default template."""
    path = (
        template_path
        if template_path is not None
        else default_template_path(default_name)
    )
    if not path.is_file():
        raise FileNotFoundError(f'Template not found: {path}')
    return path


#: The stylesheet of the packaged page layout (``opm/layout.html.j2``), in
#: ``resources/templates/opm/``.
LAYOUT_CSS_NAME = 'opm-layout.css'


def layout_css(templates_dir: Path | None = None) -> str:
    """The stylesheet behind ``opm/layout.html.j2``.

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


def template_environment(template_path: Path) -> Environment:
    """A Jinja2 environment for rendering *template_path*.

    Templates are looked up in *template_path*'s directory first, then among
    the packaged ones, so a project template can ``{% extends
    "opm/layout.html.j2" %}`` and can replace a packaged file by giving its
    own the same relative path. Frontmatter is removed from every source and
    feeds the template ``context`` (see
    [`template_context`][opm.template_frontmatter.template_context]).
    """
    searchpaths = [str(template_path.parent)]
    packaged = str(packaged_templates_dir())
    if packaged not in searchpaths:
        searchpaths.append(packaged)
    return Environment(loader=FrontmatterLoader(searchpaths), autoescape=False)


def load_template(env: Environment, template_path: Path, label: str = 'Template'):
    """Load *template_path* from *env*, raising ``FileNotFoundError`` if missing."""
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
) -> str:
    """Render a full HTML document through the selected Jinja2 template.

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
    env = template_environment(template_path)
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
    env = template_environment(template_path)
    tpl = load_template(env, template_path)
    return tpl.render(
        documents=entries,
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
) -> str:
    """Render Typst body content through the selected Jinja2 document shell."""
    env = template_environment(template_path)
    tpl = load_template(env, template_path, 'Typst template')
    return tpl.render(
        content_typst=content_typst,
        odd_typst=odd_typst or '',
        parameters=parameters or {},
        metadata=metadata or {},
        context=template_context(env, template_path.name, context),
    )
