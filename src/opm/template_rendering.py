"""Helpers for rendering full-document HTML through Jinja2 templates."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from lxml import etree

DEFAULT_TEMPLATE_NAME = 'default_document.html.j2'
DEFAULT_TYPST_TEMPLATE_NAME = 'default_document.typ.j2'


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
    user_css: str | None,
    parameters: dict[str, str],
    webcomponents_url: str | None = None,
) -> str:
    """Render a full HTML document through the selected Jinja2 template."""
    html_root = _first_html_root(serialized_html)
    if html_root is None:
        return serialized_html

    head = html_root.find('head')
    body = html_root.find('body')
    head_content = _inner_html(head)
    # HtmlOutputFunctions.document() already injects ODD CSS into <head>.
    # Skip the odd_css template variable when that happened so templates that
    # render both {{ head_html }} and {{ odd_css }} do not duplicate styles.
    # Chunked fragments have an empty head, so odd_css is still emitted there.
    effective_odd_css = odd_css or ''
    if effective_odd_css and effective_odd_css in head_content:
        effective_odd_css = ''
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=False,
    )
    try:
        tpl = env.get_template(template_path.name)
    except TemplateNotFound as e:
        raise FileNotFoundError(f'Template not found: {template_path}') from e
    return tpl.render(
        head_html=head_content,
        content_html=_inner_html(body),
        odd_css=effective_odd_css,
        user_css=user_css or '',
        parameters=parameters or {},
        lang=html_root.get('lang', ''),
        webcomponents_url=webcomponents_url,
    )


def _typst_template_loader(template_path: Path) -> FileSystemLoader:
    """Load templates from *template_path*'s directory and packaged defaults."""
    searchpaths = [str(template_path.parent)]
    packaged = default_template_path(DEFAULT_TYPST_TEMPLATE_NAME).parent
    packaged_str = str(packaged)
    if packaged_str not in searchpaths:
        searchpaths.append(packaged_str)
    return FileSystemLoader(searchpaths)


def render_typst_document_template(
    *,
    content_typst: str,
    template_path: Path,
    odd_typst: str | None,
    parameters: dict[str, str],
    metadata: dict | None = None,
) -> str:
    """Render Typst body content through the selected Jinja2 document shell."""
    env = Environment(
        loader=_typst_template_loader(template_path),
        autoescape=False,
    )
    try:
        tpl = env.get_template(template_path.name)
    except TemplateNotFound as e:
        raise FileNotFoundError(f'Typst template not found: {template_path}') from e
    return tpl.render(
        content_typst=content_typst,
        odd_typst=odd_typst or '',
        parameters=parameters or {},
        metadata=metadata or {},
    )
