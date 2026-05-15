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

from teipublisher.config import ChunkingConfig, FragmentConfig, ProjectConfig, DEFAULT_CDN_TEMPLATE, DEFAULT_VERSION
from teipublisher.transform import load_transform_module, run_transform, xpath_select
from teipublisher.template_rendering import resolve_template_path, _inner_html
from teipublisher.runtime.pm_runtime import serialize as _default_serialize, inject_cached_footnotes
from teipublisher.runtime.output_functions import XML_ID, reset_counters


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
        self.chunks: list[etree._Element] = []
        self.results: list[ChunkResult] = []
        self._jinja_env: Any | None = None
        self._jinja_template: Any | None = None
        # Built once; only config['footnotes'] is reset between chunks.
        self._transform_config: dict[str, Any] | None = None
        self._chunk_anchor_map: dict[str, str] = {}

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
            try:
                nsmap: dict[str, str] = {k: v for k, v in self.xml_root.nsmap.items() if k is not None}
                chunks = self.xml_root.xpath(self.config.xpath, namespaces=nsmap or None)  # type: ignore[arg-type]
            except Exception:
                chunks = xpath_select(
                    self.xml_root,
                    self.config.xpath,
                    xpath_extensions=self.xpath_extensions or None,
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
            xpath=self.config.xpath + f"[{index + 1}]",
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
            return pattern.format(file=target_file, stem=stem, anchor=anchor)
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
    ) -> str:
        """Process a fragment transform."""
        if fragment.scope == 'global':
            context = self.xml_root
        else:
            context = context_node if context_node is not None else self.xml_root

        fragment_content = xpath_select(
            context,
            fragment.xpath,
            params=fragment.params or {},
            xpath_extensions=self.xpath_extensions or None,
        )

        if not fragment_content:
            return ""

        if isinstance(fragment_content, list) and len(fragment_content) == 1:
            fragment_content = fragment_content[0]

        if isinstance(fragment_content, etree._Element):
            mod = (
                self._fragment_modules[str(fragment.module)]
                if fragment.module
                else self.module
            )
            params_key = frozenset((fragment.params or {}).items())
            if _cache is not None and mod is self.module:
                cache_key = (id(fragment_content), params_key)
                if cache_key in _cache:
                    return _cache[cache_key]
            result = run_transform(
                mod,
                fragment_content,
                parameters=fragment.params or {},
                xpath_extensions=self.xpath_extensions or None,
                apply_template=False,
            )
            if _cache is not None and mod is self.module:
                _cache[(id(fragment_content), params_key)] = result
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
            from teipublisher.runtime.markdown_output_functions import MarkdownOutputFunctions, normalize_markdown_xml_text
            pmf = MarkdownOutputFunctions()
            normalize_text = normalize_markdown_xml_text
        else:
            from teipublisher.runtime.html_output_functions import HtmlOutputFunctions
            pmf = HtmlOutputFunctions()

        # Generated modules export apply_children_impl; fall back to the runtime function.
        from teipublisher.runtime.pm_runtime import apply_children as _apply_children_fallback
        apply_children = getattr(mod, 'apply_children_impl', _apply_children_fallback)

        cfg: dict[str, Any] = {
            'output': [primary] if primary else [],
            'parameters': {},
            'xpath_extensions': list(self.xpath_extensions) if self.xpath_extensions else None,
            'webcomponents': self.webcomponents,
            'pmf': pmf,
            'apply': mod.apply,
            'apply_children': apply_children,
            'dispatch': mod._dispatch,
            'odd_css': getattr(mod, 'ODD_GENERATED_CSS', ''),
            'footnotes': [],
        }
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
        reset_counters()
        result = self.module.apply(cfg, [chunk])
        result = cfg['pmf'].finish(cfg, result)
        return inject_cached_footnotes(result, cfg)

    def process_chunk(self, chunk: etree._Element, index: int) -> ChunkResult:
        """Process a single chunk with its fragments."""
        metadata = self.generate_chunk_metadata(chunk, index)

        # Call the transform pipeline directly so we can work with the raw lxml
        # result (avoids serialize → HTMLParser re-parse) and reuse the shared
        # config dict (avoids rebuilding HtmlOutputFunctions each iteration).
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
            content_html = _inner_html(html_el.find('body'))
            head_html = _inner_html(html_el.find('head'))
        else:
            # Fragment: one serialization, no re-parse.
            content_html = serialize(raw_result)
            head_html = ''

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
                        self.process_fragment(fragment, chunk, _cache),
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
                odd_css="",
                user_css="",
                parameters={},
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
                    'odd_css': getattr(self.module, 'ODD_GENERATED_CSS', ''),
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
) -> None:
    """Chunk a document using the specified configuration."""
    resolved_module = module_path or config.module
    if resolved_module is None:
        raise ValueError(
            'No transform module specified. Pass a module path or set chunking.module in your config.'
        )

    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    processor = ChunkProcessor(
        resolved_module, root, config, project_root,
        project_config=project_config,
        webcomponents=webcomponents,
        xpath_extensions=xpath_extensions,
    )
    processor.process_all(template_path, on_progress=on_progress, output_format=output_format)
