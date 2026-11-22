# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Auxiliary pages (``[[pages]]``): standalone pages of a site beside the reading view.

Chunking splits a document into the pages you read; a page is one additional
address in the site — an "about" page, a register browser. Both run through
an ODD when they have a ``source``, but a page has a fixed ``path`` and none
of the reading-view furniture: no per-document subdirectory, no prev/next, no
listing as a document in the collection index (its ``menu`` label is listed
there instead).

``opm chunk`` renders the pages after the chunking runs, into the same output
root, via [`render_pages`][opm.pages.render_pages]. A page without ``source``
is static — its template alone is rendered. A page with ``source`` is a chunk
run in disguise: one page per node the selector finds when ``path`` holds a
``{placeholder}``, else a single page.
"""

from __future__ import annotations

import json
import posixpath
import re
from urllib.parse import quote, unquote
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from lxml import etree

from opm.assets import ASSETS_DIR, asset_styles, resolve_assets
from opm.chunking import chunk_document
from opm.config import ChunkingConfig, PageConfig
from opm.jinks_templates.merge import merge_deep
from opm.template_frontmatter import template_context
from opm.template_rendering import (
    LAYOUT_CSS_NAME,
    load_template,
    resolve_template_path,
    template_environment,
)
from opm.transform import load_transform_module, project_xpath_env, xpath_select
from opm.xml_parser import parse as xml_parse


@dataclass
class PageResult:
    """What rendering one ``[[pages]]`` entry wrote."""

    page: PageConfig
    """The page's config."""
    files: tuple[Path, ...]
    """The files written, absolute."""
    href: str
    """Link to the page's entry point, relative to the output root."""


def _page_dir_and_pattern(page: PageConfig) -> tuple[str, str]:
    """The page's ``path`` as ``(directory, file pattern)`` below the output root.

    ``places/{xml_id}.html`` → ``("places", "{xml_id}.html")``;
    ``about.html`` → ``("", "about.html")``.
    """
    rel = PurePosixPath(page.path)
    parent = str(rel.parent)
    return ('' if parent == '.' else parent), rel.name


def _url_prefix(page: PageConfig) -> str:
    """The path from the page back to the output root (``../`` per directory level)."""
    return '../' * max(len(PurePosixPath(page.path).parts) - 1, 0)


def _check_selection(page: PageConfig, xpath_env: Any) -> None:
    """Fail early when a page's selector does not fit its ``path``.

    A path with a placeholder takes one page per selected node; a path
    without one is a single page and must select exactly one node. Checked
    against the source here so a multi-node selection does not silently
    overwrite one file with the last node.
    """
    if page.selector or not page.source or not page.xpath:
        return
    tree = xml_parse(str(page.source))
    found = xpath_select(tree.getroot(), page.xpath, xpath_env=xpath_env)
    if not isinstance(found, list):
        found = [found] if found else []
    nodes = [node for node in found if isinstance(node, etree._Element)]
    multi = '{' in page.path
    if multi and not nodes:
        raise ValueError(f'pages path {page.path!r}: xpath selects nothing in {page.source}')
    if not multi and len(nodes) != 1:
        raise ValueError(
            f'pages path {page.path!r} has no placeholder, so it is a single page, '
            f'but xpath selects {len(nodes)} nodes in {page.source} — '
            'add a placeholder like {xml_id} for one page per node'
        )


def _render_static_page(
    project: Any,
    page: PageConfig,
    *,
    out_root: Path,
    run: ChunkingConfig,
    module_path: Path | None,
    webcomponents: bool,
    documents: Sequence[Mapping[str, str]] = (),
) -> PageResult:
    """Render a page without ``source``: the template alone, through no ODD."""
    template_path = resolve_template_path(
        page.template or run.template, project=project,
    )
    xpath_env = project_xpath_env(project.config, project.root)
    env = template_environment(template_path, xpath_env, project)
    tpl = load_template(env, template_path)
    prefix = _url_prefix(page)
    odd_name = getattr(load_transform_module(module_path), 'ODD_NAME', '') if module_path else ''
    odd_css = getattr(load_transform_module(module_path), 'ODD_GENERATED_CSS', '') if module_path else ''
    urls = {
        'odd_css_url': f'{prefix}css/{odd_name}.css' if odd_css and odd_name else '',
        'layout_css_url': (
            f'{prefix}css/{LAYOUT_CSS_NAME}' if (out_root / 'css' / LAYOUT_CSS_NAME).is_file() else ''
        ),
        'assets': f'{prefix}{ASSETS_DIR}' if run.assets else '',
        'asset_styles': asset_styles(
            resolve_assets(project.root, run.assets), prefix,
        ),
        'site_root': prefix,
    }
    context = template_context(
        merge_deep(project.config.context_for('web', webcomponents=webcomponents), page.context or {}),
    )
    rendered = tpl.render(
        content_html='',
        head_html='',
        context={**context, **urls},
        site_documents=_documents_from(documents, prefix),
    )
    target = out_root / page.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding='utf-8')
    return PageResult(page=page, files=(target,), href=page.path)


def _render_data_page(
    project: Any,
    page: PageConfig,
    *,
    out_root: Path,
    run: ChunkingConfig,
    webcomponents: bool,
    xpath_extensions: Sequence[str] | None,
    anchors: Mapping[str, str] | None,
    on_progress: Callable[[int, int], None] | None,
    documents: Sequence[Mapping[str, str]] = (),
) -> PageResult | None:
    """Render a page with ``source``: a chunk run over that source, into the page's directory.

    Returns *None* when a profile-contributed page's ``source`` is missing —
    the profile's default for a project that has no such data.
    """
    if page.source is None:
        raise ValueError(f'pages path {page.path!r} has no source')
    if not page.source.is_file():
        if page.from_profile:
            # A profile ships defaults for projects that may not have the
            # data; the page is simply not built.
            return None
        raise FileNotFoundError(f'pages path {page.path!r}: source not found: {page.source}')
    directory, pattern = _page_dir_and_pattern(page)
    if out_root.is_relative_to(project.root):
        out_rel = out_root.relative_to(project.root).as_posix().strip('/')
        page_out_rel = f'{out_rel}/{directory}'.strip('/') if directory else out_rel
    else:
        # Output outside the project (e.g. an editor preview's temp folder):
        # an absolute output_dir, which the chunker's root / output_dir keeps.
        page_out_rel = str(out_root / directory if directory else out_root)

    module_path = run.module
    if page.odd is not None:
        module_path = project._resolve('web', page.odd, packaged_default=False).module_path
    synth = replace(
        run,
        name=None,
        output_dir=page_out_rel,
        xpath=page.xpath if page.xpath is not None else run.xpath,
        selector=page.selector if page.selector is not None else run.selector,
        template=page.template or run.template,
        odd=page.odd or run.odd,
        parameters=page.parameters if page.parameters is not None else run.parameters,
        fragments=page.fragments,
        file_pattern=pattern,
        document_name=None,
        link_doc=None,
        module=module_path,
    )
    xpath_env = project_xpath_env(project.config, page.source, extensions=xpath_extensions)
    _check_selection(page, xpath_env)
    # The inherited anchors are relative to the output root; from a page one
    # directory down they need the page's own prefix.
    prefix = _url_prefix(page)
    page_anchors = (
        {xml_id: f'{prefix}{chunk_file}' for xml_id, chunk_file in anchors.items()}
        if prefix and anchors else anchors
    )
    chunk_document(
        module_path=module_path,
        xml_path=page.source,
        config=synth,
        project=project,
        webcomponents=webcomponents,
        xpath_extensions=tuple(xpath_extensions) if xpath_extensions else None,
        output_format='html',
        anchors=page_anchors,
        merge_manifest=False,
        shared_root=out_root,
        url_prefix=_url_prefix(page),
        role='page',
        on_progress=on_progress,
        context=page.context,
        template_variables={
            'site_documents': _documents_from(documents, prefix),
        },
    )
    page_dir = out_root / directory if directory else out_root
    manifest_file = page_dir / 'manifest.json'
    files: list[Path] = []
    if manifest_file.is_file():
        chunks = json.loads(manifest_file.read_text(encoding='utf-8')).get('chunks') or []
        files = [page_dir / entry['file'] for entry in chunks]
    if not files:
        files = [out_root / page.path]
    href = f'{directory}/{files[0].name}' if directory else files[0].name
    return PageResult(page=page, files=tuple(files), href=href)


def _documents_from(documents: Sequence[Mapping[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """The site's documents as a page at *prefix* links to them."""
    return [{**doc, 'href': f"{prefix}{doc['href']}"} for doc in documents]


_HREF_RE = re.compile(r'(\shref=")([^"#?]+)([^"]*)(")')


def _resolve_page_links(out_root: Path, results: Sequence[PageResult]) -> None:
    """Point jinks-style links between pages at the files opm wrote.

    TEI Publisher addresses a page by its path below the context path and
    without a suffix: the stock ODD's register overview links an entry as
    ``people/{id}``. opm writes ``people/{id}.html``, and a link from
    ``people/index.html`` is relative to that page. A relative ``href`` that
    does not name an existing file, but names a page once ``.html`` is added
    and it is read from the site root, is rewritten to that page, relative to
    the file it is in. Every other link is left alone.
    """
    files = [file for result in results for file in result.files]
    known = {file.relative_to(out_root).as_posix() for file in files if file.is_relative_to(out_root)}
    if not known:
        return
    for file in files:
        if file.suffix != '.html' or not file.is_file():
            continue
        here = file.parent.relative_to(out_root).as_posix() if file.parent != out_root else '.'

        def fix(match: re.Match, file: Path = file, here: str = here) -> str:
            raw = match.group(2)
            if '://' in raw or raw.startswith(('/', '.', 'mailto:', 'javascript:')):
                return match.group(0)
            # An ODD may percent-encode the id (`Enge_Z%C3%BCrich`); files
            # are named by the id itself.
            href = unquote(raw)
            if (file.parent / href).exists():
                return match.group(0)
            target = f'{href.rstrip("/")}.html'
            if target not in known:
                return match.group(0)
            rel = quote(posixpath.relpath(target, here), safe='/')
            return f'{match.group(1)}{rel}{match.group(3)}{match.group(4)}'

        html = file.read_text(encoding='utf-8')
        fixed = _HREF_RE.sub(fix, html)
        if fixed != html:
            file.write_text(fixed, encoding='utf-8')


def render_pages(
    project: Any,
    *,
    out_dir: Path,
    run: ChunkingConfig,
    webcomponents: bool = False,
    xpath_extensions: Sequence[str] | None = None,
    anchors: Mapping[str, str] | None = None,
    only: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    documents: Sequence[Mapping[str, str]] = (),
) -> list[PageResult]:
    """Render every ``[[pages]]`` entry of *project*'s config into *out_dir*.

    *run* is the first chunking run: pages inherit its ODD, template, assets
    and parameters unless they set their own. *anchors* is the map of the
    chunking runs' ids to their files (prefixed with each document's
    directory), so pages can link into the reading view. *only* limits the
    build to pages whose ``path`` starts with it (``--page``).

    *documents* are the chunked documents, each a map of ``name``, ``path``
    (the source file) and ``href`` (its first page, relative to the output
    root). Page templates receive them as ``site_documents``, with ``href``
    relative to the page. Links between pages written the TEI Publisher way are then
    resolved, see [`_resolve_page_links`][opm.pages._resolve_page_links].

    Pages are rendered in config order, HTML only — ``--format json`` and
    ``pb-view`` feed external site generators, which build their own pages.
    """
    results: list[PageResult] = []
    for page in project.config.pages:
        if only and not page.path.startswith(only):
            continue
        if not page.enabled:
            continue
        if page.source is None:
            result = _render_static_page(
                project, page,
                out_root=out_dir, run=run, module_path=run.module,
                webcomponents=webcomponents, documents=documents,
            )
        else:
            result = _render_data_page(
                project, page,
                out_root=out_dir, run=run, webcomponents=webcomponents,
                xpath_extensions=xpath_extensions, anchors=anchors,
                on_progress=on_progress, documents=documents,
            )
        if result is not None:
            results.append(result)
    _resolve_page_links(out_dir, results)
    return results
