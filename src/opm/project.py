# SPDX-FileCopyrightText: 2026 e-editiones
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The supported way to drive opm from Python: [`Project`][opm.project.Project].

A specific project configuration and associated methods. Each method does
what the command of the same name does, taking the same settings from the
config:

```python
from opm import Project

project = Project.load()                       # ./opm.toml
html = project.transform('data/doc.xml')       # -t web
docx = project.transform('data/doc.xml', mode='docx')
run = project.chunk('data/letters', format='json', overwrite=True)
records = project.index('data')
```

The lower-level functions in [`opm.transform`][opm.transform], [`opm.chunking`][opm.chunking] and
[`opm.indexing`][opm.indexing] stay available for callers that need finer control.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence, Union

from urllib.parse import urlparse
from urllib.request import url2pathname

from lxml import etree

from opm.chunking import build_index, chunk_document
from opm.config import (
    CONFIG_FILENAME,
    ChunkingConfig,
    ProjectConfig,
    load_project_config,
    resolve_base_css,
)
from opm.odd_cache import ResolvedTransform, resolve_transform_module
from opm.output_modes import output_mode
from opm.transform import (
    load_project_documents,
    load_transform_module,
    transform_with_config,
)

if TYPE_CHECKING:
    from opm.coverage import CoverageReport
    from opm.indexing import IndexOptions

#: An XML input: a file, or a tree or element parsed with lxml.
Source = Union[Path, str, etree._Element, etree._ElementTree]

#: The ``format`` values [`Project.chunk`][opm.project.Project.chunk] accepts.
CHUNK_FORMATS = ('html', 'json', 'pb-view')


@dataclass(frozen=True)
class ChunkRun:
    """What [`Project.chunk`][opm.project.Project.chunk] wrote."""

    output_dir: Path
    """Root of the output. A directory run writes one subdirectory per document."""
    documents: tuple[Path, ...]
    """The XML files that were chunked, in order."""
    format: str
    """``html``, ``json`` or ``pb-view``."""
    modules: tuple[ResolvedTransform, ...]
    """The transform modules used: the main one first, then the fragment ones."""
    index_file: Path | None = None
    """The ``index.html`` an HTML run over a directory writes at the output root."""


def chunk_input_files(source: Path) -> list[Path]:
    """The XML files a chunk run over *source* reads.

    That is *source* itself, or the ``*.xml`` files directly inside it when it
    is a directory. Subdirectories are not searched: a chunk run publishes the
    pages of a given set of documents.
    """
    if source.is_dir():
        return sorted(
            path for path in source.iterdir()
            if path.is_file() and path.suffix.lower() == '.xml'
        )
    return [source]


def _corpus_files(sources: Path | str | Iterable[Path | str]) -> list[Path]:
    """Files for [`Project.index`][opm.project.Project.index] and [`Project.coverage`][opm.project.Project.coverage].

    A directory stands for every ``*.xml`` file below it, subdirectories
    included, since corpora are often filed in them.
    """
    items = [sources] if isinstance(sources, (str, Path)) else list(sources)
    files: list[Path] = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob('*.xml') if p.is_file()))
        else:
            files.append(path)
    return files


def _source_path(source: Source) -> Path | None:
    """The file *source* was read from, when it is known and local."""
    if isinstance(source, (str, Path)):
        return Path(source)
    # The document's URL, unless an xml:base says otherwise.
    url = _source_root(source).base  # type: ignore[attr-defined]  # missing from the lxml stubs
    if not url:
        return None
    if url.startswith('file:'):
        return Path(url2pathname(urlparse(url).path))
    if '://' in url:
        return None
    return Path(url)


def _source_root(source: Source) -> etree._Element:
    if isinstance(source, (str, Path)):
        return etree.parse(str(source)).getroot()
    if isinstance(source, etree._ElementTree):
        return source.getroot()
    return source


def _clear_output_dir(out_dir: Path, overwrite: bool) -> None:
    """Remove *out_dir* if it exists and *overwrite* allows it; otherwise raise."""
    if not out_dir.exists():
        return
    if not overwrite:
        raise FileExistsError(
            f'output directory {out_dir} already exists; pass overwrite=True to replace it.',
        )
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
    else:
        out_dir.unlink()


class Project:
    """An opm project represents a specific configuration and its associated methods.

    Each method takes whatever its arguments leave open from the config, as
    the command of the same name does. ODDs compile on demand into the user
    cache, as they do for the CLI.

    A project is a snapshot. It keeps the modules it has loaded and the
    register documents it has parsed, so repeated calls are cheap, for
    example in a web service. After editing an ODD or a register, make a new
    ``Project``. One instance can be shared between threads.

    An XPath expression that fails at run time counts as false or empty, as
    it does in the CLI. To see which ones failed, wrap the calls in
    [`collect_xpath_errors`][opm.runtime.xpath_diagnostics.collect_xpath_errors]:

    ```python
    from opm import Project, collect_xpath_errors

    project = Project.load('edition/opm.toml')
    with collect_xpath_errors() as log:
        html = project.transform('edition/data/doc.xml')
    for failure in log.ordered_failures():
        print(failure.expression, failure.message)
    ```

    Relative paths given to the methods are relative to the current
    directory, as usual in Python. Paths inside ``opm.toml`` are relative to
    the file's directory, and the chunk ``output_dir`` to [`root`][opm.project.Project.root].

    Args:
        config: The project settings. Defaults to an empty config, which
            uses the packaged ODD.
        root: The project directory: chunk output goes below it, and
            ``styles/default-styles.css`` there replaces the packaged base
            rules. Defaults to the current directory.
    """

    def __init__(
        self,
        config: ProjectConfig | None = None,
        *,
        root: Path | str | None = None,
    ) -> None:
        self.config: ProjectConfig = config if config is not None else ProjectConfig()
        """The settings from ``opm.toml``."""
        self.root: Path = Path(root).absolute() if root is not None else Path.cwd()
        """The project directory."""
        # Project modules (XPath extensions, chunk selectors) import from here.
        self.config.extend_sys_path()
        self._lock = threading.Lock()
        self._resolved: dict[tuple[str, Path | None, bool], ResolvedTransform] = {}
        self._modules: dict[Path, ModuleType] = {}
        self._registers: tuple[dict[str, Any], dict[str, list]] | None = None

    @classmethod
    def load(cls, path: Path | str | None = None, *, root: Path | str | None = None) -> Project:
        """Load the project with the configuration given in *path*.

        Without *path*, ``opm.toml`` in the current directory is read if it
        exists; if not, the project has default settings. *root* defaults to
        the config file's directory.

        Raises:
            FileNotFoundError: *path* was given but is not a file.
        """
        if path is not None and not Path(path).is_file():
            raise FileNotFoundError(f'Config file not found: {path}')
        config_path = Path(path) if path is not None else Path(CONFIG_FILENAME)
        config = load_project_config(config_path)
        return cls(config, root=root if root is not None else config_path.absolute().parent)

    def with_config(self, **changes: Any) -> Project:
        """A new project with some [`ProjectConfig`][opm.config.ProjectConfig] fields replaced.

        For example, ``project.with_config(document_css=Path('print.css'))``.
        """
        return Project(replace(self.config, **changes), root=self.root)

    # ── compiling ────────────────────────────────────────────────────────────

    def compile(self, mode: str | None = None, odd: Path | str | None = None) -> ResolvedTransform:
        """Compile the ODD for output *mode*, or find it in the cache.

        The ODD is *odd*, else ``[transform.<mode>] odd``, else
        ``[transform] odd``, else the packaged ``teipublisher.odd``.

        Args:
            mode: An output mode such as ``web``, ``markdown``, ``docx``,
                ``typst`` or ``json`` (see [`opm.output_modes`][opm.output_modes]).
                Defaults to ``web``.
            odd: The ODD to use instead of the configured one.

        Raises:
            ValueError: *mode* is not an output mode.
        """
        name = output_mode(mode).name
        chosen = Path(odd) if odd is not None else self.config.odd_for_type(name)
        return self._resolve(name, chosen)

    def module(self, mode: str | None = None, odd: Path | str | None = None) -> ModuleType:
        """The loaded transform module for *mode*; see [`compile`][opm.project.Project.compile]."""
        return self._load(self.compile(mode, odd).module_path)

    def _resolve(
        self, mode: str, odd: Path | None, *, packaged_default: bool = True,
    ) -> ResolvedTransform:
        name = output_mode(mode).name
        key = (name, odd.absolute() if odd is not None else None, packaged_default)
        with self._lock:
            found = self._resolved.get(key)
        if found is None:
            found = resolve_transform_module(
                odd=odd,
                output_mode=name,
                use_packaged_default=packaged_default,
                base_css=resolve_base_css(self.config.document_css, self.root),
            )
            with self._lock:
                found = self._resolved.setdefault(key, found)
        return found

    def _load(self, path: Path) -> ModuleType:
        with self._lock:
            mod = self._modules.get(path)
        if mod is None:
            mod = load_transform_module(path)
            with self._lock:
                mod = self._modules.setdefault(path, mod)
        return mod

    def _documents(self) -> tuple[dict[str, Any], dict[str, list]]:
        """The register and collection documents, parsed once."""
        with self._lock:
            if self._registers is None:
                self._registers = load_project_documents(self.config)
            return self._registers

    # ── transforming ─────────────────────────────────────────────────────────

    def transform(
        self,
        source: Source,
        *,
        mode: str | None = None,
        odd: Path | str | None = None,
        xpath: str | None = None,
        parameters: dict[str, str] | None = None,
        xpath_extensions: Sequence[str] | None = None,
        webcomponents: bool | None = None,
        template: Path | None = None,
    ) -> str | bytes:
        """Transform *source*, as ``opm transform`` does.

        Args:
            source: An XML file, or a tree or element parsed with lxml. When
                an element comes from a parsed file, ``doc()`` resolves
                against that file and ``$parameters?input_path`` names it.
            mode: The output mode (``web`` by default); see [`compile`][opm.project.Project.compile].
            odd: The ODD to use instead of the configured one.
            xpath: XPath 3.1 expression selecting the element to transform.
                Unprefixed names use the document's default namespace.
            parameters: XPath ``$parameters``, over ``[transform.parameters]``.
            xpath_extensions: Extension modules to use instead of the
                configured ones.
            webcomponents: Enable web-component mode. ``None`` uses the config.
            template: The document template to use instead of the configured one.

        Returns:
            ``str`` for text output (HTML, Markdown, Typst, JSON) and ``bytes``
            for DOCX and EPUB.
        """
        return transform_with_config(
            self.module(mode, odd),
            _source_root(source),
            _source_path(source),
            self.config,
            xpath=xpath,
            parameters=parameters,
            xpath_extensions=xpath_extensions,
            webcomponents=webcomponents,
            template=template,
            documents=self._documents(),
        )

    # ── chunking ─────────────────────────────────────────────────────────────

    def _chunking(self) -> ChunkingConfig:
        if self.config.chunking is None:
            raise ValueError('no [chunking] section found in config.')
        return self.config.chunking

    def chunk_output_dir(self, output_dir: Path | str | None = None) -> Path:
        """Where [`chunk`][opm.project.Project.chunk] writes: *output_dir*, else ``[chunking] output_dir``, below [`root`][opm.project.Project.root]."""
        return self.root / (output_dir if output_dir is not None else self._chunking().output_dir)

    def chunk_modules(self, odd: Path | str | None = None) -> tuple[ResolvedTransform, ...]:
        """Compile the modules a chunk run uses: the main one, then one per fragment ODD.

        The main ODD is *odd*, else ``[chunking] odd``, else the packaged one.
        Fragments without an ODD of their own use the main module.

        Raises:
            ValueError: The config has no ``[chunking]`` section.
        """
        chunking = self._chunking()
        main_odd = Path(odd) if odd is not None else chunking.odd
        main = self._resolve('web', main_odd, packaged_default=main_odd is None)
        fragments = tuple(
            self._resolve(fragment.mode, fragment.odd, packaged_default=False)
            for fragment in chunking.fragments or ()
            if fragment.odd is not None
        )
        return (main, *fragments)

    def chunk(
        self,
        source: Path | str,
        *,
        format: str = 'html',
        output_dir: Path | str | None = None,
        template: Path | None = None,
        depth: int | None = None,
        odd: Path | str | None = None,
        doc_path: str | None = None,
        webcomponents: bool | None = None,
        xpath_extensions: Sequence[str] | None = None,
        overwrite: bool = False,
        on_document: Callable[[int, Path], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ChunkRun:
        """Split *source* into pages, as ``opm chunk`` does.

        *source* is one XML file or a directory of them. For a directory,
        each document goes to a subdirectory named after it, and an HTML run
        also writes ``index.html`` listing the documents. ``pb-view`` output
        puts every document's data under ``<doc_path>/<name>.xml/`` instead.

        The arguments override the ``[chunking]`` settings of the same name.

        Args:
            source: An XML file, or a directory of XML files (not searched
                recursively).
            format: ``html`` (pages rendered with the chunk template),
                ``json`` (one JSON file per chunk, for static site
                generators) or ``pb-view`` (data for the ``pb-view`` web
                component in static mode).
            output_dir: Output directory, relative to [`root`][opm.project.Project.root].
            template: Page template for HTML output.
            depth: Maximum section depth to split at.
            odd: The ODD to use instead of ``[chunking] odd``.
            doc_path: For ``pb-view``: the ``pb-document`` path the data is
                written under.
            webcomponents: Enable web-component mode for HTML output. JSON
                and ``pb-view`` output always use it.
            xpath_extensions: Extension modules to use instead of the
                configured ones.
            overwrite: Replace the output directory if it exists. Without
                it, an existing directory raises `FileExistsError`.
            on_document: Called with the position and path of each document
                before it is chunked.
            on_progress: Called with ``(done, total)`` chunks as each
                document is processed.

        Raises:
            ValueError: The config has no ``[chunking]`` section, *format* is
                unknown, or a directory contains no XML files.
            FileExistsError: The output directory exists and *overwrite*
                does not allow replacing it.
        """
        if format not in CHUNK_FORMATS:
            raise ValueError(f'format must be "html", "json" or "pb-view", got {format!r}')
        source = Path(source)
        files = chunk_input_files(source)
        by_directory = source.is_dir()
        if by_directory and not files:
            raise ValueError(f'no XML files found in directory {source}.')

        modules = self.chunk_modules(odd)
        chunking = self._chunking()
        changes: dict[str, Any] = {'module': modules[0].module_path}
        if output_dir is not None:
            changes['output_dir'] = str(output_dir)
        if template is not None:
            changes['template'] = Path(template)
        if depth is not None:
            changes['depth'] = depth
        if odd is not None:
            changes['odd'] = Path(odd)
        if chunking.fragments:
            compiled = iter(modules[1:])
            changes['fragments'] = [
                replace(fragment, module=next(compiled).module_path if fragment.odd else None)
                for fragment in chunking.fragments
            ]
        chunking = replace(chunking, **changes)

        out_dir = self.chunk_output_dir(chunking.output_dir)
        _clear_output_dir(out_dir, overwrite)

        enabled = (
            True if format in ('json', 'pb-view')
            else webcomponents if webcomponents is not None
            else bool(self.config.webcomponents_enabled)
        )
        extensions = tuple(xpath_extensions) if xpath_extensions else None
        base_doc_path = doc_path or chunking.doc_path
        # Built once and shared: templates test links against it.
        names = frozenset(path.name for path in files)

        for position, xml_file in enumerate(files):
            if on_document is not None:
                on_document(position, xml_file)
            if by_directory and format != 'pb-view':
                document_config = replace(
                    chunking,
                    output_dir=f'{chunking.output_dir.rstrip("/")}/{xml_file.name}',
                    link_doc=xml_file.name,
                )
            elif Path(chunking.output_dir).name == xml_file.name:
                # Single-file output into …/<name>.xml/ should still expand {doc}.
                document_config = replace(chunking, link_doc=xml_file.name)
            else:
                document_config = chunking
            if by_directory and format == 'pb-view':
                document_doc_path = (
                    f'{base_doc_path.rstrip("/")}/{xml_file.name}' if base_doc_path
                    else xml_file.name
                )
            else:
                document_doc_path = base_doc_path

            chunk_document(
                module_path=chunking.module,
                xml_path=xml_file,
                config=document_config,
                project_root=self.root,
                template_path=chunking.template,
                on_progress=on_progress,
                project_config=self.config,
                webcomponents=enabled,
                xpath_extensions=extensions,
                output_format=format,
                doc_path=document_doc_path,
                documents=names,
            )

        # A directory run leaves one subdirectory per document, which a web
        # server would otherwise show as a bare listing.
        index_file: Path | None = None
        if by_directory and format == 'html':
            index_file = build_index(
                out_dir,
                template_path=chunking.index_template,
                title=chunking.index_title or source.name,
                module_path=chunking.module,
                project_config=self.config,
                project_root=self.root,
                chunking_config=chunking,
                webcomponents=enabled,
            )
        return ChunkRun(
            output_dir=out_dir,
            documents=tuple(files),
            format=format,
            modules=modules,
            index_file=index_file,
        )

    # ── indexing and coverage ────────────────────────────────────────────────

    def index(
        self,
        sources: Path | str | Iterable[Path | str],
        *,
        odd: Path | str | None = None,
        options: IndexOptions | None = None,
    ) -> list[dict]:
        """Search-index records for *sources*, as ``opm index`` makes them.

        Args:
            sources: An XML file, a directory (searched recursively), or a
                list of either.
            odd: The ODD to use instead of ``[transform.json] odd``.
            options: Rollup settings. ``None`` uses ``[index]`` from the config.

        Write the result with [`opm.indexing.write_jsonl`][opm.indexing.write_jsonl].
        """
        from opm.indexing import index_document

        base_css = resolve_base_css(self.config.document_css, self.root)
        records: list[dict] = []
        for path in _corpus_files(sources):
            records.extend(
                index_document(
                    path,
                    cfg=self.config,
                    odd=Path(odd) if odd is not None else None,
                    project_root=self.root,
                    options=options,
                    base_css=base_css,
                ),
            )
        return records

    def coverage(
        self,
        sources: Path | str | Iterable[Path | str],
        *,
        mode: str = 'json',
        odd: Path | str | None = None,
        parameters: dict[str, str] | None = None,
    ) -> CoverageReport:
        """Measure the ODD against *sources*, as ``opm coverage`` does.

        Args:
            sources: An XML file, a directory (searched recursively), or a
                list of either.
            mode: ``json`` for the web channel, or ``json-<channel>`` for
                another one (``json-print``, ``json-typst``, …).
            odd: The ODD to use instead of ``[transform.json] odd``.
            parameters: XPath ``$parameters``, over ``[transform.parameters]``.
        """
        from opm.coverage import analyze

        name = output_mode(mode).name
        chosen = Path(odd) if odd is not None else self.config.odd_for_type(name)
        return analyze(
            _corpus_files(sources),
            cfg=self.config,
            odd=chosen,
            output_mode=name,
            parameters=parameters,
            base_css=resolve_base_css(self.config.document_css, self.root),
        )
