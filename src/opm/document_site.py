# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a static HTML documentation site from a compiled ODD / Guidelines document.

The site is two [`chunk_document`][opm.chunking.chunk_document] runs over
one prepared tree. The prepare step stamps ``xml:id`` values and adds the home
page and the catalog pages to the compiled tree, then
[`expand_document_tree`][opm.odd_expand.expand_document_tree] writes into it
everything the pages show that depends on the schema as a whole: the
relations of each spec, the A–Z lists, the table of contents, heading numbers
and link targets. ``tagdocs.odd`` then renders the text — every top-level
division — and the reference pages, one per spec, as the two runs in
``resources/document/opm.toml`` select them.
"""

from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path

from lxml import etree

from opm.chunking import chunk_document
from opm.config import ProjectConfig, load_project_config
from opm.odd_cache import ensure_compiled_module
from opm.odd_expand import CATALOGS, expand_document_tree
from opm.odd_schema import CompiledSchema, iter_guideline_chapters
from opm.resources import packaged_document_dir, packaged_odd
from opm.spec_index import (
    SPEC_TAGS,
    SpecIndex,
    iter_canonical_specs,
    localname,
    qn,
)
from opm.transform import load_transform_module

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
ProgressFn = Callable[[int, int, str], None]

_TAGDOCS_XPATH_EXTENSIONS = (
    'opm.runtime.common_xpath_functions',
    'opm.runtime.spec_xpath_functions',
)

_CATALOG_IDS = {xml_id for xml_id, _subtype, _heading in CATALOGS}


@dataclass
class DocumentSite:
    """Result of [`build_document_site`][opm.document_site.build_document_site]."""

    output_dir: Path
    index: SpecIndex
    pages: int
    chapters: int
    #: Expressions the documentation ODD uses that opm cannot evaluate, as the
    #: compiler recorded them in ``ODD_UNSUPPORTED``. They render as empty.
    unsupported: list[dict] = field(default_factory=list)


def build_document_site(
    compiled: CompiledSchema,
    output_dir: Path | str,
    *,
    lang: str = 'en',
    title: str | None = None,
    odd: Path | str | None = None,
    on_progress: ProgressFn | None = None,
    config_path: Path | str | None = None,
) -> DocumentSite:
    """Write a static HTML site for *compiled* into *output_dir*.

    *config_path* is the ``opm.toml`` to build with: a documentation project's
    (``opm init --example odd``), or by default the packaged one. It supplies
    the ODD, the chunking runs, the page template and the extension modules;
    the page assets and ``nav.xml`` come from the page template's directory.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config_file = Path(config_path) if config_path else packaged_document_dir() / 'opm.toml'
    base_cfg = load_project_config(config_file)
    site_dir = site_assets_dir(base_cfg, config_file)

    tree, index = _prepare(compiled, lang=lang, title=title, nav=site_dir / 'nav.xml')
    site_title = title or index.title
    if odd:
        odd_path = Path(odd)
    elif config_path and base_cfg.chunking and base_cfg.chunking.odd:
        odd_path = base_cfg.chunking.odd
    else:
        odd_path = packaged_odd('tagdocs')
    header_source = compiled.tree

    cfg = replace(
        base_cfg,
        template_context={
            **base_cfg.template_context,
            'site_title': site_title,
            'lang': lang,
            'edition': _edition_line(compiled.tree) or _edition_line(header_source),
            'rights': _rights_line(header_source) or _rights_line(compiled.tree),
        },
        parameters={**base_cfg.parameters, 'lng': lang, 'mode': 'ref'},
    )
    extensions = tuple(cfg.xpath_extensions) or _TAGDOCS_XPATH_EXTENSIONS
    runs = cfg.chunking_runs or ((cfg.chunking,) if cfg.chunking else ())
    if not runs:
        raise ValueError(f'{config_file} declares no [chunking] run')

    _copy_assets(output_dir, site_dir)

    chapters = [
        div for div in iter_guideline_chapters(tree)
        if div.get(XML_ID) not in _CATALOG_IDS
    ]
    specs = [
        spec for spec in index.all()
        if spec.kind in {'element', 'class', 'macro', 'datatype'}
    ]
    total = max(len(specs) + len(chapters) + 6, 1)
    written = 0

    def _on_chunk_progress(done: int, _run_total: int) -> None:
        # Several runs, one bar: each continues where the previous ended.
        if on_progress:
            on_progress(written + done, total, 'pages')

    with tempfile.TemporaryDirectory(prefix='opm-document-') as tmp:
        xml_path = Path(tmp) / 'schema.xml'
        xml_path.write_bytes(
            etree.tostring(tree, xml_declaration=True, encoding='utf-8'),
        )
        # In order, each run handed the anchors of those before it: the text
        # first, so a spec page's pointers into the prose resolve
        # (`#SATSRN` → SA.html#SATSRN).
        anchors: dict[str, str] = {}
        for position, run in enumerate(runs):
            chunking = replace(run, output_dir='.', odd=odd_path)
            anchors = chunk_document(
                module_path=None,
                xml_path=xml_path,
                config=chunking,
                project_root=output_dir,
                template_path=chunking.template,
                on_progress=_on_chunk_progress,
                project_config=cfg,
                xpath_extensions=extensions,
                anchors=anchors,
                merge_manifest=position > 0,
            )
            written = len(set(anchors.values()))

    _write_idents(index, output_dir)

    module_path, _fresh = ensure_compiled_module(odd_path, output_mode='web')
    mod = load_transform_module(module_path)
    unsupported = [
        entry for entry in getattr(mod, 'ODD_UNSUPPORTED', [])
        if entry.get('odd') == odd_path.name
    ]

    html_pages = list(output_dir.glob('*.html'))
    return DocumentSite(
        output_dir=output_dir,
        index=index,
        pages=len(html_pages),
        chapters=len(chapters),
        unsupported=unsupported,
    )


def prepare_document_tree(
    compiled: CompiledSchema,
    *,
    lang: str = 'en',
    title: str | None = None,
    nav: Path | None = None,
) -> etree._Element:
    """Deep-copy *compiled*, add the nodes ``opm chunk`` needs as pages, and
    expand it for rendering.

    *nav* is the sidebar list to inject (``nav.xml``); the packaged one when
    omitted.

    Three passes. First the tree is normalized: appendix dumps our catalogs
    replace are dropped, the title page becomes a chapter, and every node that
    will be a page gets an ``xml:id`` — specs get ``ref-{ident}`` so
    ``file_pattern = "{xml_id}.html"`` yields the URLs tagdocs links to.

    Then the site's own pages are injected, because ``chunk`` selects chunks by
    XPath over this tree and names each file after an ``xml:id``: a page with
    no node cannot exist. Where each goes is what tells the runs and tagdocs
    what it is, so no page needs a mark of its own. Home sits directly under
    ``text``, outside front/body/back: it is no division of the text, which
    keeps it out of the numbering and the chapter sequence. The A–Z catalogs
    go to ``text/back``, where the appendices they replace stood, and are
    chapters like any other. The sidebar list goes to ``text/body``.

    Last, [`expand_document_tree`][opm.odd_expand.expand_document_tree] fills
    the pages in, so the tree holds everything they show.
    """
    return _prepare(compiled, lang=lang, title=title, nav=nav)[0]


def _prepare(
    compiled: CompiledSchema,
    *,
    lang: str,
    title: str | None,
    nav: Path | None,
) -> tuple[etree._Element, SpecIndex]:
    """[`prepare_document_tree`][opm.document_site.prepare_document_tree], and
    the index it expanded the tree from."""
    tree = deepcopy(compiled.tree)
    _drop_schema_catalog_chapters(tree)
    # Collected before the title page is wrapped into a chapter of its own,
    # which would move it out of the walk below.
    opening = _opening_nodes(tree)
    _ensure_title_chapter(tree)
    _ensure_spec_xml_ids(tree)
    _ensure_chapter_ids(tree)
    body = _ensure_body(tree)
    _inject_nav(body, nav)
    _inject_home(
        body.getparent(),
        title=title or compiled.title or 'ODD documentation',
        opening=opening,
    )
    _inject_catalogs(_ensure_back(tree))
    # Built before the expansion, so nothing it adds feeds back into the index.
    index = SpecIndex.from_tree(
        tree,
        lang=lang,
        title=title or compiled.title or 'ODD documentation',
    )
    expand_document_tree(tree, index, lang=lang)
    return tree, index


def _drop_schema_catalog_chapters(tree: etree._Element) -> None:
    """Remove Guidelines appendix dumps that our catalog pages already cover."""
    for div in list(iter_guideline_chapters(tree)):
        if div.get(XML_ID) not in _CATALOG_IDS:
            continue
        parent = div.getparent()
        if parent is not None:
            parent.remove(div)


def _ensure_title_chapter(tree: etree._Element) -> None:
    """Wrap ``front/titlePage`` so it becomes a chunked Title page."""
    title = _first_child(_text_part(tree, 'front'), 'titlePage')
    if title is None:
        return
    parent = title.getparent()
    if parent is None or (localname(parent) == 'div' and parent.get(XML_ID) == 'Title'):
        return
    wrap = etree.Element(qn('div'))
    wrap.set(XML_ID, 'Title')
    head = etree.SubElement(wrap, qn('head'))
    head.text = 'Title'
    parent.insert(list(parent).index(title), wrap)
    wrap.append(title)


def _first_child(parent: etree._Element | None, name: str) -> etree._Element | None:
    if parent is None:
        return None
    for child in parent:
        if localname(child) == name:
            return child
    return None


def _ensure_spec_xml_ids(tree: etree._Element) -> None:
    """Stamp ``xml:id="ref-{ident}"`` on one copy of each spec.

    A compiled schema repeats the same ``elementSpec`` in ``schemaSpec`` and in
    the body, p5all and a compiled ODD alike. Giving every copy the same id
    makes the serialized tree invalid (``ID ref-TEI already defined``). SpecIndex already
    keeps one node per ident (preferring ``@module``); match that here, and
    drop colliding ids on the extra copies so they are not chunked as pages.
    """
    chosen: dict[str, etree._Element] = {}
    extras: list[etree._Element] = []
    for el, _kind in iter_canonical_specs(tree):
        ident = el.get('ident')
        if not ident:
            continue
        previous = chosen.get(ident)
        if previous is None or (el.get('module') and not previous.get('module')):
            if previous is not None:
                extras.append(previous)
            chosen[ident] = el
        else:
            extras.append(el)
    wanted = {f'ref-{ident}' for ident in chosen}
    _free_spec_ids(tree, wanted)
    seen: set[str] = set()
    for ident, el in chosen.items():
        xml_id = f'ref-{ident}'
        el.set(XML_ID, xml_id)
        seen.add(xml_id)
    for el in extras:
        current = el.get(XML_ID)
        if current and current not in seen:
            seen.add(current)
            continue
        if XML_ID in el.attrib:
            del el.attrib[XML_ID]


_POINTER_ATTRS = ('target', 'corresp', 'sameAs', 'ref', 'source')


def _free_spec_ids(tree: etree._Element, wanted: set[str]) -> None:
    """Move non-spec elements off the ``ref-*`` ids the specs are about to take.

    The Guidelines give one figure ``xml:id="ref-faith"`` — exactly the id the
    ``faith`` elementSpec needs for its page. Two elements would then share an
    id and two chunks would claim ``ref-faith.html``. The spec wins, because
    tagdocs links to ``ref-{ident}.html`` everywhere, so the other element is
    renamed and any pointer to it rewritten to keep the cross-reference alive.
    """
    taken = {el.get(XML_ID) for el in tree.iter() if el.get(XML_ID)} | wanted
    for el in tree.iter():
        current = el.get(XML_ID)
        if not current or current not in wanted:
            continue
        if localname(el) in SPEC_TAGS:
            continue
        el.set(XML_ID, _unique_id(f'{current}-{localname(el)}', taken))
        _retarget(tree, current, el.get(XML_ID) or '')


def _retarget(tree: etree._Element, old: str, new: str) -> None:
    """Point every ``#old`` reference in *tree* at ``#new`` instead."""
    for el in tree.iter():
        for attr in _POINTER_ATTRS:
            value = el.get(attr)
            if not value or f'#{old}' not in value:
                continue
            el.set(attr, ' '.join(
                f'#{new}' if token == f'#{old}' else token
                for token in value.split()
            ))


def _ensure_chapter_ids(tree: etree._Element) -> None:
    """Give every published chapter and headed section an ``xml:id``.

    The id becomes the page's filename (``{xml_id}.html``) or its fragment
    anchor, so it is a published URL and should survive edits elsewhere in the
    document. Deriving it from the heading does that; a running counter would
    renumber every later page as soon as a chapter is inserted, removed, or
    starts carrying enough prose to be published.
    """
    taken = {el.get(XML_ID) for el in tree.iter() if el.get(XML_ID)}
    # Injected later, so not in the tree yet, but their ids are still spoken for.
    taken.update(_CATALOG_IDS)
    taken.add('index')
    for div in iter_guideline_chapters(tree):
        xmlid = div.get(XML_ID)
        if not xmlid:
            xmlid = _unique_id(_slug(_chapter_heading(div), 'chapter'), taken)
            div.set(XML_ID, xmlid)
        _ensure_nested_div_ids(div, prefix=xmlid, taken=taken)


_DASHES = re.compile(r'-{2,}')


def _slug(text: str, fallback: str) -> str:
    """*text* as a readable, NCName-safe id fragment.

    Accents are folded away (``Éléments`` → ``elements``) but letters outside
    Latin are kept, since ``xml:id`` allows them: transliterating to ASCII
    would flatten every heading in a Japanese or Greek document to the same
    fallback, which is the positional numbering this is here to avoid. An
    ``xml:id`` may not start with a digit, so "12 Numbers" takes the *fallback*
    as a prefix instead of being rejected.
    """
    folded = [
        ch for ch in unicodedata.normalize('NFKD', text.lower())
        if not unicodedata.combining(ch)
    ]
    slug = ''.join(ch if ch.isalnum() else '-' for ch in folded)
    slug = _DASHES.sub('-', slug).strip('-')[:60].strip('-')
    if not slug:
        return fallback
    return slug if slug[0].isalpha() else f'{fallback}-{slug}'


def _unique_id(base: str, taken: set[str]) -> str:
    """*base*, suffixed if the document already uses it. Records the result."""
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f'{base}-{n}'
        n += 1
    taken.add(candidate)
    return candidate


def _text_element(tree: etree._Element) -> etree._Element | None:
    text = tree.find(f'.//{{{TEI_NS}}}text')
    if text is None:
        text = next((el for el in tree.iter() if localname(el) == 'text'), None)
    return text


def _text_part(tree: etree._Element, name: str) -> etree._Element | None:
    text = _text_element(tree)
    if text is None:
        return None
    for child in text:
        if localname(child) == name:
            return child
    return None


def _ensure_body(tree: etree._Element) -> etree._Element:
    """``text/body``, created when the compiled tree has neither.

    Everything injected as a page goes here, so it has to exist even for a
    schema-only ODD that never had a ``text`` element of its own.
    """
    body = _text_part(tree, 'body')
    if body is not None:
        return body
    text = _text_element(tree)
    if text is None:
        text = etree.SubElement(tree, qn('text'))
    return etree.SubElement(text, qn('body'))


def _ensure_back(tree: etree._Element) -> etree._Element:
    """``text/back``, created after ``text/body`` when the ODD has none."""
    back = _text_part(tree, 'back')
    if back is not None:
        return back
    text = _text_element(tree)
    if text is None:
        text = etree.SubElement(tree, qn('text'))
    return etree.SubElement(text, qn('back'))


def _inject_nav(body: etree._Element, path: Path | None = None) -> None:
    if path is not None and path.is_file():
        data = path.read_bytes()
    else:
        data = resources.files('opm').joinpath('resources/document/nav.xml').read_bytes()
    body.insert(0, etree.fromstring(data))


_OPENING_TAGS = {'titlePage', 'p', 'opener', 'epigraph'}


def _inject_home(
    text: etree._Element,
    *,
    title: str,
    opening: list[etree._Element],
) -> None:
    """The home page, as the first child of ``text``.

    Not in front, body or back: the home page belongs to the site rather than
    to the text, and outside the three parts it is no chapter — tagdocs knows
    it by ``parent::text``, the numbering skips it and prev/next never lands
    on it, all without a mark.
    """
    home = etree.Element(qn('div'))
    home.set(XML_ID, 'index')
    head = etree.SubElement(home, qn('head'))
    head.text = title
    home.extend(opening)
    text.insert(0, home)


def _opening_nodes(tree: etree._Element) -> list[etree._Element]:
    """Copies of the title page and any prose that belongs to no chapter.

    Chapter ``div``s each become their own page, but a ``<p>`` sitting in
    ``body`` before the first chapter, or a ``titlePage`` in ``front``, has no
    chapter to be chunked with. The home page carries them instead.
    """
    text = _text_element(tree)
    if text is None:
        return []
    found: list[etree._Element] = []
    for part in text:
        name = localname(part)
        if name not in {'front', 'body'}:
            continue
        for child in part:
            tag = localname(child)
            if tag == 'div':
                # Front matter interleaves divs with loose prose; in the body
                # everything from the first chapter on belongs to a chapter.
                if name == 'body':
                    break
                continue
            if tag in _OPENING_TAGS:
                found.append(deepcopy(child))
    return found


def _inject_catalogs(back: etree._Element) -> None:
    """The A–Z catalog pages, as the first divs of ``text/back``.

    They stand in for the Guidelines' own reference appendices, which
    [`_drop_schema_catalog_chapters`][opm.document_site._drop_schema_catalog_chapters]
    removed, so they belong to the back matter and are numbered with it
    (Appendix A…). Document order is unchanged either way: back follows body.
    The lists come later, from the expansion.
    """
    for offset, (xml_id, subtype, heading) in enumerate(CATALOGS):
        div = etree.Element(qn('div'))
        div.set(XML_ID, xml_id)
        if subtype:
            div.set('subtype', subtype)
        head = etree.SubElement(div, qn('head'))
        head.text = heading
        back.insert(offset, div)


def _write_idents(index: SpecIndex, output_dir: Path) -> None:
    payload = [
        {'ident': s.ident, 'kind': s.kind, 'href': s.href}
        for s in index.all()
        if s.kind in {'element', 'class', 'macro', 'datatype'}
    ]
    (output_dir / 'idents.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


#: The page assets a site directory provides, copied into every build.
SITE_ASSETS = ('document.css', 'fonts.css', 'search.js', 'theme.js', 'tei-logo.svg')


def site_assets_dir(cfg: ProjectConfig, config_file: Path) -> Path:
    """Where the page assets and ``nav.xml`` live: beside the page template.

    The first run with a template decides; without one, the directory of
    *config_file*.
    """
    runs = cfg.chunking_runs or ((cfg.chunking,) if cfg.chunking else ())
    for run in runs:
        if run.template is not None:
            return Path(run.template).parent
    return config_file.parent


def _copy_assets(output_dir: Path, site_dir: Path | None = None) -> None:
    """The stylesheets, scripts, logo and fonts, from *site_dir* where it has
    them — a project's own — else the packaged ones."""
    packaged = resources.files('opm').joinpath('resources/document')

    def source(name: str):
        own = site_dir / name if site_dir is not None else None
        return own if own is not None and own.exists() else packaged.joinpath(name)

    for name in SITE_ASSETS:
        (output_dir / name).write_bytes(source(name).read_bytes())
    fonts_dir = output_dir / 'fonts'
    fonts_dir.mkdir(exist_ok=True)
    for entry in source('fonts').iterdir():
        if entry.name.endswith('.woff2'):
            (fonts_dir / entry.name).write_bytes(entry.read_bytes())


def _edition_line(root: etree._Element | None) -> str:
    """``editionStmt/edition`` condensed to "P5 Version 4.12.0 · 28th July 2026"."""
    edition = _header_element(root, 'edition')
    if edition is None:
        return ''
    text = _collapse(' '.join(edition.itertext()))
    if not text:
        return ''
    head = re.split(r'\.\s', text, maxsplit=1)[0].rstrip('.').strip()
    dates = [el for el in edition.iter() if localname(el) == 'date']
    when = _collapse(' '.join(dates[0].itertext())) if dates else ''
    if head and when:
        return f'{head} · {when}'
    return head or text


def _rights_line(root: etree._Element | None) -> str:
    licence = _header_element(root, 'licence')
    if licence is None:
        return ''
    text = _collapse(' '.join(licence.itertext()))
    return text if len(text) <= 160 else ''


def _header_element(root: etree._Element | None, name: str) -> etree._Element | None:
    if root is None:
        return None
    header = next((el for el in root.iter() if localname(el) == 'teiHeader'), None)
    if header is None:
        return None
    return next((el for el in header.iter() if localname(el) == name), None)


def _collapse(text: str) -> str:
    return re.sub(r'\s+([.,;:])', r'\1', re.sub(r'\s+', ' ', text)).strip()


def _ensure_nested_div_ids(
    div: etree._Element,
    *,
    prefix: str,
    taken: set[str],
) -> None:
    """Name each headed section under *div* after its own heading."""
    for el in div.iter():
        if el is div or localname(el) != 'div':
            continue
        if el.get(XML_ID):
            continue
        heading = _chapter_heading(el)
        if not heading:
            continue
        el.set(XML_ID, _unique_id(f'{prefix}-{_slug(heading, "s")}', taken))


def _chapter_heading(div: etree._Element) -> str:
    for child in div:
        if localname(child) == 'head':
            return ' '.join(child.itertext()).strip()
    return div.get(XML_ID) or ''
