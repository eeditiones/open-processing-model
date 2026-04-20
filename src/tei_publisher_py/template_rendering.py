"""Helpers for rendering full-document HTML through Jinja2 templates."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from lxml import etree

DEFAULT_TEMPLATE_NAME = 'default_document.html.j2'


def default_template_path() -> Path:
    """Return the packaged default document template path."""
    return Path(resources.files('tei_publisher_py').joinpath(f'templates/{DEFAULT_TEMPLATE_NAME}'))


def resolve_template_path(template_path: Path | None) -> Path:
    """Resolve override template path or packaged default template."""
    path = template_path if template_path is not None else default_template_path()
    if not path.is_file():
        raise FileNotFoundError(f'Template not found: {path}')
    return path


def _inner_html(el: etree._Element | None) -> str:
    if el is None:
        return ''
    parts: list[str] = [el.text or '']
    for child in el:
        parts.append(etree.tostring(child, encoding='unicode', method='html'))
    return ''.join(parts)


def _first_html_root(serialized_html: str) -> etree._Element | None:
    parser = etree.HTMLParser()
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
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=False,
    )
    try:
        tpl = env.get_template(template_path.name)
    except TemplateNotFound as e:
        raise FileNotFoundError(f'Template not found: {template_path}') from e
    return tpl.render(
        head_html=_inner_html(head),
        content_html=_inner_html(body),
        odd_css=odd_css or '',
        user_css=user_css or '',
        parameters=parameters or {},
        lang=html_root.get('lang', ''),
        webcomponents_url=webcomponents_url,
    )
