# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a static HTML documentation site from a compiled ODD or Guidelines document.

[`prepare_document_tree`][opm.document_site.prepare_document_tree] turns the
compiled schema into a TEI tree that already holds every page (title page,
chapters, catalogs, reference entries) and the schema-wide content those pages show —
spec relations, A–Z lists, and so on, via
[`expand_document_tree`][opm.odd_expand.expand_document_tree].

[`build_document_site`][opm.document_site.build_document_site] then runs
[`chunk_document`][opm.chunking.chunk_document] three times over that tree, as
configured in ``resources/document/opm.toml``: Guidelines chapters, the home
page (the ``titlePage``), and one HTML page per spec. ``tagdocs.odd`` supplies the processing
models that render each chunk.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from lxml import etree

from opm.chunking import chunk_document
from opm.config import ProjectConfig, load_project_config
from opm.odd_cache import ensure_compiled_module
from opm.odd_expand import CATALOGS, expand_document_tree
from opm.odd_schema import (
    CompiledSchema,
    SchemaError,
    ensure_guideline_images,
    iter_guideline_chapters,
)
from opm.resources import packaged_document_dir, packaged_odd
from opm.spec_index import (
    SPEC_TAGS,
    SpecIndex,
    _inside_egxml,
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
    #: What the build could not do but did not stop for, e.g. missing figures.
    warnings: list[str] = field(default_factory=list)


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
            'site_name': site_title,
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

    assets = site_assets(site_dir, logo=cfg.template_context.get('logo'))

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
            # The page assets go into assets/ like any project's, unless the
            # run lists its own.
            chunking = replace(
                run, output_dir='.', odd=odd_path, assets=run.assets or assets,
            )
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
    figures, warnings = figure_files(compiled, tree)
    copy_figures(figures, output_dir)

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
        warnings=warnings,
    )


def prepare_document_tree(
    compiled: CompiledSchema,
    *,
    lang: str = 'en',
    title: str | None = None,
    nav: Path | None = None,
) -> etree._Element:
    """Return a deep copy of *compiled* ready for ``opm chunk`` / tagdocs.

    *nav* is the sidebar ``nav.xml`` to inject; the packaged copy is used when
    omitted.

    The preparation has three steps:

    1. **Normalize.** Drop Guidelines appendix dumps that our catalog pages
       replace and give every page node an ``xml:id``. Specs get
       ``ref-{ident}`` so ``file_pattern = "{xml_id}.html"`` matches the URLs
       tagdocs emits.

    2. **Inject site pages.** Chunking selects nodes by XPath, so every page
       needs a node in the tree. The home page is ``front/titlePage``, built
       from the ``teiHeader`` when the document has none. A–Z catalogs go into
       ``text/back`` as appendices. The sidebar list goes into ``text/body``.

    3. **Expand.** [`expand_document_tree`][opm.odd_expand.expand_document_tree]
       fills in relations, catalog lists, and the other content each page
       shows.
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
    _ensure_spec_xml_ids(tree)
    _ensure_chapter_ids(tree)
    body = _ensure_body(tree)
    _inject_nav(body, nav)
    _ensure_title_page(tree, title or compiled.title or 'ODD documentation')
    _inject_catalogs(_ensure_back(tree))
    # Built before the expansion, so nothing it adds feeds back into the index.
    index = SpecIndex.from_tree(
        tree,
        lang=lang,
        title=title or compiled.title or 'ODD documentation',
    )
    expand_document_tree(tree, index)
    return tree, index


def _drop_schema_catalog_chapters(tree: etree._Element) -> None:
    """Remove Guidelines appendix dumps that our catalog pages already cover."""
    for div in list(iter_guideline_chapters(tree)):
        if div.get(XML_ID) not in _CATALOG_IDS:
            continue
        parent = div.getparent()
        if parent is not None:
            parent.remove(div)


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

    Nav and chapter prose live here, so it has to exist even for a
    schema-only ODD that never had a ``text`` element of its own.
    """
    body = _text_part(tree, 'body')
    if body is not None:
        return body
    text = _text_element(tree)
    if text is None:
        text = etree.SubElement(tree, qn('text'))
    return etree.SubElement(text, qn('body'))


def _ensure_front(tree: etree._Element) -> etree._Element:
    """``text/front``, created before ``body`` when the ODD has none."""
    front = _text_part(tree, 'front')
    if front is not None:
        return front
    text = _text_element(tree)
    if text is None:
        text = etree.SubElement(tree, qn('text'))
    front = etree.Element(qn('front'))
    insert_at = len(text)
    for i, child in enumerate(text):
        if localname(child) in {'body', 'group', 'back'}:
            insert_at = i
            break
    text.insert(insert_at, front)
    return front


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


def _ensure_title_page(tree: etree._Element, title: str) -> None:
    """Make sure ``text/front`` opens with a ``titlePage``: it is the home page.

    A document without one gets a title page built from its ``teiHeader``,
    or from *title* alone when there is no header either.
    """
    front = _ensure_front(tree)
    if any(localname(child) == 'titlePage' for child in front):
        return
    page = etree.Element(qn('titlePage'))
    doc_title = etree.SubElement(page, qn('docTitle'))
    main = etree.SubElement(doc_title, qn('titlePart'), type='main')
    titles = _header_elements(tree, 'titleStmt', 'title')
    main.text = next(
        (_collapse(' '.join(t.itertext())) for t in titles if t.get('type') != 'sub'),
        '',
    ) or title
    for sub in (t for t in titles if t.get('type') == 'sub'):
        etree.SubElement(doc_title, qn('titlePart'), type='sub').text = _collapse(
            ' '.join(sub.itertext())
        )
    for author in _header_elements(tree, 'titleStmt', 'author'):
        etree.SubElement(page, qn('docAuthor')).text = _collapse(' '.join(author.itertext()))
    publishers = _header_elements(tree, 'publicationStmt', 'publisher')
    if publishers:
        imprint = etree.SubElement(page, qn('docImprint'))
        for publisher in publishers:
            etree.SubElement(imprint, qn('publisher')).text = _collapse(
                ' '.join(publisher.itertext())
            )
    dates = _header_elements(tree, 'publicationStmt', 'date')
    if dates:
        etree.SubElement(page, qn('docDate')).text = _collapse(' '.join(dates[0].itertext()))
    front.insert(0, page)


def _header_elements(tree: etree._Element, stmt: str, name: str) -> list[etree._Element]:
    """The non-empty *name* children of ``teiHeader/fileDesc/{stmt}``."""
    header = next((el for el in tree if localname(el) == 'teiHeader'), None)
    if header is None:
        return []
    found = []
    for parent in header.iter():
        if localname(parent) != stmt:
            continue
        found.extend(
            el for el in parent
            if localname(el) == name and ' '.join(el.itertext()).strip()
        )
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


#: The page assets a site directory provides, in cascade order for the two
#: stylesheets: the webfonts first, then the design that uses them.
SITE_ASSETS = ('fonts.css', 'document.css', 'fonts', 'search.js', 'theme.js', 'logo.svg')


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


def site_assets(site_dir: Path | None = None, logo: str | None = None) -> tuple[Path, ...]:
    """The stylesheets, scripts, fonts and logo every page links from assets/.

    Each is taken from *site_dir* where it has one — a project's own — else
    from the packaged ``resources/document``, so a project only keeps the
    files it changes. *logo* is ``context.logo``: a bare filename found in
    *site_dir* is added, since the page template resolves it under assets/.
    """
    packaged = Path(str(resources.files('opm').joinpath('resources/document')))

    def source(name: str) -> Path:
        own = site_dir / name if site_dir is not None else None
        return own if own is not None and own.exists() else packaged / name

    found = [source(name) for name in SITE_ASSETS]
    if (
        logo
        and site_dir is not None
        and logo not in SITE_ASSETS
        and '/' not in logo
        and not logo.startswith(('.', 'http'))
        and (site_dir / logo).is_file()
    ):
        found.append(site_dir / logo)
    return tuple(found)


def figure_urls(tree: etree._Element) -> list[str]:
    """The relative ``graphic/@url`` values *tree* shows, in document order.

    A graphic quoted in an example is markup being explained, not a figure;
    an absolute URL, or one climbing out of the output, is left as it is.
    """
    seen: dict[str, None] = {}
    for graphic in tree.iter(qn('graphic')):
        url = (graphic.get('url') or '').strip()
        if url and _is_local_url(url) and not _inside_egxml(graphic):
            seen.setdefault(url, None)
    return list(seen)


def _is_local_url(url: str) -> bool:
    if urlparse(url).scheme or url.startswith('/'):
        return False
    return '..' not in PurePosixPath(unquote(url)).parts


def figure_files(
    compiled: CompiledSchema, tree: etree._Element,
) -> tuple[dict[str, Path], list[str]]:
    """Map each figure *tree* shows to its file, and say which were not found.

    Figures resolve against the documented source, as they do in its own
    repository. For the TEI Guidelines that is the cached ``p5all.xml``, and
    their ``Images/`` are fetched beside it the first time a page needs one.
    """
    urls = figure_urls(tree)
    if not urls:
        return {}, []
    warnings: list[str] = []
    bases: list[Path] = []
    if compiled.source_path is not None:
        source = compiled.source_path
        bases.append(source if source.is_dir() else source.parent)

    def resolve() -> dict[str, Path]:
        found: dict[str, Path] = {}
        for url in urls:
            for base in bases:
                path = base / unquote(url)
                if path.is_file():
                    found[url] = path
                    break
        return found

    found = resolve()
    if len(found) < len(urls) and compiled.fetched_source is not None:
        try:
            bases.append(ensure_guideline_images())
        except SchemaError as exc:
            warnings.append(f'The TEI figures could not be fetched: {exc}')
        else:
            found = resolve()
    missing = [url for url in urls if url not in found]
    if missing:
        shown = ', '.join(missing[:5]) + (', …' if len(missing) > 5 else '')
        warnings.append(
            f'{len(missing)} figure{"s" if len(missing) != 1 else ""} not found, '
            f'shown as broken images: {shown}'
        )
    return found, warnings


def copy_figures(figures: dict[str, Path], dest: Path) -> None:
    """Copy *figures* under *dest*, each at the path its URL names."""
    for url, path in figures.items():
        target = dest / unquote(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


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
