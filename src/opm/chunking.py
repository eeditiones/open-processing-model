# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Document chunking

Splits large TEI documents into smaller HTML pages with metadata and fragments
for static site generation.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Collection
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from lxml import etree
from lxml import html as lxml_html

from opm.config import ChunkingConfig, FragmentConfig, ProjectConfig
from opm.epub import _resolve_image_sources
from opm.runtime import source_map
from opm.runtime.context import RunState
from opm.runtime.xpath_env import XPathEnvironment
from opm.transform import (
    load_transform_module,
    project_xpath_env,
    run_transform,
    xpath_select,
)
from opm.template_rendering import (
    DEFAULT_INDEX_TEMPLATE_NAME,
    render_index_template,
    resolve_template_path,
    _inner_html,
)
from opm.runtime.pm_runtime import serialize as _default_serialize, inject_cached_footnotes
from opm.runtime.output_functions import XML_ID

# ``pb-link`` carries its cross-reference in a pb-view attribute rather than an
# href; the first one set wins when resolving the target.
PB_LINK_TARGET_ATTRS = ('xml-id', 'node-id', 'hash')
# pb-view wiring that means nothing once the element is a plain anchor.
PB_LINK_DROP_ATTRS = PB_LINK_TARGET_ATTRS + ('emit', 'subscribe', 'browse')


@dataclass
class ChunkMetadata:
    id: str
    file: str
    xpath: str
    prev: str | None = None
    next: str | None = None
    #: The chunk root's own ``xml:id``, when it has one. The anchor index maps
    #: every id in a chunk to its file, which cannot say which one *is* the
    #: chunk — the distinction a consumer needs to key a page on the entry it
    #: renders (a register person, a numbered letter). ``None`` when the chunk
    #: root carries no id.
    xml_id: str | None = None


@dataclass
class ChunkResult:
    metadata: ChunkMetadata
    content_html: str
    head_html: str
    fragments: dict[str, str]


@dataclass
class ManifestData:
    chunks: list[ChunkMetadata]
    fragments: dict[str, str]
    anchors: dict[str, str]


class ChunkProcessor:
    """Splits one document into chunks and writes them in one output format.

    Most callers want [`opm.project.Project.chunk`][opm.project.Project.chunk] or
    [`chunk_document`][opm.chunking.chunk_document], which build one of these. Use it directly to
    select chunks ([`select_chunks`][opm.chunking.ChunkProcessor.select_chunks]) or read their metadata without
    writing anything.

    Args:
        module_path: The compiled transform module for chunk content.
        xml_root: Root element of the parsed document.
        config: The ``[chunking]`` settings, with fragment modules compiled.
        project_root: The directory ``config.output_dir`` is relative to.
        project_config: The project settings (parameters, template context).
        webcomponents: Enable web-component mode.
        xpath_env: The XPath environment to evaluate in; see
            [`opm.transform.project_xpath_env`][opm.transform.project_xpath_env].
        source_dir: Directory of the source file, for copying images.
        documents: Names of every document in the run, for the templates.
        document: Name of this document's source file.
    """

    def __init__(
        self,
        module_path: Path,
        xml_root: etree._Element,
        config: ChunkingConfig,
        project_root: Path,
        project_config: ProjectConfig | None = None,
        webcomponents: bool = False,
        xpath_env: XPathEnvironment | None = None,
        source_dir: Path | None = None,
        documents: Collection[str] | None = None,
        document: str | None = None,
    ):
        self.module = load_transform_module(module_path)
        # The source file's name (`serafin01.xml`), handed to the page template
        # as `document`.
        self.document: str | None = document or config.link_doc or None
        # Names of every document in the run, handed to the page template as
        # `documents` so it can link only to pages that exist. One set is
        # shared by all documents of a directory run.
        self.documents: frozenset[str] = (
            frozenset(documents) if documents is not None
            else frozenset(filter(None, [self.document]))
        )
        self._fragment_modules: dict[str, Any] = {}
        if config.fragments:
            for frag in config.fragments:
                if frag.module:
                    key = str(frag.module)
                    if key not in self._fragment_modules:
                        self._fragment_modules[key] = load_transform_module(frag.module)
        self.xml_root = xml_root
        self.config = config
        self.project_root = project_root
        self.output_dir = project_root / config.output_dir
        self.webcomponents = webcomponents
        cfg = project_config or ProjectConfig()
        # Chunk pages are HTML, so the web overlay applies. Includes the derived
        # webcomponents_url when web-component mode is on.
        self.template_context: dict[str, Any] = cfg.context_for(
            'web', webcomponents=webcomponents,
        )
        self.parameters: dict[str, str] = dict(cfg.parameters)
        self.source_dir = source_dir
        self._copied_images: set[str] = set()
        # One environment for the whole document: the selector, every chunk
        # and every fragment share its cached node trees. Without one, the
        # project's variables and extensions apply but no registers load.
        self.xpath_env = xpath_env if xpath_env is not None else XPathEnvironment(
            variables=dict(cfg.xpath_variables),
            namespaces=dict(cfg.xpath_namespaces),
            extensions=cfg.xpath_extensions,
        )
        # Includes the project's base override ([transform] css), compiled in.
        # Design CSS is not part of this — it travels through chunking.assets.
        self.odd_css: str = getattr(self.module, 'ODD_GENERATED_CSS', '') or ''
        self.chunks: list[etree._Element] = []
        self.results: list[ChunkResult] = []
        self._jinja_env: Any | None = None
        self._jinja_template: Any | None = None
        # Built once per document; each chunk derives a run of its own from it.
        self._base_context: Any | None = None
        self._id_index: dict[str, etree._Element] | None = None
        self._chunk_anchor_map: dict[str, str] = {}
        self._shared_urls: dict[str, Any] = {
            'odd_css_url': '',
            'assets': '',
            'asset_styles': [],
        }

    @property
    def odd_name(self) -> str:
        """ODD name to advertise to ``pb-view``.

        Read from the ``ODD_NAME`` baked into the generated module, i.e. the ODD
        it was actually compiled from, so the index and CSS reference the right
        ODD. pb-view sends ``odd=<name>.odd`` and loads ``css/<name>.css``.
        """
        return getattr(self.module, 'ODD_NAME', '')

    def _source_node(self, node: etree._Element) -> etree._Element:
        """Original document node that *node* was copied from, else *node*.

        tei-publisher-lib binds this as ``$parameters?root``. Intro copies from
        [`opm.navigation.dbk_section_chunks`][opm.navigation.dbk_section_chunks] keep the source ``xml:id``.
        """
        if node.getroottree().getroot() is self.xml_root:
            return node
        xml_id = node.get(XML_ID)
        if not xml_id:
            return self.xml_root
        if self._id_index is None:
            # Built once: scanning the document per chunk was quadratic.
            self._id_index = {}
            for el in self.xml_root.iter():
                el_id = el.get(XML_ID) if isinstance(el.tag, str) else None
                if el_id:
                    self._id_index.setdefault(el_id, el)
        return self._id_index.get(xml_id, self.xml_root)

    def select_chunks(self) -> list[etree._Element]:
        """Find chunk elements.

        If ``config.selector`` is set to a dotted Python path it is imported
        and called as ``selector(root, config)``.  Otherwise the ``xpath``
        expression from the chunking config is evaluated.

        Selectors that rebuild a region as a detached tree record copy → source
        in `opm.runtime.source_map` while they build, which is what lets
        ``$get()`` in an ODD step back to the stored document. The map holds
        both trees alive, so it is reset here — once per document, before the
        selector runs.
        """
        source_map.clear()
        source_map.set_base_uri(self.xpath_env.base_uri)
        if self.config.selector:
            import importlib
            module_name, _, func_name = self.config.selector.rpartition('.')
            selector_fn = getattr(importlib.import_module(module_name), func_name)
            chunks = selector_fn(self.xml_root, self.config)
        else:
            # Use xpath_select (XPath 3.1) so unprefixed names resolve against the
            # document's default namespace — TEI's div/body live in the TEI
            # namespace, which raw lxml xpath() with a prefix-only nsmap silently
            # misses. Matches how process_fragment() selects nodes.
            chunks = xpath_select(
                self.xml_root,
                self.config.xpath or '//text/body/div',
                xpath_env=self.xpath_env,
            )

        if not isinstance(chunks, list):
            chunks = [chunks] if chunks else []

        # Filter to only elements
        self.chunks = [
            chunk for chunk in chunks
            if isinstance(chunk, etree._Element)
        ]
        return self.chunks

    def shared_root(self) -> Path:
        """Return the directory holding output shared across documents.

        Each document gets its own subdirectory, so stylesheets and assets
        belong one level up, beside the collection index — one copy for the
        whole edition. Without ``link_doc`` the output directory is itself the
        root.
        """
        return self.output_dir.parent if self.config.link_doc else self.output_dir

    def url_prefix(self) -> str:
        """Return the relative path from a chunk page back to [`shared_root`][opm.chunking.ChunkProcessor.shared_root]."""
        return '../' if self.config.link_doc else ''

    def write_shared_files(self) -> dict[str, str]:
        """Write stylesheets and copy assets into [`shared_root`][opm.chunking.ChunkProcessor.shared_root].

        Chunking always produces several pages sharing one stylesheet, so the
        stylesheets are always written as files — the same thing
        ``--format pb-view`` has always done. Templates receive
        ``odd_css_url`` pointing at it, alongside the ``odd_css`` string, which
        stays available so a template that inlines it keeps working. Stylesheets
        among ``config.assets`` are listed in ``asset_styles``, in declared
        order. ``index_url`` points back at the collection index written at
        [`shared_root`][opm.chunking.ChunkProcessor.shared_root] (see ``build_index``) — empty when the caller sets
        no ``link_doc``, as there is then no such page to link to.

        Safe to call once per document — the writes are idempotent.
        """
        root = self.shared_root()
        prefix = self.url_prefix()
        urls: dict[str, Any] = {
            'odd_css_url': '', 'assets': '', 'asset_styles': [],
            'index_url': f'{prefix}index.html' if self.config.link_doc else '',
        }

        if self.odd_css:
            css_dir = root / 'css'
            css_dir.mkdir(parents=True, exist_ok=True)
            (css_dir / f'{self.odd_name}.css').write_text(self.odd_css, encoding='utf-8')
            urls['odd_css_url'] = f'{prefix}css/{self.odd_name}.css'

        if self.config.assets:
            assets_dir = root / 'assets'
            assets_dir.mkdir(parents=True, exist_ok=True)
            sources = resolve_assets(self.project_root, self.config.assets)
            for source in sources:
                target = assets_dir / source.name
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, target)
            urls['assets'] = f'{prefix}assets'
            # Stylesheets among the assets, in the order they were declared —
            # that is the cascade order, so a template can link them blind.
            urls['asset_styles'] = [
                f'{prefix}assets/{source.name}'
                for source in sources
                if source.suffix.lower() == '.css'
            ]

        return urls

    def copy_referenced_images(self, html: str) -> None:
        """Copy the local images *html* references into `output_dir`.

        An ``img/@src`` is written relative to the source document, and the
        chunk pages sit flat in the output directory, so each image goes to the
        same relative path there.  Files are looked up the way EPUB output does:
        next to the source document, then in a sibling ``images/`` directory.
        Remote and root-relative URLs are left alone, as are paths that would
        land outside the output directory and images that cannot be found.
        """
        if self.source_dir is None or not html or '<img' not in html:
            return
        try:
            root = lxml_html.fromstring(f'<div>{html}</div>')
        except (etree.ParserError, ValueError):
            return
        out_root = self.output_dir.resolve()
        for img in root.iter('img'):
            src = img.get('src') or ''
            parts = urlsplit(src)
            if not parts.path or parts.scheme or parts.netloc or src.startswith('/'):
                continue
            href = unquote(parts.path)
            if href in self._copied_images:
                continue
            self._copied_images.add(href)
            source = _resolve_image_sources([href], self.source_dir).get(href)
            if source is None:
                continue
            target = (self.output_dir / href).resolve()
            if not target.is_relative_to(out_root) or target == source.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def entry_file(self) -> str:
        """Return the filename of this document's first chunk (its entry point)."""
        return f'{1:03d}.html'

    def entry_href(self) -> str:
        """Return the link to this document's entry point, relative to the output root.

        ``config.link_doc`` names the per-document subdirectory, giving
        ``quickstart.xml/001.html``; without it there is no prefix.
        """
        doc = (self.config.link_doc or '').strip('/')
        entry = self.entry_file()
        return f'{doc}/{entry}' if doc else entry

    def _expand_document_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fill in per-document parameter values for fragment processing.

        Global fragments otherwise receive the same static parameters for every
        document in a directory run, but browse/index models need to know which
        document they are describing. Two things happen here:

        * ``doc`` defaults to [`entry_href`][opm.chunking.ChunkProcessor.entry_href] when not set explicitly. The
          ``display='browse'`` models in the stock ODDs build their link as
          ``<param name="uri" value="$parameters?doc"/>``, so declaring the
          fragment is enough to get a working href.
        * Placeholders in string values are expanded by ``_expand_placeholders``.
          This is how an absolute or TEI-Publisher-style scheme is configured,
          e.g. ``parameters = { display = "browse", doc = "/exist/apps/x/{doc}/{stem}" }``.
        """
        expanded = self._expand_placeholders(params)
        expanded.setdefault('doc', self.entry_href())
        return expanded

    def _expand_placeholders(self, params: dict[str, Any]) -> dict[str, Any]:
        """Expand ``{…}`` placeholders in string parameter values.

        ``{doc}``, ``{doc_stem}``, ``{file}`` and ``{stem}`` carry the same
        vocabulary as [`ChunkingConfig.link_pattern`][opm.config.ChunkingConfig.link_pattern].
        ``{prefix}`` is the path from a chunk page back to the output root,
        where the shared ``css/`` and ``assets/`` live. ``opm chunk`` writes
        every page into a per-document subdirectory, so it expands to ``../``;
        it is empty only for a caller driving this class with no ``link_doc``.
        A parameter holding a URL into ``assets/`` should use it rather than
        hard-coding the hop: ``context-path = "{prefix}assets"``.

        Values with unknown placeholders are passed through untouched, so
        parameters that legitimately contain braces are unaffected.
        """
        doc = (self.config.link_doc or '').strip('/')
        entry = self.entry_file()
        expanded: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str) and '{' in value:
                try:
                    value = value.format(
                        doc=doc,
                        doc_stem=Path(doc).stem,
                        file=entry,
                        stem=Path(entry).stem,
                        prefix=self.url_prefix(),
                    )
                except (KeyError, IndexError, ValueError):
                    pass
            expanded[key] = value
        return expanded

    def generate_chunk_metadata(self, chunk: etree._Element, index: int) -> ChunkMetadata:
        """Generate metadata for a chunk."""
        chunk_id = f"chunk-{index + 1:03d}"
        chunk_file = f"{index + 1:03d}.html"
        
        # Determine prev/next as filename stems (e.g. "002") so templates can
        # link them directly as {{ chunk.prev }}.html.
        prev_id = f"{index:03d}" if index > 0 else None
        next_id = f"{index + 2:03d}" if index < len(self.chunks) - 1 else None
        
        return ChunkMetadata(
            id=chunk_id,
            file=chunk_file,
            xpath=(self.config.xpath + f"[{index + 1}]") if self.config.xpath else '',
            prev=prev_id,
            next=next_id,
            xml_id=chunk.get(XML_ID) or chunk.get('id'),
        )

    def build_anchor_index(self) -> dict[str, str]:
        """Map source ``xml:id`` (or plain ``@id``) values to the chunk file that owns them.

        JATS and other no-namespace vocabularies identify elements with ``@id``,
        so both are indexed; ``xml:id`` wins where an element carries both.
        """
        xml_ns = {'xml': 'http://www.w3.org/XML/1998/namespace'}
        anchor_map: dict[str, str] = {}

        for index, chunk in enumerate(self.chunks):
            chunk_file = self.generate_chunk_metadata(chunk, index).file
            source_nodes = chunk.xpath(
                './/*[@xml:id or @id] | self::*[@xml:id or @id]', namespaces=xml_ns,
            )
            for node in source_nodes:
                if not isinstance(node, etree._Element):
                    continue
                xml_id = node.get(XML_ID) or node.get('id')
                if xml_id and xml_id not in anchor_map:
                    anchor_map[xml_id] = chunk_file

        self._chunk_anchor_map = anchor_map
        return anchor_map

    def _rewrite_same_document_target(
        self,
        target: str | None,
        *,
        current_file: str | None = None,
    ) -> str | None:
        """Rewrite ``#id`` links to the owning chunk file when needed.

        When ``config.link_pattern`` is set the cross-chunk URL is built by
        substituting ``{file}``, ``{stem}``, ``{anchor}``, ``{doc}`` and
        ``{doc_stem}`` into the pattern.
        Otherwise the default relative form ``{file}#{anchor}`` is used.
        """
        if not target or not target.startswith('#') or target == '#':
            return target

        anchor = target[1:]
        target_file = self._chunk_anchor_map.get(anchor)
        if target_file is None:
            return target
        if current_file is not None and target_file == current_file:
            return f'#{anchor}'

        pattern = self.config.link_pattern
        if pattern:
            stem = Path(target_file).stem
            doc = (self.config.link_doc or '').strip('/')
            url = pattern.format(
                file=target_file,
                stem=stem,
                anchor=anchor,
                doc=doc,
                doc_stem=Path(doc).stem,
            )
            # Drop empty {doc} path segments without touching "http://" / "https://".
            if not doc:
                if '://' in url:
                    scheme, sep, rest = url.partition('://')
                    url = scheme + sep + rest.replace('//', '/')
                else:
                    while '//' in url:
                        url = url.replace('//', '/')
            return url
        return f'{target_file}#{anchor}'

    def _rewrite_html_fragment(
        self,
        html: str,
        *,
        current_file: str | None = None,
    ) -> str:
        """Rewrite same-document links inside an HTML fragment string."""
        if not html:
            return html
        has_targets = '#' in html and bool(self._chunk_anchor_map)
        if not has_targets and 'pb-link' not in html:
            return html

        parser = etree.HTMLParser(encoding='utf-8')
        wrapped = etree.fromstring(f'<div>{html}</div>'.encode('utf-8'), parser=parser)
        body = wrapped.find('body')
        wrapper = body.find('div') if body is not None else None
        if wrapper is None:
            return html

        changed = False
        for attr_name in ('href', 'data-target'):
            for element in wrapper.xpath(f'.//*[@{attr_name}]'):
                if not isinstance(element, etree._Element):
                    continue
                original = element.get(attr_name)
                rewritten = self._rewrite_same_document_target(original, current_file=current_file)
                if rewritten is not None and rewritten != original:
                    element.set(attr_name, rewritten)
                    changed = True

        if self._resolve_pb_links(wrapper, current_file=current_file):
            changed = True

        return _inner_html(wrapper) if changed else html

    def _resolve_pb_links(
        self,
        wrapper: etree._Element,
        *,
        current_file: str | None = None,
    ) -> bool:
        """Turn ``pb-link`` custom elements into real anchors.

        Chunk pages are plain HTML with no ``pb-view`` to listen on the channel
        a ``pb-link`` emits on, so a TOC built from them is unclickable. The
        target sits in ``xml-id``/``node-id`` instead of an href, so resolve it
        through the anchor index exactly as a ``#id`` href is resolved. The
        stock templates pair every ``pb-link`` selector with an ``a`` one, so
        the rewritten element keeps its styling.

        A ``pb-link`` with no resolvable target (the ``path``-based browse form,
        which points at another document) is left untouched.
        """
        changed = False
        for element in wrapper.xpath('.//pb-link'):
            if not isinstance(element, etree._Element):
                continue
            href = element.get('href')
            if not href:
                target = next(
                    (element.get(attr) for attr in PB_LINK_TARGET_ATTRS if element.get(attr)),
                    None,
                )
                if not target:
                    continue
                href = self._rewrite_same_document_target(
                    target if target.startswith('#') else f'#{target}',
                    current_file=current_file,
                )
            if not href:
                continue
            element.tag = 'a'
            element.set('href', href)
            for attr in PB_LINK_DROP_ATTRS:
                element.attrib.pop(attr, None)
            changed = True
        return changed

    def _rewrite_fragments(
        self,
        fragments: dict[str, str],
        *,
        current_file: str | None = None,
    ) -> dict[str, str]:
        """Rewrite same-document links in a fragment mapping."""
        return {
            name: self._rewrite_html_fragment(content, current_file=current_file)
            for name, content in fragments.items()
        }

    def process_fragment(
        self,
        fragment: FragmentConfig,
        context_node: etree._Element | None = None,
        _cache: dict[tuple, str] | None = None,
        chunk_index: int | None = None,
    ) -> str:
        """Process a fragment transform.

        The xpath is evaluated with the chunk as context node, so a
        chunk-relative expression (``../../text[@type='translation']/div``)
        picks that chunk's counterpart. An absolute expression that yields one
        element per chunk (``//body/div[@xml:lang='en']``) is instead aligned by
        position — the parallel-column case — using *chunk_index*. Both formats
        pass the index, so ``--format pb-view`` and the HTML output resolve
        fragments identically.
        """
        if fragment.scope == 'global':
            context = self.xml_root
        else:
            context = context_node if context_node is not None else self.xml_root

        # Project-wide parameters provide defaults; fragment params override them.
        params = {**self.parameters, **(fragment.parameters or {})}
        params = self._expand_document_params(params)
        view_root = (
            self.xml_root if fragment.scope == 'global' else self._source_node(context)
        )
        env = self.xpath_env.with_root(view_root).with_parameters(params)

        fragment_content = xpath_select(context, fragment.xpath, xpath_env=env)

        if not fragment_content:
            return ""

        if isinstance(fragment_content, list) and len(fragment_content) == 1:
            fragment_content = fragment_content[0]
        elif (
            isinstance(fragment_content, list)
            and chunk_index is not None
            and len(fragment_content) == len(self.chunks)
            and chunk_index < len(fragment_content)
        ):
            # Parallel columns: one fragment element per chunk, aligned by position.
            fragment_content = fragment_content[chunk_index]

        if isinstance(fragment_content, etree._Element):
            mod = (
                self._fragment_modules[str(fragment.module)]
                if fragment.module
                else self.module
            )
            params_key = frozenset(
                (k, v) for k, v in params.items() if isinstance(v, str)
            )
            if _cache is not None and mod is self.module:
                cache_key = (id(fragment_content), params_key, id(view_root))
                if cache_key in _cache:
                    return _cache[cache_key]
            result = run_transform(
                mod,
                fragment_content,
                parameters=params,
                # Fragments must use the same output mode as the chunk body.
                # Without it an `alternate` model degrades to the non-component
                # form, which inlines the alternate content in a <span> — and
                # register entries are block markup (<h1>, <p>, <ul>), so the
                # HTML parser closes the enclosing <p> and the entry spills into
                # the running text instead of staying a popover.
                webcomponents=self.webcomponents,
                apply_template=False,
                xpath_env=env,
            )
            if _cache is not None and mod is self.module:
                _cache[(id(fragment_content), params_key, id(view_root))] = result
            return result
        elif isinstance(fragment_content, str):
            return fragment_content
        else:
            return str(fragment_content)

    def _chunk_options(self) -> dict[str, Any]:
        """The ``transform()`` options every chunk runs with.

        Placeholders are expanded first, so a parameter pointing into
        ``assets/`` (``context-path = "{prefix}assets"``) resolves from the
        depth the chunk pages are actually written at.
        """
        options: dict[str, Any] = self._expand_placeholders(self.parameters)
        if self.webcomponents:
            options['webcomponents'] = True
        return options

    def _run_chunk_transform(self, chunk: etree._Element) -> list:
        """Apply the transform to *chunk* as a run of its own.

        The module's context is built once per document. Each chunk derives a
        view of it with fresh run state (footnotes, counters) and a fresh
        output-functions instance, and binds its source node as
        ``$parameters?root``; the XPath environment's cached document trees are
        shared by all of them.
        """
        view_root = self._source_node(chunk)
        if self._base_context is None:
            self._base_context = self.module.new_context(
                self.xml_root, self._chunk_options(), xpath_env=self.xpath_env,
            )
        base = self._base_context
        ctx = base.derive(
            root=chunk,
            pmf=type(base.pmf)(),
            state=RunState(),
            xpath=base.xpath.with_root(view_root),
        )
        result = self.module.apply(ctx, [chunk])
        result = ctx.pmf.finish(ctx, result)
        return inject_cached_footnotes(result, ctx)

    def _render_chunk_html(self, chunk: etree._Element) -> tuple[str, str]:
        """Transform *chunk* and return ``(content_html, head_html)``.

        Works with the raw lxml result (avoids serialize → HTMLParser re-parse)
        and reuses the shared config dict.  No link rewriting is applied.
        """
        raw_result = self._run_chunk_transform(chunk)

        serialize = getattr(self.module, 'serialize', _default_serialize)

        # Check whether the transform produced a full HTML document (<html> root).
        html_el = next(
            (item for item in raw_result
             if isinstance(item, etree._Element) and etree.QName(item).localname == 'html'),
            None,
        )
        if html_el is not None:
            # Full document: extract head/body directly without serializing first.
            return _inner_html(html_el.find('body')), _inner_html(html_el.find('head'))
        # Fragment: one serialization, no re-parse.
        return serialize(raw_result), ''

    def process_chunk(self, chunk: etree._Element, index: int) -> ChunkResult:
        """Process a single chunk with its fragments."""
        metadata = self.generate_chunk_metadata(chunk, index)

        content_html, head_html = self._render_chunk_html(chunk)

        content_html = self._rewrite_html_fragment(content_html, current_file=metadata.file)
        head_html = self._rewrite_html_fragment(head_html, current_file=metadata.file)

        # Per-chunk fragment transforms share a cache so identical
        # (element, params) combinations are not re-transformed.
        _cache: dict[tuple, str] = {(id(chunk), frozenset()): content_html}

        fragments: dict[str, str] = {}
        if self.config.fragments:
            for fragment in self.config.fragments:
                if fragment.scope == 'per-chunk':
                    fragments[fragment.name] = self._rewrite_html_fragment(
                        self.process_fragment(fragment, chunk, _cache, index),
                        current_file=metadata.file,
                    )

        return ChunkResult(
            metadata=metadata,
            content_html=content_html,
            head_html=head_html,
            fragments=fragments,
        )

    def process_global_fragments(self) -> dict[str, str]:
        """Process global fragments once."""
        fragments: dict[str, str] = {}
        if self.config.fragments:
            for fragment in self.config.fragments:
                if fragment.scope == 'global':
                    fragments[fragment.name] = self.process_fragment(fragment)
        return fragments

    def render_chunk_template(
        self, 
        chunk_result: ChunkResult, 
        global_fragments: dict[str, str],
        template_path: Path | None = None
    ) -> str:
        """Render a chunk with its template context."""
        # Use chunk-specific template or fallback to main template
        if self.config.template:
            chunk_template = resolve_template_path(self.project_root / self.config.template)
        elif template_path:
            chunk_template = template_path
        else:
            # Create a minimal template for chunks
            chunk_template = None
        
        if chunk_template:
            # content_html and head_html are pre-extracted in process_chunk() —
            # no HTMLParser round-trip needed here.
            content_html = chunk_result.content_html
            head_html = chunk_result.head_html

            # Build Jinja2 env + template once; reuse across all chunks
            if self._jinja_template is None or self._jinja_env is None:
                from jinja2 import Environment, FileSystemLoader
                self._jinja_env = Environment(
                    loader=FileSystemLoader(str(chunk_template.parent)),
                    autoescape=False,
                )
                try:
                    with chunk_template.open('r', encoding='utf-8') as f:
                        template_content = f.read()
                    self._jinja_template = self._jinja_env.from_string(template_content)
                except Exception as e:
                    raise FileNotFoundError(f'Template not found: {chunk_template}') from e
            assert self._jinja_template is not None
            tpl = self._jinja_template

            all_fragments = {**global_fragments, **chunk_result.fragments}
            
            # Ensure all strings are properly encoded UTF-8
            if isinstance(content_html, bytes):
                content_html = content_html.decode('utf-8')
            if isinstance(head_html, bytes):
                head_html = head_html.decode('utf-8')
            
            # Ensure fragment content is properly encoded
            for key, value in all_fragments.items():
                if isinstance(value, bytes):
                    all_fragments[key] = value.decode('utf-8')
            
            rendered = tpl.render(
                head_html=head_html,
                content_html=content_html,
                odd_css=self.odd_css,
                # Expanded the same way the transform sees them, so a template
                # and XPath never disagree about a parameter's value.
                parameters=self._expand_placeholders(self.parameters),
                lang="",
                context=self.template_context,
                # Add chunk-specific context
                fragments=all_fragments,
                chunk=chunk_result.metadata,
                document=self.document,
                documents=self.documents,
                # Stylesheet URLs, plus an assets prefix when configured.
                # The inline strings above stay available either way.
                **self._shared_urls,
            )
            
            return rendered
        else:
            # Return raw chunk HTML
            return chunk_result.content_html

    def generate_manifest(self, global_fragments: dict[str, str]) -> ManifestData:
        """Generate JSON manifest for static site builders."""
        chunks_metadata = [result.metadata for result in self.results]
        return ManifestData(
            chunks=chunks_metadata,
            fragments=global_fragments,
            anchors=self._chunk_anchor_map,
        )

    def _chunk_file_stem(self, chunk_result: ChunkResult) -> str:
        """Return the filename stem (without extension) for a chunk."""
        return Path(chunk_result.metadata.file).stem

    def process_all(
        self,
        template_path: Path | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        output_format: str = 'html',
    ) -> None:
        """Process all chunks and save files.

        Args:
            template_path: Optional Jinja2 template path (ignored for ``output_format='json'``).
            on_progress: Optional callback ``(current, total)`` called after each chunk is written.
            output_format: ``'html'`` (default) or ``'json'``.  JSON mode writes one
                ``<stem>.json`` per chunk containing all fields as a JSON object, and
                writes global fragments into the manifest rather than separate files.
        """
        use_json = output_format == 'json'

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Stylesheets and assets live in the shared root, written once for the
        # whole edition; the returned URLs go into every template context.
        self._shared_urls = self.write_shared_files()

        # Select chunks
        self.select_chunks()
        self.build_anchor_index()
        
        # Process global fragments once
        global_fragments = self.process_global_fragments()
        standalone_global_fragments = self._rewrite_fragments(global_fragments)
        
        if not use_json:
            # Save global fragment files as standalone HTML
            for name, content in standalone_global_fragments.items():
                fragment_file = self.output_dir / f"{name}.html"
                fragment_file.write_text(content, encoding='utf-8')
        
        total = len(self.chunks)
        # Process each chunk
        for index, chunk in enumerate(self.chunks):
            chunk_result = self.process_chunk(chunk, index)
            self.results.append(chunk_result)

            if use_json:
                stem = self._chunk_file_stem(chunk_result)
                embedded_global_fragments = self._rewrite_fragments(
                    global_fragments,
                    current_file=chunk_result.metadata.file,
                )
                chunk_data: dict = {
                    **asdict(chunk_result.metadata),
                    'content': chunk_result.content_html,
                    'head': chunk_result.head_html,
                    'odd_css': self.odd_css,
                    'fragments': {**embedded_global_fragments, **chunk_result.fragments},
                    **self._shared_urls,
                }
                chunk_file = self.output_dir / f"{stem}.json"
                chunk_file.write_text(
                    json.dumps(chunk_data, indent=2, ensure_ascii=False),
                    encoding='utf-8',
                )
            else:
                embedded_global_fragments = self._rewrite_fragments(
                    global_fragments,
                    current_file=chunk_result.metadata.file,
                )
                rendered_html = self.render_chunk_template(
                    chunk_result,
                    embedded_global_fragments,
                    template_path,
                )
                chunk_file = self.output_dir / chunk_result.metadata.file
                chunk_file.write_text(rendered_html, encoding='utf-8')
                self.copy_referenced_images(chunk_result.content_html)
            
            if on_progress is not None:
                on_progress(index + 1, total)
        
        # Generate and save manifest
        manifest = self.generate_manifest(standalone_global_fragments)
        manifest_file = self.output_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
            encoding='utf-8'
        )

    def _pb_view_base_params(self) -> dict[str, str]:
        """Build the constant part of the pb-view lookup key.

        Mirrors the parameters ``pb-view`` includes in its static key
        (``odd``, ``view``, ``xpath``, ``map`` and ``user.*``) — see
        ``_staticUrl()`` in ``pb-view.js``.
        """
        params: dict[str, str] = {
            'odd': f'{self.odd_name}.odd',
            'view': self.config.view,
        }
        if self.config.map:
            params['map'] = self.config.map
        for name, value in (self.config.parameters or {}).items():
            params[f'user.{name}'] = str(value)
        return params

    def _pb_view_fragment_params(self, fragment: FragmentConfig) -> dict[str, str]:
        """Base pb-view params plus this fragment's ``user.*`` overrides."""
        params = self._pb_view_base_params()
        for name, value in (fragment.parameters or {}).items():
            params[f'user.{name}'] = str(value)
        return params

    @staticmethod
    def _is_chunk_context_xpath(xpath: str) -> bool:
        """True when *xpath* means "the current chunk" (not a document-wide select).

        Used for per-chunk fragments such as breadcrumbs (``xpath="."``): the
        expression is evaluated against each chunk, matching
        [`process_fragment`][opm.chunking.ChunkProcessor.process_fragment], rather than pre-selected once from the
        document root (which would yield a single node and skip later chunks).
        """
        return xpath.strip() in ('.', './', 'self::node()', 'self::*')

    def _pb_view_part_nav(
        self, index: int, chunk_ids: list[str], xml_id: str
    ) -> dict[str, Any]:
        """Build navigation fields mirroring TEI Publisher's ``/api/parts/.../json``.

        ``id`` / ``nextId`` / ``previousId`` carry xml:ids (or synthetic ids).
        ``root`` is always ``None``: ``pb-view`` assigns ``nodeId = resp.root``,
        and a subscribed *dynamic* view would then call the parts API with
        ``root=<xml:id>``, which expects an eXist node id and fails with
        ``NumberFormatException``.

        ``next`` / ``previous`` stay populated (same values as the ``*Id``
        fields) so ``pb-view.navigate()`` sees a truthy next/previous; when
        ``*Id`` is set it loads by ``id`` and does not send ``root``.
        ``rootNode`` repeats the chunk id as a stable stand-in (no eXist
        node ids offline).
        """
        total = len(chunk_ids)
        nav: dict[str, Any] = {
            'id': xml_id,
            'root': None,
            'rootNode': xml_id,
        }
        if index > 0:
            nav['previous'] = chunk_ids[index - 1]
            nav['previousId'] = chunk_ids[index - 1]
        if index < total - 1:
            nav['next'] = chunk_ids[index + 1]
            nav['nextId'] = chunk_ids[index + 1]
        return nav

    def _register_fragment_index_keys(
        self,
        index: dict[str, str],
        frag: FragmentConfig,
        filename: str,
        ids: set[str],
        xml_id: str,
        *,
        first_chunk: bool,
    ) -> None:
        """Register pb-view lookup keys for a fragment part file.

        Chunk-context xpaths (``.``) are transform context only — the
        consuming ``pb-view`` typically has no ``xpath`` attribute — so those
        keys omit ``xpath``. Absolute fragment xpaths (parallel columns) keep
        ``xpath`` in the key, matching ``pb-view`` when it sends one.
        """
        frag_params = self._pb_view_fragment_params(frag)
        frag_key_xpath = frag.xpath_dynamic or frag.xpath
        if frag.xpath_dynamic is None and self._is_chunk_context_xpath(frag.xpath):
            key_variants: list[dict[str, str]] = [frag_params]
        else:
            with_xpath = {**frag_params, 'xpath': frag_key_xpath}
            key_variants = [with_xpath]

        for base in key_variants:
            if first_chunk:
                index[_compute_part_key(base)] = filename
            for node_id in ids:
                index[_compute_part_key({**base, 'id': node_id})] = filename
            index[_compute_part_key({**base, 'root': xml_id})] = filename

    def export_pb_view(
        self,
        doc_path: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Export chunks as data consumable by the ``pb-view`` web component.

        Lays the output out the way ``pb-view`` resolves it in static mode, where
        the data location is derived from the ``static`` root and the document
        ``path`` (``${static}/${path}/...``):

        - ``<output_dir>/<doc_path>/index.json`` — lookup table mapping pb-view's
          computed parameter keys to part files
        - ``<output_dir>/<doc_path>/<xml:id>.json`` — one part per chunk, mirroring
          the response of TEI Publisher's ``/api/parts/<doc>/json`` endpoint
        - ``<output_dir>/<doc_path>/<name>.json`` — one part per global fragment
          (e.g. ``toc.json``), keyed by the fragment xpath and ``user.*`` params;
          a sibling ``<name>.html`` carries the same content as well-formed XML,
          for consumers that store it in an XML database (see
          `_wellformed_fragment_xml`)
        - ``<output_dir>/<doc_path>/<name>-<xml:id>.json`` — per-chunk fragments
        - ``<output_dir>/css/<odd>.css`` — stylesheet, shared by every document
          under the same static root

        ``doc_path`` should match the ``path`` of the consuming ``pb-document``.
        When omitted the data is written directly into ``<output_dir>`` (single
        document at the static root).

        Chunks carrying an ``xml:id`` are addressed by it; chunks without one get
        a stable synthetic id. ``pb-view`` navigates via ``nextId``/``previousId``
        (xml:ids) when present; ``next``/``previous`` are kept truthy for
        ``navigate()`` but ``root`` is left null so subscribed dynamic views do
        not call the parts API with ``root=<xml:id>``.

        ``on_progress`` is an optional callback ``(current, total)`` invoked after
        each chunk is written.
        """
        xml_ns = {'xml': 'http://www.w3.org/XML/1998/namespace'}

        # Data lives under the document path; CSS is shared at the static root.
        data_dir = self.output_dir / doc_path if doc_path else self.output_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.select_chunks()
        if not self.chunks:
            raise ValueError('pb-view export: no chunks selected.')

        # Resolve each chunk's identifier up front so we can wire prev/next links.
        # Chunks with an xml:id are addressed by it; chunks without one get a
        # stable synthetic id so they can still be paged through by pb-view via
        # nextId/previousId (and index keys for id=/root=).
        existing_ids = {
            e.get(XML_ID)
            for e in self.xml_root.xpath('//*[@xml:id]', namespaces=xml_ns)
            if isinstance(e, etree._Element) and e.get(XML_ID)
        }
        chunk_ids: list[str] = []
        synthetic_counter = 0
        for chunk in self.chunks:
            xml_id = chunk.get(XML_ID)
            if not xml_id:
                synthetic_counter += 1
                xml_id = f'_chunk{synthetic_counter}'
                while xml_id in existing_ids:
                    synthetic_counter += 1
                    xml_id = f'_chunk{synthetic_counter}'
                existing_ids.add(xml_id)
            chunk_ids.append(xml_id)

        base_params = self._pb_view_base_params()
        index: dict[str, str] = {}
        total = len(self.chunks)

        # Global fragments once: {name}.json (+ sibling {name}.html), keyed by
        # xpath + fragment user params. Also register under every chunk id/root
        # so a subscribed pb-view that re-fetches on navigation still resolves
        # to the same file. Links stay as in-document anchors (same as main
        # chunk content) so pb-view client navigation can resolve them.
        global_frags = [f for f in (self.config.fragments or []) if f.scope == 'global']
        for frag in global_frags:
            frag_html = self.process_fragment(frag)
            if isinstance(frag_html, bytes):
                frag_html = frag_html.decode('utf-8')

            frag_filename = f'{frag.name}.json'
            (data_dir / frag_filename).write_text(
                json.dumps({'content': frag_html}, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
            # The JSON keeps the HTML verbatim — pb-view injects it as HTML —
            # while the .html sibling is written as well-formed XML, since that
            # is the copy that gets uploaded into an XML database.
            (data_dir / f'{frag.name}.html').write_text(
                _wellformed_fragment_xml(frag_html, frag.name),
                encoding='utf-8',
            )

            frag_params = self._pb_view_fragment_params(frag)
            frag_key_xpath = frag.xpath_dynamic or frag.xpath
            index[_compute_part_key({**frag_params, 'xpath': frag_key_xpath})] = frag_filename
            for xml_id in chunk_ids:
                index[_compute_part_key({**frag_params, 'id': xml_id, 'xpath': frag_key_xpath})] = (
                    frag_filename
                )
                index[_compute_part_key({**frag_params, 'root': xml_id, 'xpath': frag_key_xpath})] = (
                    frag_filename
                )

        per_chunk_frags = [f for f in (self.config.fragments or []) if f.scope == 'per-chunk']
        # Shared by process_fragment across chunks, as in process_chunk: identical
        # (node, params) pairs are transformed once.
        frag_cache: dict[tuple, str] = {}

        for i, (chunk, xml_id) in enumerate(zip(self.chunks, chunk_ids)):
            content_html, _ = self._render_chunk_html(chunk)
            response: dict[str, Any] = {
                'content': content_html,
                **self._pb_view_part_nav(i, chunk_ids, xml_id),
            }

            filename = f'{xml_id}.json'
            (data_dir / filename).write_text(
                json.dumps(response, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )

            # The first chunk answers the initial load, where pb-view sends
            # neither id nor root; also register the configured xpath as-is.
            if i == 0:
                index[_compute_part_key(base_params)] = filename
                # pb-view looks itself up by its own ``xpath`` attribute, which
                # names the region it displays — not the expression that selected
                # the chunk roots. ``xpath_dynamic`` supplies the former.
                key_xpath = self.config.xpath_dynamic or self.config.xpath
                if key_xpath:
                    index[_compute_part_key({**base_params, 'xpath': key_xpath})] = filename

            # Register every xml:id contained in the chunk so navigation by id
            # (gotoId, prev/next) and by root resolves to this file.
            ids = {xml_id}
            for node in chunk.xpath('.//*[@xml:id]', namespaces=xml_ns):
                if isinstance(node, etree._Element):
                    node_id = node.get(XML_ID)
                    if node_id:
                        ids.add(node_id)
            for node_id in ids:
                index[_compute_part_key({**base_params, 'id': node_id})] = filename
            index[_compute_part_key({**base_params, 'root': xml_id})] = filename

            # Per-chunk fragment files: {name}-{xml_id}.json
            # Rendered through process_fragment, exactly as the HTML format does,
            # so both evaluate the fragment xpath with the chunk as context node
            # and share one set of runtime options (collections, variables,
            # namespaces, web-component mode).
            for frag in per_chunk_frags:
                frag_html = self.process_fragment(frag, chunk, frag_cache, i)
                if not frag_html:
                    continue

                frag_response: dict[str, Any] = {
                    'content': frag_html,
                    **self._pb_view_part_nav(i, chunk_ids, xml_id),
                }

                frag_filename = f'{frag.name}-{xml_id}.json'
                (data_dir / frag_filename).write_text(
                    json.dumps(frag_response, indent=2, ensure_ascii=False),
                    encoding='utf-8',
                )

                self._register_fragment_index_keys(
                    index,
                    frag,
                    frag_filename,
                    ids,
                    xml_id,
                    first_chunk=(i == 0),
                )

            if on_progress is not None:
                on_progress(i + 1, total)

        (data_dir / 'index.json').write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

        # pb-view loads its stylesheet from <static>/css/<odd>.css, i.e. shared
        # at the static root across all documents.
        odd_css = getattr(self.module, 'ODD_GENERATED_CSS', '')
        css_dir = self.output_dir / 'css'
        css_dir.mkdir(parents=True, exist_ok=True)
        (css_dir / f'{self.odd_name}.css').write_text(odd_css, encoding='utf-8')


#: HTML elements that carry no end tag; ``<br/>`` is well-formed XML *and* valid
#: HTML5, so these are the only ones that may be serialised self-closed.
_VOID_HTML_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
})


def _explicit_end_tags(root: etree._Element) -> None:
    """Force an end tag on every empty non-void element.

    The XML serialiser writes ``<span class="x"/>`` for an empty element, which
    an HTML parser reads as an *unclosed* ``<span>`` — the rest of the fragment
    would then nest inside it. Giving the element an empty text node makes lxml
    emit ``<span class="x"></span>``, which both parsers agree on.
    """
    for el in root.iter():
        if not isinstance(el.tag, str):  # comments, PIs
            continue
        if len(el) == 0 and not el.text and el.tag.lower() not in _VOID_HTML_ELEMENTS:
            el.text = ''


def _wellformed_fragment_xml(html: str, name: str) -> str:
    """Return *html* as a well-formed XML fragment with a single root element.

    ``<name>.html`` is written for consumers that store the fragment as XML —
    eXist-db maps ``.html`` to an XML resource, so anything it cannot parse is
    rejected on upload. Two things in the HTML serialisation stop it parsing:
    void elements are written open (``<br>``, ``<img …>``), and a model may emit
    several sibling elements, as ``display='browse'`` does with title, author and
    abstract — leaving the fragment without a single root.

    A fragment that already has exactly one root element keeps it, so existing
    output does not gain a wrapper it never had; anything else (several roots,
    bare text alongside an element, or nothing at all) is wrapped in
    ``<div class="fragment fragment-<name>">``.
    """
    items = lxml_html.fragments_fromstring(html or '')
    # Leading text is returned as a bare string; only non-whitespace text has to
    # survive into the output, so whitespace between elements can be dropped.
    elements = [i for i in items if not isinstance(i, str)]
    stray_text = any(isinstance(i, str) and i.strip() for i in items)
    single_root = len(elements) == 1 and not stray_text and not (elements[0].tail or '').strip()

    if single_root:
        root = elements[0]
        root.tail = None
    else:
        root = lxml_html.Element('div')
        root.set('class', f'fragment fragment-{name}')
        for i in items:
            if isinstance(i, str):
                if i.strip():
                    _append_text(root, i)
            else:
                root.append(i)

    _explicit_end_tags(root)
    return etree.tostring(root, encoding='unicode', method='xml', with_tail=False)


def _append_text(parent: etree._Element, text: str) -> None:
    """Append *text* to *parent*'s content, after any children it already has."""
    if len(parent) == 0:
        parent.text = (parent.text or '') + text
    else:
        last = parent[-1]
        last.tail = (last.tail or '') + text


def _compute_part_key(params: dict[str, str]) -> str:
    """Build a pb-view lookup key from *params*.

    Matches ``createKey()`` in ``pb-view.js``: sort the parameter names and join
    ``name=value`` pairs with ``&``.
    """
    return '&'.join(f'{key}={params[key]}' for key in sorted(params))


def chunk_document(
    module_path: Path | None,
    xml_path: Path,
    config: ChunkingConfig,
    project_root: Path,
    template_path: Path | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    project_config: ProjectConfig | None = None,
    webcomponents: bool = False,
    xpath_extensions: tuple[str, ...] | None = None,
    output_format: str = 'html',
    doc_path: str | None = None,
    documents: Collection[str] | None = None,
) -> None:
    """Chunk a document using the specified configuration.

    The page template gets *xml_path*'s name as ``document``. *documents*
    names every document of the run (``serafin01.xml``, …) and reaches the
    template as ``documents``; pass the same set for each document of a
    directory run. It defaults to just *xml_path*.

    ODDs in *config* (the main one and the fragments') that have no compiled
    module yet are compiled here. [`opm.project.Project.chunk`][opm.project.Project.chunk] handles
    a whole directory the way ``opm chunk`` does.
    """
    from dataclasses import replace

    from opm.config import resolve_base_css
    from opm.odd_cache import ensure_compiled_module

    # Same base override the CLI applies, so calling this directly as a
    # library gives the same stylesheet as `opm chunk`.
    base_css = resolve_base_css((project_config or ProjectConfig()).document_css, project_root)
    resolved_module = module_path or config.module
    if resolved_module is None and config.odd is not None:
        resolved_module, _ = ensure_compiled_module(
            config.odd, output_mode='web', base_css=base_css,
        )
    if config.fragments and any(f.odd and f.module is None for f in config.fragments):
        config = replace(config, fragments=[
            replace(
                fragment,
                module=ensure_compiled_module(
                    fragment.odd, output_mode=fragment.mode, base_css=base_css,
                )[0],
            ) if fragment.odd and fragment.module is None else fragment
            for fragment in config.fragments
        ])
    if resolved_module is None:
        raise ValueError(
            'No transform module specified. Pass a module path, set chunking.odd '
            'in your config, or use the packaged teipublisher ODD.',
        )

    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    cfg = project_config or ProjectConfig()

    processor = ChunkProcessor(
        resolved_module, root, config, project_root,
        project_config=project_config,
        webcomponents=webcomponents,
        xpath_env=project_xpath_env(cfg, xml_path, extensions=xpath_extensions),
        source_dir=xml_path.parent,
        documents=documents if documents is not None else (xml_path.name,),
        document=xml_path.name,
    )
    if output_format == 'pb-view':
        processor.export_pb_view(doc_path=doc_path, on_progress=on_progress)
    else:
        processor.process_all(template_path, on_progress=on_progress, output_format=output_format)


@dataclass
class IndexEntry:
    """One document in a generated collection index."""

    name: str
    """Output subdirectory, e.g. ``quickstart.xml``."""
    stem: str
    """Source filename without its suffix, e.g. ``quickstart``."""
    label: str
    """Readable fallback heading derived from *stem* — used when no ODD title exists."""
    href: str
    """Link to the document's first chunk, relative to the index."""
    chunks: int
    """Number of chunks the document was split into."""
    fragments: dict[str, str]
    """Global fragments from the document's manifest (``browse``, ``title``, …)."""


def _humanise(stem: str) -> str:
    """Turn a filename stem into a readable fallback label."""
    text = stem.replace('_', ' ').replace('-', ' ').strip()
    return text[:1].upper() + text[1:] if text else stem


def resolve_assets(root: Path, assets: tuple[Path, ...]) -> list[Path]:
    """Expand ``[chunking] assets`` entries to the paths to copy.

    An entry holding ``*``, ``?`` or ``[`` is matched against the filesystem, so
    ``iiif/*`` copies every document's directory in one line instead of naming
    each one — and keeps working when a document is added. Matches are sorted,
    which fixes the cascade order of any stylesheets among them. Every other
    entry is taken literally.

    A literal path that does not exist, or a pattern matching nothing, raises
    ``FileNotFoundError``. The alternative is output quietly missing a file a
    template or model expects, which surfaces much later as a 404.
    """
    resolved: list[Path] = []
    for asset in assets:
        source = asset if asset.is_absolute() else root / asset
        text = str(source)
        if any(char in text for char in '*?['):
            pattern = str(source.relative_to(source.anchor))
            matches = sorted(Path(source.anchor).glob(pattern))
            if not matches:
                raise FileNotFoundError(f'Asset pattern matched nothing: {source}')
            resolved.extend(matches)
        elif source.exists():
            resolved.append(source)
        else:
            raise FileNotFoundError(f'Asset not found: {source}')
    return resolved


def collect_index_entries(output_dir: Path) -> list[IndexEntry]:
    """Collect one [`IndexEntry`][opm.chunking.IndexEntry] per chunked document under *output_dir*.

    Reads the ``manifest.json`` each document run writes, so this works on any
    existing output directory without re-chunking. Directories without a
    readable manifest are skipped.
    """
    entries: list[IndexEntry] = []
    for manifest_file in sorted(output_dir.glob('*/manifest.json')):
        try:
            data = json.loads(manifest_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue

        doc_dir = manifest_file.parent
        chunks = data.get('chunks') or []
        first = chunks[0].get('file') if chunks else None
        stem = Path(doc_dir.name).stem
        entries.append(
            IndexEntry(
                name=doc_dir.name,
                stem=stem,
                label=_humanise(stem),
                href=f'{doc_dir.name}/{first}' if first else doc_dir.name,
                chunks=len(chunks),
                fragments=data.get('fragments') or {},
            )
        )
    return entries


def build_index(
    output_dir: Path,
    *,
    template_path: Path | None = None,
    title: str | None = None,
    odd_css: str | None = None,
    module_path: Path | None = None,
    project_config: ProjectConfig | None = None,
    project_root: Path | None = None,
    chunking_config: ChunkingConfig | None = None,
    webcomponents: bool = False,
) -> Path | None:
    """Render ``<output_dir>/index.html`` listing every chunked document.

    ``http.server`` serves ``index.html`` in preference to a directory listing,
    so writing this file is all that is needed for ``opm serve`` to show a real
    landing page.

    *project_config* also supplies the template ``context``, so the index and
    the chunk pages read the same ``[context]`` values. Pass *webcomponents* to
    match the run's effective mode, so the index page is given
    ``webcomponents_url`` exactly when the chunk pages are.

    Pass *module_path* (and optionally *project_config*) to have the ODD's
    generated CSS and the project stylesheet resolved the same way chunk pages
    resolve them, so an index template can style a browse record's ``tei-*``
    classes exactly as the document pages do. An explicit *odd_css* wins.

    Returns the path written, or *None* when *output_dir* holds no chunked
    documents.
    """
    entries = collect_index_entries(output_dir)
    if not entries:
        return None

    if odd_css is None and module_path is not None:
        odd_css = getattr(load_transform_module(module_path), 'ODD_GENERATED_CSS', '')

    # The index sits at the output root that chunking wrote css/ and assets/
    # into, so its URLs need no prefix.
    chunk_cfg = chunking_config or ChunkingConfig()
    odd_name = getattr(load_transform_module(module_path), 'ODD_NAME', '') if module_path else ''
    odd_css_url = f'css/{odd_name}.css' if odd_css and odd_name else ''
    asset_styles = [
        f'assets/{source.name}'
        for source in resolve_assets(project_root or output_dir, chunk_cfg.assets)
        if source.suffix.lower() == '.css'
    ]

    rendered = render_index_template(
        entries=entries,
        template_path=resolve_template_path(
            template_path, default_name=DEFAULT_INDEX_TEMPLATE_NAME
        ),
        title=title or output_dir.name,
        odd_css=odd_css,
        odd_css_url=odd_css_url,
        assets='assets' if chunk_cfg.assets else '',
        asset_styles=asset_styles,
        context=(project_config or ProjectConfig()).context_for(
            'web', webcomponents=webcomponents,
        ),
    )
    index_file = output_dir / 'index.html'
    index_file.write_text(rendered, encoding='utf-8')
    return index_file


def build_index_json(output_dir: Path, *, title: str | None = None) -> Path | None:
    """Write ``<output_dir>/index.json`` listing every chunked document.

    The JSON counterpart of [`build_index`][opm.chunking.build_index]. A directory run splits its
    documents into one subdirectory each, and nothing at the root says what they
    are or what order they belong in — a static site generator would have to
    rediscover that by scanning. This writes it once, from the same
    [`collect_index_entries`][opm.chunking.collect_index_entries] the HTML index is built from, so both agree.

    Returns the path written, or *None* when *output_dir* holds no chunked
    documents.
    """
    entries = collect_index_entries(output_dir)
    if not entries:
        return None

    index_file = output_dir / 'index.json'
    index_file.write_text(
        json.dumps(
            {
                'title': title or output_dir.name,
                'documents': [asdict(entry) for entry in entries],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    return index_file
