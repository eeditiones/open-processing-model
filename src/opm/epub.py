# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""EPUB 3 packager — ZIP container around EPUB-mode HTML transforms.

Mirrors ``tei-publisher-app/modules/lib/epub.xql``: chapter XHTML, OPF, nav,
NCX, stylesheet, and images. Uses stdlib ``zipfile`` (no ebooklib).
"""

from __future__ import annotations

import importlib
import io
import mimetypes
import re
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

from lxml import etree

from opm.config import ChunkingConfig
from opm.resources import packaged_epub_css
from opm.runtime.output_functions import XML_ID, XML_LANG

XHTML_NS = 'http://www.w3.org/1999/xhtml'
EPUB_NS = 'http://www.idpf.org/2007/ops'
OPF_NS = 'http://www.idpf.org/2007/opf'
DC_NS = 'http://purl.org/dc/elements/1.1/'
NCX_NS = 'http://www.daisy.org/z3986/2005/ncx/'
CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'

EPUB_TYPE = f'{{{EPUB_NS}}}type'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
DOCBOOK_NS = 'http://docbook.org/ns/docbook'

_SAFE_ID = re.compile(r'[^A-Za-z0-9_-]+')

# EPUB 3 content documents are XHTML; anything else is degraded to div/span.
XHTML_TAGS = frozenset({
    'a', 'abbr', 'address', 'area', 'article', 'aside', 'audio', 'b', 'bdi',
    'bdo', 'blockquote', 'body', 'br', 'button', 'canvas', 'caption', 'cite',
    'code', 'col', 'colgroup', 'data', 'datalist', 'dd', 'del', 'details',
    'dfn', 'dialog', 'div', 'dl', 'dt', 'em', 'embed', 'fieldset',
    'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5',
    'h6', 'head', 'header', 'hgroup', 'hr', 'html', 'i', 'iframe', 'img',
    'input', 'ins', 'kbd', 'label', 'legend', 'li', 'link', 'main', 'map',
    'mark', 'menu', 'meta', 'meter', 'nav', 'noscript', 'object', 'ol',
    'optgroup', 'option', 'output', 'p', 'param', 'picture', 'pre', 'progress',
    'q', 'rp', 'rt', 'ruby', 's', 'samp', 'script', 'section', 'select',
    'small', 'source', 'span', 'strong', 'style', 'sub', 'summary', 'sup',
    'table', 'tbody', 'td', 'template', 'textarea', 'tfoot', 'th', 'thead',
    'time', 'title', 'tr', 'track', 'u', 'ul', 'var', 'video', 'wbr',
})

BLOCK_TAGS = frozenset({
    'address', 'blockquote', 'div', 'dl', 'figure', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'hr', 'ol', 'p', 'pre', 'section', 'table', 'ul',
})


@dataclass
class EpubMetadata:
    title: str = 'Untitled'
    creator: str = 'Unknown'
    language: str = 'en'
    urn: str = field(default_factory=lambda: f'urn:uuid:{uuid.uuid4()}')


@dataclass
class EpubChapter:
    element: etree._Element
    file_id: str
    title: str
    anchor_id: str


def _local(el: etree._Element) -> str:
    """Local name of *el*, or ``''`` for a comment or processing instruction.

    ``iter()`` yields those alongside elements and ``QName`` rejects them, so
    every walk over a source document would otherwise have to guard itself.
    They have no name, and the empty string matches none of the names callers
    look for.
    """
    if not isinstance(el.tag, str):
        return ''
    return etree.QName(el).localname


def _safe_file_id(raw: str, used: set[str], fallback: str) -> str:
    stem = _SAFE_ID.sub('_', raw).strip('_') or fallback
    if stem[0].isdigit():
        stem = f'c{stem}'
    candidate = stem
    n = 2
    while candidate in used:
        candidate = f'{stem}_{n}'
        n += 1
    used.add(candidate)
    return candidate


def extract_epub_metadata(root: etree._Element) -> EpubMetadata:
    """Pull Dublin Core-ish fields from a TEI or DocBook header."""
    title = 'Untitled'
    creator = 'Unknown'
    language = 'en'

    root_lang = root.get(XML_LANG) or root.get('lang')
    if root_lang:
        language = root_lang

    # Prefer explicit header language.
    for el in root.iter():
        if _local(el) in ('teiHeader', 'info') and el.get(XML_LANG):
            language = el.get(XML_LANG)  # type: ignore[assignment]
            break

    titles = [
        el for el in root.iter()
        if _local(el) == 'title' and el.getparent() is not None
        and _local(el.getparent()) in ('titleStmt', 'info', 'bibl', 'biblStruct')
    ]
    if not titles:
        titles = [el for el in root.iter() if _local(el) == 'title']
    if titles:
        text = ' '.join(titles[0].itertext()).strip()
        if text:
            title = text

    authors = [el for el in root.iter() if _local(el) in ('author', 'editor')]
    if authors:
        text = ' '.join(authors[0].itertext()).strip()
        if text:
            creator = text

    return EpubMetadata(title=title, creator=creator, language=language)


# Selectors that carve a chunk per page-break milestone rather than per division.
_PAGE_SELECTORS = frozenset({'opm.navigation.tei_pb_chunks'})

# Depth used when falling back from page chunking. ``depth`` carries no meaning
# for a page selector, so there is nothing to inherit. Division chunkers return
# leaves only, so this reads as "chunk at the finest division level": scenes in
# a play (play/act/scene), sections in a volume, and still the top-level divs of
# a document that is only one or two levels deep.
_PAGE_FALLBACK_DEPTH = 3


def _default_selector(root: etree._Element) -> str:
    ns = root.nsmap.get(None, '') or ''
    if DOCBOOK_NS in ns or 'docbook' in ns:
        return 'opm.navigation.dbk_section_chunks'
    return 'opm.navigation.tei_div_chunks'


def select_epub_chapters(
    root: etree._Element,
    chunking: ChunkingConfig | None = None,
) -> list[etree._Element]:
    """Select chapter roots using chunking config (or TEI/DocBook defaults).

    Page-milestone chunking is overridden. It is the right unit for a facsimile
    reading view, where a folio image sits beside its transcription, but an EPUB
    has no facsimile column and reading systems repaginate anyway: it would turn
    the book into a run of headless part-scenes broken mid-sentence. Divisions
    are the chapter unit here whatever the reading view is configured to do.
    """
    cfg = chunking or ChunkingConfig(
        depth=1,
        selector=_default_selector(root),
    )
    if cfg.selector in _PAGE_SELECTORS:
        cfg = replace(
            cfg,
            selector=_default_selector(root),
            xpath=None,
            depth=_PAGE_FALLBACK_DEPTH,
        )
    if cfg.selector:
        module_name, _, func_name = cfg.selector.rpartition('.')
        selector_fn = getattr(importlib.import_module(module_name), func_name)
        chunks = selector_fn(root, cfg)
    else:
        # Lazy import avoids a transform↔epub cycle at module load.
        from opm.transform import xpath_select

        chunks = xpath_select(root, cfg.xpath or '//text/body/div')

    if not isinstance(chunks, list):
        chunks = [chunks] if chunks else []
    chapters = [c for c in chunks if isinstance(c, etree._Element)]
    if chapters:
        return chapters

    # Fallback: whole ``text`` / ``book`` / document root.
    for name in ('text', 'book'):
        for el in root.iter():
            if _local(el) == name:
                return [el]
    return [root]


HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})


def _has_text(el: etree._Element) -> bool:
    return bool(' '.join(el.itertext()).strip())


def _collect_opening_headings(el: etree._Element, parts: list[str]) -> bool:
    """Gather the headings *el* opens with; return False at the body proper."""
    if el.text and el.text.strip():
        return False
    for child in el:
        if not isinstance(child.tag, str):
            continue
        if _local(child) in HEADING_TAGS:
            text = ' '.join(child.itertext()).strip()
            if text:
                parts.append(text)
        elif any(_local(d) in HEADING_TAGS for d in child.iter()):
            # A wrapper standing between the chapter root and its headings.
            if not _collect_opening_headings(child, parts):
                return False
        elif _has_text(child):
            return False
        if child.tail and child.tail.strip():
            return False
    return True


def _rendered_heading_text(nodes: Sequence[etree._Element]) -> str | None:
    """The heading a reader sees at the top of the chapter, once transformed.

    A table of contents should name a chapter the way the chapter names itself,
    and the ODD is where that name is decided: a parallel-text edition heads its
    two halves "Transcription" and "Translation" though neither word appears in
    the source, and a play heads a scene from numbers the source carries only as
    attributes. Consecutive opening headings are joined, because it is the pair
    that identifies the chapter ("Act 2, Scene 1"), not the first of them.
    """
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node.tag, str):
            continue
        if _local(node) in HEADING_TAGS:
            text = ' '.join(node.itertext()).strip()
            if text:
                parts.append(text)
            continue
        # Anything else after a heading is the body: whatever headings it may
        # contain further down belong to sections, not to the chapter.
        if parts or not _collect_opening_headings(node, parts):
            break
    return ', '.join(parts) or None


def _chapter_heading_text(el: etree._Element) -> str | None:
    """First ``head`` / ``title`` under *el*, skipping nested notes."""
    for child in el.iter():
        if _local(child) not in ('head', 'title'):
            continue
        # Skip titles nested inside notes / footnotes.
        skip = False
        parent = child.getparent()
        while parent is not None and parent is not el:
            if _local(parent) == 'note':
                skip = True
                break
            parent = parent.getparent()
        if skip:
            continue
        cleaned = ' '.join(child.itertext()).strip()
        if cleaned:
            return cleaned
    return None


def _milestone_label(el: etree._Element) -> str | None:
    """``Page 104`` for a headless chunk carved at a ``pb`` milestone.

    Page-based chunking (``tei_pb_chunks``) produces one chapter per folio, and
    most folios open mid-scene with no ``head`` to name them. The printed page
    number is what a reader would use, so it beats a run of "Untitled" entries
    in the table of contents.
    """
    for node in el.iter():
        if _local(node) != 'pb':
            continue
        n = (node.get('n') or '').strip()
        return f'Page {n}' if n else None
    return None


def _build_chapter_list(
    elements: Sequence[etree._Element],
) -> list[EpubChapter]:
    used: set[str] = set()
    chapters: list[EpubChapter] = []
    for i, el in enumerate(elements, start=1):
        xml_id = el.get(XML_ID) or ''
        file_id = _safe_file_id(xml_id or f'chapter-{i}', used, f'chapter-{i}')
        anchor = xml_id or file_id
        chapters.append(
            EpubChapter(
                element=el,
                file_id=file_id,
                # Provisional: the transform may name the chapter better than
                # the source does. Resolved in :func:`build_epub`.
                title=_chapter_heading_text(el) or '',
                anchor_id=anchor,
            )
        )
    return chapters


def _find_header(root: etree._Element) -> etree._Element | None:
    for el in root.iter():
        if _local(el) == 'fileDesc':
            return el
    for el in root.iter():
        if _local(el) == 'info' and el.getparent() is not None and _local(el.getparent()) in (
            'book', 'article', 'chapter',
        ):
            return el
    return None


def _rewrite_to_xhtml(node: etree._Element) -> etree._Element:
    """Deep-copy *node* into the XHTML namespace, dropping non-XHTML vocabulary.

    Custom elements (``pb-observable`` and friends, usually introduced by a
    ``pb:template``) are not part of the EPUB 3 content model, and reading
    systems treat unknown tags as inline — which wrecks block layout. They are
    replaced by a transparent ``div`` / ``span``, keeping their children.
    """
    q = etree.QName(node)
    local = q.localname
    known = local in XHTML_TAGS

    new = etree.Element(f'{{{XHTML_NS}}}{local if known else "div"}')
    new.text = node.text
    for k, v in node.attrib.items():
        # @slot wires a child into a custom element's shadow DOM. With the
        # element itself degraded to a div, it names nothing.
        if k == 'slot':
            continue
        if known or _is_portable_attribute(k):
            new.set(k, v)

    for child in node:
        # Comments and processing instructions have no place in the package.
        if not isinstance(child.tag, str):
            continue
        # <template> is inert without the component that would stamp it out:
        # dead weight in the package, and its content would surface as stray
        # text in reading systems that ignore the element.
        if etree.QName(child).localname == 'template':
            continue
        new_child = _rewrite_to_xhtml(child)
        new_child.tail = child.tail
        new.append(new_child)

    if not known and not _has_block_child(new):
        new.tag = f'{{{XHTML_NS}}}span'
    return new


def _is_portable_attribute(name: str) -> bool:
    """Whether an attribute survives onto a degraded custom element."""
    if name.startswith(f'{{{EPUB_NS}}}') or name.startswith(f'{{{XML_NS}}}'):
        return True
    return name in ('class', 'id', 'dir', 'lang', 'title') or name.startswith('data-')


def _has_block_child(el: etree._Element) -> bool:
    return any(
        isinstance(child.tag, str) and etree.QName(child).localname in BLOCK_TAGS
        for child in el
    )


def _collect_body_nodes(result: list) -> list[etree._Element]:
    nodes: list[etree._Element] = []
    for item in result:
        if isinstance(item, etree._Element):
            # Comments and processing instructions are _Element too, and have
            # no place in the package.
            if not isinstance(item.tag, str):
                continue
            q = etree.QName(item)
            if q.localname == 'html':
                body = item.find('.//{*}body')
                if body is not None:
                    for child in body:
                        if isinstance(child.tag, str):
                            nodes.append(_rewrite_to_xhtml(child))
                else:
                    nodes.append(_rewrite_to_xhtml(item))
            else:
                nodes.append(_rewrite_to_xhtml(item))
        elif isinstance(item, str) and item.strip():
            span = etree.Element(f'{{{XHTML_NS}}}span')
            span.text = item
            nodes.append(span)
    return nodes


def _is_footnote_aside(el: etree._Element) -> bool:
    return _local(el) == 'aside' and el.get(EPUB_TYPE) == 'footnote'


def _strip_footnotes(nodes: list[etree._Element]) -> tuple[list[etree._Element], list[etree._Element]]:
    footnotes: list[etree._Element] = []

    def walk(el: etree._Element) -> etree._Element | None:
        if _is_footnote_aside(el):
            footnotes.append(el)
            return None
        kept_children = []
        for child in list(el):
            if not isinstance(child.tag, str):
                continue
            walked = walk(child)
            if walked is None:
                # remove footnote; preserve tail onto previous sibling / parent text
                tail = child.tail
                el.remove(child)
                # The aside is now queued for the footnotes section: leaving its
                # tail attached would repeat that run of text down there.
                child.tail = None
                if tail:
                    if kept_children:
                        kept_children[-1].tail = (kept_children[-1].tail or '') + tail
                    else:
                        el.text = (el.text or '') + tail
            else:
                kept_children.append(walked)
        return el

    cleaned: list[etree._Element] = []
    for node in nodes:
        if _is_footnote_aside(node):
            footnotes.append(node)
            continue
        walked = walk(node)
        if walked is not None:
            cleaned.append(walked)
    return cleaned, footnotes


def assemble_xhtml(
    title: str,
    language: str,
    body_nodes: list[etree._Element],
) -> etree._Element:
    """Build an EPUB XHTML document; hoist footnote asides to a footnotes section."""
    cleaned, footnotes = _strip_footnotes(body_nodes)

    html = etree.Element(
        f'{{{XHTML_NS}}}html',
        nsmap={None: XHTML_NS, 'epub': EPUB_NS},
    )
    html.set(XML_LANG, language)
    head = etree.SubElement(html, f'{{{XHTML_NS}}}head')
    title_el = etree.SubElement(head, f'{{{XHTML_NS}}}title')
    title_el.text = title
    link = etree.SubElement(head, f'{{{XHTML_NS}}}link')
    link.set('type', 'text/css')
    link.set('rel', 'stylesheet')
    link.set('href', 'stylesheet.css')
    body = etree.SubElement(html, f'{{{XHTML_NS}}}body')
    for node in cleaned:
        body.append(node)
    if footnotes:
        section = etree.SubElement(body, f'{{{XHTML_NS}}}section')
        section.set(EPUB_TYPE, 'footnotes')
        for fn in footnotes:
            section.append(fn)
    return html


def _serialize_xhtml(doc: etree._Element) -> bytes:
    return etree.tostring(
        doc,
        method='xml',
        encoding='utf-8',
        xml_declaration=True,
        pretty_print=False,
    )


def _transform_fragment(
    mod: ModuleType,
    element: etree._Element,
    transform_opts: dict[str, Any] | None,
    xpath_env: Any = None,
) -> list[etree._Element]:
    result = mod.transform(element, dict(transform_opts or {}) or None, xpath_env=xpath_env)
    return _collect_body_nodes(list(result or []))


def _image_media_type(path: str) -> str:
    suffix = Path(path).suffix.lstrip('.').lower()
    mapping = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'svg': 'image/svg+xml',
        'tif': 'image/tiff',
        'tiff': 'image/tiff',
        'webp': 'image/webp',
    }
    if suffix in mapping:
        return mapping[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or 'application/octet-stream'


def _resolve_image_sources(
    hrefs: Sequence[str],
    base_dir: Path | None,
) -> dict[str, Path]:
    """Map each ``img/@src`` to a file on disk, dropping the ones that are missing.

    Looked up next to the source document and in a sibling ``images/``
    directory, the layout TEI Publisher uses. Unresolved images are left out of
    the manifest entirely — an OPF item without a file makes the EPUB invalid.
    """
    resolved: dict[str, Path] = {}
    for href in hrefs:
        candidate = Path(href)
        if candidate.is_absolute():
            if candidate.is_file():
                resolved[href] = candidate
            continue
        if base_dir is None:
            continue
        for path in (base_dir / href, base_dir / 'images' / href):
            if path.is_file():
                resolved[href] = path
                break
    return resolved


def _collect_img_srcs(*docs: etree._Element) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for doc in docs:
        for img in doc.iter(f'{{{XHTML_NS}}}img'):
            src = img.get('src')
            if src and src not in seen and not src.startswith(('http://', 'https://', 'data:')):
                seen.add(src)
                out.append(src)
    return out


def _build_opf(
    meta: EpubMetadata,
    chapters: list[EpubChapter],
    *,
    skip_title: bool,
    image_hrefs: Sequence[str],
    font_names: Sequence[str],
    cover_image: str | None,
    modified: str,
) -> bytes:
    package = etree.Element(
        f'{{{OPF_NS}}}package',
        nsmap={None: OPF_NS, 'dc': DC_NS},
    )
    package.set('unique-identifier', 'bookid')
    package.set('version', '3.0')

    metadata = etree.SubElement(package, f'{{{OPF_NS}}}metadata')
    # dc elements need the dc namespace
    dc_title = etree.SubElement(metadata, f'{{{DC_NS}}}title')
    dc_title.text = meta.title
    dc_creator = etree.SubElement(metadata, f'{{{DC_NS}}}creator')
    dc_creator.text = meta.creator
    dc_id = etree.SubElement(metadata, f'{{{DC_NS}}}identifier')
    dc_id.set('id', 'bookid')
    dc_id.text = meta.urn
    dc_lang = etree.SubElement(metadata, f'{{{DC_NS}}}language')
    dc_lang.text = meta.language
    mod_el = etree.SubElement(metadata, f'{{{OPF_NS}}}meta')
    mod_el.set('property', 'dcterms:modified')
    mod_el.text = modified
    if cover_image:
        cover_meta = etree.SubElement(metadata, f'{{{OPF_NS}}}meta')
        cover_meta.set('name', 'cover')
        cover_meta.set('content', cover_image)

    manifest = etree.SubElement(package, f'{{{OPF_NS}}}manifest')
    ncx_item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
    ncx_item.set('id', 'ncx')
    ncx_item.set('href', 'toc.ncx')
    ncx_item.set('media-type', 'application/x-dtbncx+xml')
    nav_item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
    nav_item.set('id', 'nav')
    nav_item.set('href', 'nav.xhtml')
    nav_item.set('media-type', 'application/xhtml+xml')
    nav_item.set('properties', 'nav')
    if not skip_title:
        title_item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
        title_item.set('id', 'title')
        title_item.set('href', 'title.xhtml')
        title_item.set('media-type', 'application/xhtml+xml')
    for ch in chapters:
        item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
        item.set('id', ch.file_id)
        item.set('href', f'{ch.file_id}.xhtml')
        item.set('media-type', 'application/xhtml+xml')
    css_item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
    css_item.set('id', 'css')
    css_item.set('href', 'stylesheet.css')
    css_item.set('media-type', 'text/css')
    for href in image_hrefs:
        item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
        item.set('id', _SAFE_ID.sub('_', href))
        item.set('href', href)
        item.set('media-type', _image_media_type(href))
        if cover_image and cover_image == href:
            item.set('properties', 'cover-image')
    for name in font_names:
        item = etree.SubElement(manifest, f'{{{OPF_NS}}}item')
        item.set('id', name)
        item.set('href', f'Fonts/{name}')
        item.set('media-type', 'application/x-font-truetype')

    spine = etree.SubElement(package, f'{{{OPF_NS}}}spine')
    spine.set('toc', 'ncx')
    if not skip_title:
        etree.SubElement(spine, f'{{{OPF_NS}}}itemref').set('idref', 'title')
    for ch in chapters:
        etree.SubElement(spine, f'{{{OPF_NS}}}itemref').set('idref', ch.file_id)

    return etree.tostring(package, method='xml', encoding='utf-8', xml_declaration=True)


def _build_nav(meta: EpubMetadata, chapters: list[EpubChapter], *, skip_title: bool) -> bytes:
    html = etree.Element(
        f'{{{XHTML_NS}}}html',
        nsmap={None: XHTML_NS, 'epub': EPUB_NS},
    )
    html.set('lang', meta.language)
    html.set(XML_LANG, meta.language)
    head = etree.SubElement(html, f'{{{XHTML_NS}}}head')
    title_el = etree.SubElement(head, f'{{{XHTML_NS}}}title')
    title_el.text = 'Navigation'
    meta_el = etree.SubElement(head, f'{{{XHTML_NS}}}meta')
    meta_el.set('http-equiv', 'Content-Type')
    meta_el.set('content', 'text/html; charset=utf-8')
    body = etree.SubElement(html, f'{{{XHTML_NS}}}body')
    nav = etree.SubElement(body, f'{{{XHTML_NS}}}nav')
    nav.set(EPUB_TYPE, 'toc')
    ol = etree.SubElement(nav, f'{{{XHTML_NS}}}ol')
    if not skip_title:
        li = etree.SubElement(ol, f'{{{XHTML_NS}}}li')
        a = etree.SubElement(li, f'{{{XHTML_NS}}}a')
        a.set('href', 'title.xhtml')
        a.text = 'Title'
    for ch in chapters:
        li = etree.SubElement(ol, f'{{{XHTML_NS}}}li')
        a = etree.SubElement(li, f'{{{XHTML_NS}}}a')
        a.set('href', f'{ch.file_id}.xhtml#{ch.anchor_id}')
        a.text = ch.title
    return _serialize_xhtml(html)


def _build_ncx(meta: EpubMetadata, chapters: list[EpubChapter], *, skip_title: bool) -> bytes:
    ncx = etree.Element(f'{{{NCX_NS}}}ncx', nsmap={None: NCX_NS})
    ncx.set('version', '2005-1')
    head = etree.SubElement(ncx, f'{{{NCX_NS}}}head')
    for name, content in (
        ('dtb:uid', meta.urn),
        ('dtb:depth', '2'),
        ('dtb:totalPageCount', '0'),
        ('dtb:maxPageNumber', '0'),
    ):
        m = etree.SubElement(head, f'{{{NCX_NS}}}meta')
        m.set('name', name)
        m.set('content', content)
    doc_title = etree.SubElement(ncx, f'{{{NCX_NS}}}docTitle')
    text_el = etree.SubElement(doc_title, f'{{{NCX_NS}}}text')
    text_el.text = meta.title
    nav_map = etree.SubElement(ncx, f'{{{NCX_NS}}}navMap')
    play = 1
    if not skip_title:
        np = etree.SubElement(nav_map, f'{{{NCX_NS}}}navPoint')
        np.set('id', 'navpoint-title')
        np.set('playOrder', str(play))
        play += 1
        label = etree.SubElement(np, f'{{{NCX_NS}}}navLabel')
        etree.SubElement(label, f'{{{NCX_NS}}}text').text = 'Title'
        etree.SubElement(np, f'{{{NCX_NS}}}content').set('src', 'title.xhtml')
    for ch in chapters:
        np = etree.SubElement(nav_map, f'{{{NCX_NS}}}navPoint')
        np.set('id', f'navpoint-{ch.file_id}')
        np.set('playOrder', str(play))
        play += 1
        label = etree.SubElement(np, f'{{{NCX_NS}}}navLabel')
        etree.SubElement(label, f'{{{NCX_NS}}}text').text = ch.title
        etree.SubElement(np, f'{{{NCX_NS}}}content').set(
            'src', f'{ch.file_id}.xhtml#{ch.anchor_id}',
        )
    return etree.tostring(ncx, method='xml', encoding='utf-8', xml_declaration=True)


def _container_xml() -> bytes:
    container = etree.Element(
        f'{{{CONTAINER_NS}}}container',
        nsmap={None: CONTAINER_NS},
    )
    container.set('version', '1.0')
    rootfiles = etree.SubElement(container, f'{{{CONTAINER_NS}}}rootfiles')
    rf = etree.SubElement(rootfiles, f'{{{CONTAINER_NS}}}rootfile')
    rf.set('full-path', 'OEBPS/content.opf')
    rf.set('media-type', 'application/oebps-package+xml')
    return etree.tostring(container, method='xml', encoding='utf-8', xml_declaration=True)


def _resolve_stylesheet(odd_css: str, project_css: str | None) -> str:
    """Cascade the EPUB stylesheet: packaged baseline, ODD rules, project rules.

    Later parts win, so a project stylesheet can restyle anything the ODD's own
    (web-oriented) CSS brings along.
    """
    parts: list[str] = []
    base_path = packaged_epub_css()
    if base_path is not None and base_path.is_file():
        parts.append(base_path.read_text(encoding='utf-8').rstrip())
    if odd_css.strip():
        parts.append(odd_css.rstrip())
    if project_css and project_css.strip():
        parts.append(project_css.rstrip())
    return '\n\n'.join(parts) + ('\n' if parts else '')


def _resolve_internal_links(docs: dict[str, etree._Element]) -> None:
    """Point ``href="#id"`` at the chapter file that actually holds *id*.

    Cross-references survive chunking only if the fragment is qualified with its
    target document; within the same file the bare fragment is left alone.
    """
    # Synthetic ids restart per chapter, so the same value can occur in several
    # files. Only unambiguous ids can be resolved across documents.
    home: dict[str, str | None] = {}
    for file_id, doc in docs.items():
        for el in doc.iter():
            el_id = el.get('id')
            if not el_id:
                continue
            if el_id in home and home[el_id] != file_id:
                home[el_id] = None
            else:
                home.setdefault(el_id, file_id)

    for file_id, doc in docs.items():
        for a in doc.iter(f'{{{XHTML_NS}}}a'):
            href = a.get('href') or ''
            if not href.startswith('#'):
                continue
            target = home.get(href[1:])
            if target is not None and target != file_id:
                a.set('href', f'{target}.xhtml{href}')


def build_epub(
    mod: ModuleType,
    root: etree._Element,
    *,
    chunking: ChunkingConfig | None = None,
    odd_css: str = '',
    project_css: str | None = None,
    input_path: Path | None = None,
    transform_opts: dict[str, Any] | None = None,
    skip_title: bool = False,
    fonts: Sequence[Path] = (),
    cover_image: str | None = None,
    metadata: EpubMetadata | None = None,
    xpath_env: Any = None,
) -> bytes:
    """Transform *root* with an EPUB-mode module and return ``.epub`` bytes."""
    meta = metadata or extract_epub_metadata(root)
    chapter_els = select_epub_chapters(root, chunking)
    chapters = _build_chapter_list(chapter_els)
    opts = dict(transform_opts or {})
    if input_path is not None:
        opts.setdefault('input_path', str(input_path))

    xhtml_docs: dict[str, etree._Element] = {}

    if not skip_title:
        header = _find_header(root)
        if header is not None:
            body_nodes = _transform_fragment(mod, header, opts, xpath_env)
            title_div = etree.Element(f'{{{XHTML_NS}}}div')
            title_div.set('id', 'title')
            for n in body_nodes:
                title_div.append(n)
            xhtml_docs['title'] = assemble_xhtml('Title page', meta.language, [title_div])
        else:
            # Minimal title page from metadata
            p = etree.Element(f'{{{XHTML_NS}}}p')
            p.text = meta.title
            xhtml_docs['title'] = assemble_xhtml('Title page', meta.language, [p])

    for ch in chapters:
        body_nodes = _transform_fragment(mod, ch.element, opts, xpath_env)
        # Ensure chapter root anchor exists for TOC links.
        if body_nodes and not any(
            (n.get('id') == ch.anchor_id) for n in body_nodes if isinstance(n, etree._Element)
        ):
            if body_nodes[0].get('id') is None:
                body_nodes[0].set('id', ch.anchor_id)
            else:
                wrap = etree.Element(f'{{{XHTML_NS}}}div')
                wrap.set('id', ch.anchor_id)
                for n in body_nodes:
                    wrap.append(n)
                body_nodes = [wrap]
        ch.title = (
            _rendered_heading_text(body_nodes)
            or ch.title
            or _milestone_label(ch.element)
            or 'Untitled'
        )
        xhtml_docs[ch.file_id] = assemble_xhtml(ch.title, meta.language, body_nodes)

    _resolve_internal_links(xhtml_docs)

    all_docs = list(xhtml_docs.values())
    referenced = _collect_img_srcs(*all_docs)
    if cover_image and cover_image not in referenced:
        referenced = list(referenced) + [cover_image]
    base_dir = input_path.parent if input_path is not None else None
    images = _resolve_image_sources(referenced, base_dir)
    image_hrefs = list(images)

    font_names = [p.name for p in fonts if p.is_file()]
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    stylesheet = _resolve_stylesheet(odd_css, project_css)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        # EPUB requires uncompressed mimetype as the first entry.
        zf.writestr(
            'mimetype',
            'application/epub+zip',
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr('META-INF/container.xml', _container_xml())
        zf.writestr(
            'OEBPS/content.opf',
            _build_opf(
                meta,
                chapters,
                skip_title=skip_title,
                image_hrefs=image_hrefs,
                font_names=font_names,
                cover_image=cover_image,
                modified=modified,
            ),
        )
        zf.writestr('OEBPS/nav.xhtml', _build_nav(meta, chapters, skip_title=skip_title))
        zf.writestr('OEBPS/toc.ncx', _build_ncx(meta, chapters, skip_title=skip_title))
        zf.writestr('OEBPS/stylesheet.css', stylesheet.encode('utf-8'))
        for file_id, doc in xhtml_docs.items():
            zf.writestr(f'OEBPS/{file_id}.xhtml', _serialize_xhtml(doc))

        for href, src in images.items():
            zf.write(src, f'OEBPS/{href}')

        for font_path in fonts:
            if font_path.is_file():
                zf.write(font_path, f'OEBPS/Fonts/{font_path.name}')

    return buf.getvalue()
