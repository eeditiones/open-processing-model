"""Document chunking system for TEI Publisher.

Splits large TEI documents into smaller HTML pages with metadata and fragments
for static site generation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from lxml import etree

from opm.config import ChunkingConfig, FragmentConfig, ProjectConfig, DEFAULT_CDN_TEMPLATE, DEFAULT_VERSION
from opm.transform import (
    load_transform_module,
    load_xpath_collections,
    load_xpath_documents,
    run_transform,
    xpath_select,
)
from opm.runtime.pm_runtime import xpath_runtime_context
from opm.template_rendering import resolve_template_path, _inner_html
from opm.runtime.pm_runtime import serialize as _default_serialize, inject_cached_footnotes
from opm.runtime.output_functions import XML_ID, reset_counters


def _load_user_css(css_path: Path | None, project_root: Path) -> str:
    """Return stylesheet text from *css_path*, CWD default, or the packaged default.

    Mirrors ``opm.cli._resolve_user_css`` so chunk pages get the same defaults
    (alternate popovers, ``.tei-cb`` column breaks, …) as ``opm transform``.
    """
    from opm.resources import packaged_default_css

    if css_path is not None:
        path = css_path if css_path.is_absolute() else project_root / css_path
        if path.is_file():
            return path.read_text(encoding='utf-8')
        return ''

    local = project_root / 'styles' / 'default-styles.css'
    if local.is_file():
        return local.read_text(encoding='utf-8')

    packaged = packaged_default_css()
    if packaged is not None and packaged.is_file():
        return packaged.read_text(encoding='utf-8')
    return ''


@dataclass
class ChunkMetadata:
    id: str
    file: str
    xpath: str
    prev: str | None = None
    next: str | None = None


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
    def __init__(
        self,
        module_path: Path,
        xml_root: etree._Element,
        config: ChunkingConfig,
        project_root: Path,
        project_config: ProjectConfig | None = None,
        webcomponents: bool = False,
        xpath_extensions: tuple[str, ...] | None = None,
        xpath_base_uri: str | None = None,
        xpath_documents: dict[str, Any] | None = None,
        xpath_collections: dict[str, list] | None = None,
        xpath_variables: dict[str, Any] | None = None,
        xpath_namespaces: dict[str, str] | None = None,
    ):
        self.module = load_transform_module(module_path)
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
        if webcomponents:
            self.webcomponents_url: str | None = (
                cfg.webcomponents_cdn
                or DEFAULT_CDN_TEMPLATE.replace('{version}', DEFAULT_VERSION)
            )
        else:
            self.webcomponents_url = None
        self.xpath_extensions: tuple[str, ...] = (
            xpath_extensions if xpath_extensions is not None else cfg.xpath_extensions
        )
        self.parameters: dict[str, str] = dict(cfg.parameters)
        self.xpath_base_uri = xpath_base_uri
        self.xpath_documents = xpath_documents or {}
        self.xpath_collections = xpath_collections or {}
        self.xpath_variables = dict(
            xpath_variables if xpath_variables is not None else cfg.xpath_variables,
        )
        self.xpath_namespaces = dict(
            xpath_namespaces if xpath_namespaces is not None else cfg.xpath_namespaces,
        )
        self.odd_css: str = getattr(self.module, 'ODD_GENERATED_CSS', '') or ''
        self.user_css: str = _load_user_css(cfg.document_css, project_root)
        self.chunks: list[etree._Element] = []
        self.results: list[ChunkResult] = []
        self._jinja_env: Any | None = None
        self._jinja_template: Any | None = None
        # Built once; only config['footnotes'] is reset between chunks.
        self._transform_config: dict[str, Any] | None = None
        self._chunk_anchor_map: dict[str, str] = {}

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
        :func:`opm.navigation.dbk_section_chunks` keep the source ``xml:id``.
        """
        if node.getroottree().getroot() is self.xml_root:
            return node
        xml_id = node.get(XML_ID)
        if not xml_id:
            return self.xml_root
        for el in self.xml_root.iter():
            if isinstance(el, etree._Element) and el.get(XML_ID) == xml_id:
                return el
        return self.xml_root

    def select_chunks(self) -> list[etree._Element]:
        """Find chunk elements.

        If ``config.selector`` is set to a dotted Python path it is imported
        and called as ``selector(root, config)``.  Otherwise the ``xpath``
        expression from the chunking config is evaluated.
        """
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
                xpath_extensions=self.xpath_extensions or None,
                xpath_base_uri=self.xpath_base_uri,
                xpath_documents=self.xpath_documents,
                xpath_collections=self.xpath_collections,
                xpath_variables=self.xpath_variables,
                xpath_namespaces=self.xpath_namespaces,
            )

        if not isinstance(chunks, list):
            chunks = [chunks] if chunks else []

        # Filter to only elements
        self.chunks = [
            chunk for chunk in chunks
            if isinstance(chunk, etree._Element)
        ]
        return self.chunks

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
            next=next_id
        )

    def build_anchor_index(self) -> dict[str, str]:
        """Map source ``xml:id`` values to the chunk file that owns them."""
        xml_ns = {'xml': 'http://www.w3.org/XML/1998/namespace'}
        anchor_map: dict[str, str] = {}

        for index, chunk in enumerate(self.chunks):
            chunk_file = self.generate_chunk_metadata(chunk, index).file
            source_nodes = chunk.xpath('.//*[@xml:id] | self::*[@xml:id]', namespaces=xml_ns)
            for node in source_nodes:
                if not isinstance(node, etree._Element):
                    continue
                xml_id = node.get(XML_ID)
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
        substituting ``{file}``, ``{stem}``, and ``{anchor}`` into the pattern.
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
            url = pattern.format(file=target_file, stem=stem, anchor=anchor, doc=doc)
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
        if not html or '#' not in html or not self._chunk_anchor_map:
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

        return _inner_html(wrapper) if changed else html

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
        view_root = (
            self.xml_root if fragment.scope == 'global' else self._source_node(context)
        )
        params.update(
            xpath_runtime_context(
                base_uri=self.xpath_base_uri,
                documents=self.xpath_documents,
                collections=self.xpath_collections,
                variables=self.xpath_variables,
                namespaces=self.xpath_namespaces,
                root=view_root,
            ),
        )

        fragment_content = xpath_select(
            context,
            fragment.xpath,
            params=params,
            xpath_extensions=self.xpath_extensions or None,
            xpath_base_uri=self.xpath_base_uri,
            xpath_documents=self.xpath_documents,
            xpath_collections=self.xpath_collections,
            xpath_variables=self.xpath_variables,
                xpath_namespaces=self.xpath_namespaces,
        )

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
                xpath_extensions=self.xpath_extensions or None,
                # Fragments must use the same output mode as the chunk body.
                # Without it an `alternate` model degrades to the non-component
                # form, which inlines the alternate content in a <span> — and
                # register entries are block markup (<h1>, <p>, <ul>), so the
                # HTML parser closes the enclosing <p> and the entry spills into
                # the running text instead of staying a popover.
                webcomponents=self.webcomponents,
                apply_template=False,
                xpath_base_uri=self.xpath_base_uri,
                xpath_documents=self.xpath_documents,
                xpath_collections=self.xpath_collections,
                xpath_variables=self.xpath_variables,
                xpath_namespaces=self.xpath_namespaces,
            )
            if _cache is not None and mod is self.module:
                _cache[(id(fragment_content), params_key, id(view_root))] = result
            return result
        elif isinstance(fragment_content, str):
            return fragment_content
        else:
            return str(fragment_content)

    def _build_transform_config(self) -> dict[str, Any]:
        """Build the transform config dict once; reuse across all chunks."""
        mod = self.module
        # Mirror what the generated transform() function does, but without
        # re-instantiating HtmlOutputFunctions or rebuilding the dict each time.
        channels = mod.transform_output_channels()
        primary = (channels[0] if channels else '') if isinstance(channels, (list, tuple)) else channels
        pmf: Any
        normalize_text = None
        if primary == 'markdown':
            from opm.runtime.markdown_output_functions import MarkdownOutputFunctions, normalize_markdown_xml_text
            pmf = MarkdownOutputFunctions()
            normalize_text = normalize_markdown_xml_text
        else:
            from opm.runtime.html_output_functions import HtmlOutputFunctions
            pmf = HtmlOutputFunctions()

        # Generated modules export apply_children_impl; fall back to the runtime function.
        from opm.runtime.pm_runtime import apply_children as _apply_children_fallback
        apply_children = getattr(mod, 'apply_children_impl', _apply_children_fallback)

        cfg: dict[str, Any] = {
            'output': [primary] if primary else [],
            'parameters': dict(self.parameters),
            'xpath_extensions': list(self.xpath_extensions) if self.xpath_extensions else None,
            'webcomponents': self.webcomponents,
            'pmf': pmf,
            'apply': mod.apply,
            'apply_children': apply_children,
            'dispatch': mod._dispatch,
            'odd_css': getattr(mod, 'ODD_GENERATED_CSS', ''),
            'footnotes': [],
        }
        cfg.update(
            xpath_runtime_context(
                base_uri=self.xpath_base_uri,
                documents=self.xpath_documents,
                collections=self.xpath_collections,
                variables=self.xpath_variables,
                namespaces=self.xpath_namespaces,
            ),
        )
        if normalize_text is not None:
            cfg['normalize_text'] = normalize_text
        return cfg

    def _run_chunk_transform(self, chunk: etree._Element) -> list:
        """Apply the transform to *chunk*, reusing the shared config dict.

        Resets only the per-chunk mutable state (footnote accumulator + global
        note counter) so we avoid rebuilding HtmlOutputFunctions and the config
        dict on every iteration.
        """
        if self._transform_config is None:
            self._transform_config = self._build_transform_config()
        cfg = self._transform_config
        # Reset per-chunk state.
        cfg['footnotes'] = []
        cfg['parameters'] = {
            **self.parameters,
            **xpath_runtime_context(
                base_uri=self.xpath_base_uri,
                documents=self.xpath_documents,
                collections=self.xpath_collections,
                variables=self.xpath_variables,
                namespaces=self.xpath_namespaces,
                root=self._source_node(chunk),
            ),
        }
        reset_counters()
        result = self.module.apply(cfg, [chunk])
        result = cfg['pmf'].finish(cfg, result)
        return inject_cached_footnotes(result, cfg)

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
                user_css=self.user_css,
                parameters=self.parameters,
                lang="",
                webcomponents_url=self.webcomponents_url,
                # Add chunk-specific context
                fragments=all_fragments,
                chunk=chunk_result.metadata,
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
        :meth:`process_fragment`, rather than pre-selected once from the
        document root (which would yield a single node and skip later chunks).
        """
        return xpath.strip() in ('.', './', 'self::node()', 'self::*')

    def _pb_view_part_nav(
        self, index: int, chunk_ids: list[str], xml_id: str
    ) -> dict[str, Any]:
        """Build navigation fields mirroring ``/api/parts/.../json``.

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
          a sibling ``<name>.html`` is written with the same HTML content
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
            (data_dir / f'{frag.name}.html').write_text(frag_html, encoding='utf-8')

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
) -> None:
    """Chunk a document using the specified configuration."""
    resolved_module = module_path or config.module
    if resolved_module is None and config.odd is not None:
        from opm.odd_cache import ensure_compiled_module

        resolved_module, _ = ensure_compiled_module(config.odd, output_mode='web')
    if resolved_module is None:
        raise ValueError(
            'No transform module specified. Pass a module path, set chunking.odd '
            'in your config, or use the packaged teipublisher ODD.',
        )

    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    cfg = project_config or ProjectConfig()
    xpath_documents = load_xpath_documents(cfg.xpath_documents)
    xpath_collections, xpath_documents = load_xpath_collections(
        cfg.xpath_collections, xpath_documents,
    )

    processor = ChunkProcessor(
        resolved_module, root, config, project_root,
        project_config=project_config,
        webcomponents=webcomponents,
        xpath_extensions=xpath_extensions,
        xpath_base_uri=xml_path.resolve().as_uri(),
        xpath_documents=xpath_documents,
        xpath_collections=xpath_collections,
        xpath_variables=dict(cfg.xpath_variables),
        xpath_namespaces=dict(cfg.xpath_namespaces),
    )
    if output_format == 'pb-view':
        processor.export_pb_view(doc_path=doc_path, on_progress=on_progress)
    else:
        processor.process_all(template_path, on_progress=on_progress, output_format=output_format)
