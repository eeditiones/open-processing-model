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

import glob
import itertools
import shutil
import threading
from dataclasses import dataclass, field, fields, replace
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, Iterable, Sequence, Union

from urllib.parse import urlparse
from urllib.request import url2pathname

from lxml import etree

from opm.xml_parser import parse as parse_xml

from opm.chunking import build_index, chunk_document
from opm.config import (
    CONFIG_FILENAME,
    ChunkingConfig,
    PageConfig,
    ProjectConfig,
    load_project_config,
    resolve_base_css,
)
from opm.jinks_templates.merge import merge_deep
from opm.profile import load_profiles, merge_profile_configs, get_profile_paths, PROFILE_LOCATIONS
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
    """Root of the output, holding one subdirectory per document."""
    documents: tuple[Path, ...]
    """The XML files that were chunked, in order."""
    format: str
    """``html``, ``json`` or ``pb-view``."""
    modules: tuple[ResolvedTransform, ...]
    """The transform modules used: the main one first, then the fragment ones."""
    index_file: Path | None = None
    """The ``index.html`` at the output root: the generated collection index, or
    the project's own page when a ``[[pages]]`` entry has ``path = "index.html"``."""
    document_dirs: dict[Path, str] = field(default_factory=dict)
    """Each document's directory name below [`output_dir`][opm.project.ChunkRun.output_dir], by source file.

    A file read by several runs is listed with the first run's directory.
    """
    pages: tuple[Path, ...] = ()
    """The auxiliary pages (``[[pages]]``) written below [`output_dir`][opm.project.ChunkRun.output_dir], absolute."""


def _document_config(
    run: ChunkingConfig, xml_file: Path, format: str, name: str | None = None,
) -> ChunkingConfig:
    """*run* as it applies to one document: where its pages go, and ``{doc}``.

    *name* is the document's directory name (see
    [`document_names`][opm.project.document_names]); it defaults to the
    file name.
    """
    if format == 'pb-view':
        # pb-view keeps its own layout: the data is fetched by path rather than
        # served as pages, and `doc_path` places it.
        return run
    name = name or xml_file.name
    if Path(run.output_dir).name in (name, xml_file.name):
        # The output directory already names the document (-o site/doc.xml), so
        # take it as the per-document directory instead of nesting twice.
        return replace(run, link_doc=Path(run.output_dir).name)
    # One document or many, pages go to <output>/<name>/ with the
    # stylesheets, assets and index shared at the root. Chunking a single file
    # therefore publishes the same URLs it will still publish once a second
    # document joins it.
    return replace(
        run,
        output_dir=f'{run.output_dir.rstrip("/")}/{name}',
        link_doc=name,
    )


def document_names(
    files: Sequence[Path],
    expr: str | None,
    config: ProjectConfig,
    *,
    extensions: Sequence[str] | None = None,
) -> dict[Path, str]:
    """The output directory name of each of *files*: ``[chunking] document_name``.

    *expr* is evaluated with each document's root as context, in the project's
    XPath environment; its string value is the name. A ``/`` in it nests the
    directory (``aarets-historie/collation``); other unsafe characters within
    each part are replaced. Without *expr* every document keeps its file name.

    Raises:
        ValueError: A document's name is empty or not a usable directory
            name, two documents get the same name, or one document's directory
            would lie inside another's.
    """
    if not expr:
        # Files matched by a glob pattern may share a name across directories.
        taken_by_file: dict[str, Path] = {}
        for path in files:
            if path.name in taken_by_file:
                raise ValueError(
                    f'{taken_by_file[path.name]} and {path} would both be written to '
                    f'{path.name}/; set [chunking] document_name to name the documents apart.',
                )
            taken_by_file[path.name] = path
        return {path: path.name for path in files}
    from opm.chunking import _safe_file_stem
    from opm.transform import project_xpath_env

    # The registers are parsed once for the run, not once per document.
    documents = load_project_documents(config)
    names: dict[Path, str] = {}
    taken: dict[str, Path] = {}
    for path in files:
        root = parse_xml(str(path)).getroot()
        env = project_xpath_env(config, path, extensions=extensions, documents=documents)
        value = env.select(root, expr)
        if isinstance(value, list):
            value = ''.join(
                item.xpath('string()') if isinstance(item, etree._Element) else str(item)
                for item in value
            )
        parts = [_safe_file_stem(part) for part in str(value).strip().strip('/').split('/')]
        name = '/'.join(parts)
        if any(part in ('', '.', '..') for part in parts):
            raise ValueError(
                f'[chunking] document_name gives no usable name for {path.name}: '
                f'{expr} evaluated to {str(value)!r}.',
            )
        if name in taken:
            raise ValueError(
                f'[chunking] document_name gives {taken[name].name} and {path.name} '
                f'the same name, {name!r}.',
            )
        taken[name] = path
        names[path] = name
    _check_document_dirs(names.items())
    return names


def _check_document_dirs(names: Iterable[tuple[Path, str]]) -> None:
    """No two documents share a directory, and none lies inside another's.

    A document's directory holding another's would mix their pages, and the
    collection index could not tell them apart. A file read by two runs
    appears twice, once per directory.
    """
    taken: dict[str, Path] = {}
    for path, name in names:
        if name in taken:
            raise ValueError(
                f'{taken[name].name} and {path.name} would both be written to {name}/.',
            )
        taken[name] = path
    for name, path in taken.items():
        for parent in PurePosixPath(name).parents:
            if str(parent) in taken:
                raise ValueError(
                    f'[chunking] document_name puts {path.name} ({name!r}) inside the '
                    f'directory of {taken[str(parent)].name} ({str(parent)!r}).',
                )


def is_glob_pattern(source: Path | str) -> bool:
    """Whether *source* is a glob pattern rather than a path: it holds ``*``, ``?`` or ``[``.

    A file or directory that exists under that very name is a path, so a
    directory called ``data[old]`` still works.
    """
    return any(char in str(source) for char in '*?[') and not Path(source).exists()


def is_multi_document(source: Path | str) -> bool:
    """Whether a chunk run over *source* may read several documents: a directory or a glob pattern.

    Such a run writes each document to a subdirectory of its own and, for
    HTML, an ``index.html`` listing them.
    """
    return is_glob_pattern(source) or Path(source).is_dir()


@dataclass(frozen=True)
class ChunkInput:
    """Documents read by one or more ``[[chunking]]`` runs."""

    runs: tuple[ChunkingConfig, ...]
    """The runs reading them, in config order."""
    source: Path | str
    """The file, directory or glob pattern they come from."""
    files: tuple[Path, ...]
    """The XML files *source* stands for."""


def _run_label(run: ChunkingConfig, runs: Sequence[ChunkingConfig]) -> str:
    return f'"{run.name}"' if run.name else f'#{list(runs).index(run) + 1}'


def chunk_inputs(
    runs: Sequence[ChunkingConfig], source: Path | str | None = None,
) -> list[ChunkInput]:
    """Which documents each ``[[chunking]]`` run reads.

    A run with an ``input`` of its own reads those files; every run without
    one reads *source*, the input given on the command line, together. When
    every run has its own input, *source* is not used (see
    [`runs_ignoring_source`][opm.project.runs_ignoring_source]).

    Two runs may read the same files, as long as their ``document_name``
    puts them in different directories (one presentation per run).

    Raises:
        ValueError: A run has neither an input of its own nor a *source*, or
            an input matches no file.
    """
    groups: list[ChunkInput] = []
    shared = tuple(run for run in runs if run.input is None)
    for run in runs:
        if run.input is not None:
            groups.append(ChunkInput((run,), run.input, ()))
        elif run is shared[0]:
            if source is None:
                labels = ', '.join(_run_label(item, runs) for item in shared)
                raise ValueError(
                    f'no input for [[chunking]] run {labels}: give one on the command '
                    'line or set input in opm.toml.'
                )
            groups.append(ChunkInput(shared, source, ()))
    result: list[ChunkInput] = []
    for group in groups:
        files = chunk_input_files(group.source)
        if not files:
            where = ', '.join(_run_label(run, runs) for run in group.runs)
            if is_glob_pattern(group.source):
                raise ValueError(f'no files match {group.source} ([[chunking]] run {where}).')
            raise ValueError(f'no XML files found in {group.source} ([[chunking]] run {where}).')
        result.append(replace(group, files=tuple(files)))
    return result


def runs_ignoring_source(runs: Sequence[ChunkingConfig]) -> list[str]:
    """Labels of the runs that read an ``input`` of their own and so ignore a command-line input."""
    return [_run_label(run, runs) for run in runs if run.input is not None]


def _source_label(source: Path | str) -> str:
    """A name for *source* in the collection index: its last component, or for
    a glob pattern the last directory before the first wildcard
    (``data/collation/**/*.col.xml`` → ``collation``).
    """
    path = Path(source)
    if not is_glob_pattern(source):
        return path.name
    fixed = list(itertools.takewhile(lambda part: not is_glob_pattern(part), path.parts))
    return Path(*fixed).resolve().name if fixed else Path.cwd().name


def chunk_input_files(source: Path | str) -> list[Path]:
    """The XML files a chunk run over *source* reads.

    That is *source* itself; the ``*.xml`` files directly inside it when it
    is a directory; or the files matching it when it is a glob pattern, where
    ``**`` matches any number of subdirectories. A directory is not searched
    recursively: a chunk run publishes the pages of a given set of documents,
    and a pattern is how to name a set filed in subdirectories.
    """
    if is_glob_pattern(source):
        return sorted(
            Path(path) for path in glob.glob(str(source), recursive=True)
            if Path(path).is_file()
        )
    source = Path(source)
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
        return parse_xml(str(source)).getroot()
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
        
        # Load profiles
        self._profiles: tuple[Any, ...] = self._load_profiles()
        
        if self._profiles:
            self.config = self._with_profile_files(self.config)
        # Profiles contribute defaults to the template context: a later profile
        # overrides an earlier one, and the project's own [context] overrides both.
        if self._profiles:
            from opm.template_frontmatter import merge_deep
            merged_context = merge_deep(
                *(profile_config.config.get('context') for profile_config, _ in self._profiles),
                self.config.template_context,
            )
            if merged_context != self.config.template_context:
                self.config = replace(self.config, template_context=merged_context)
        
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

    def _with_profile_files(self, config: ProjectConfig) -> ProjectConfig:
        """*config* with the profiles' assets, fragments and pages added.

        Profile assets come before the project's, so the project's stylesheets
        cascade after them. A profile fragment is added to every chunking run
        that has no fragment of the same name. A profile page is added; when
        the project declares a page with the same ``path``, the keys the
        project's entry sets win (see [`_merge_page`][opm.project._merge_page]),
        so it can repoint a profile's ``source`` or relabel a page and keep
        the rest. Applying this twice changes nothing, so a
        [`with_config`][opm.project.Project.with_config] copy stays as it was.
        """
        from opm.config import parse_fragments, parse_pages

        assets: list[Path] = []
        fragments = []
        pages = []
        for profile_config, profile_path in self._profiles:
            assets.extend(profile_path / entry for entry in profile_config.assets)
            fragments.extend(parse_fragments(profile_config.fragments, profile_path))
            pages.extend(
                replace(page, from_profile=True)
                for page in parse_pages(
                    profile_config.pages, profile_path, self.root,
                    label=f"profile '{profile_config.name}'",
                )
            )
        if not assets and not fragments and not pages:
            return config

        def with_assets(existing: Sequence[Path]) -> tuple[Path, ...]:
            return (*(a for a in assets if a not in existing), *existing)

        def run_with(run: ChunkingConfig) -> ChunkingConfig:
            own = list(run.fragments or [])
            names = {fragment.name for fragment in own}
            extra = [f for f in fragments if f.name not in names]
            return replace(run, assets=with_assets(run.assets), fragments=[*own, *extra] or None)

        runs = tuple(run_with(run) for run in config.chunking_runs)
        chunking = (
            runs[0] if runs and config.chunking is config.chunking_runs[0]
            else run_with(config.chunking) if config.chunking is not None
            else None
        )
        profile_pages = {page.path: page for page in pages}
        own_page_paths = {page.path for page in config.pages}
        merged_pages = (
            *(
                _merge_page(page, profile_pages[page.path]) if page.path in profile_pages else page
                for page in config.pages
            ),
            *(p for p in pages if p.path not in own_page_paths),
        )
        return replace(
            config,
            web_assets=with_assets(config.web_assets),
            chunking_runs=runs,
            chunking=chunking,
            pages=merged_pages,
        )

    def _load_profiles(self) -> tuple:
        """Load and return the project's profiles.
        
        Profiles are loaded from:
        1. The project's local profiles/ directory
        2. ~/.opm/profiles/ (user profiles)
        3. Bundled profiles in opm.resources.profiles
        
        Returns:
            Tuple of (profile_config, profile_path) for each profile
        """
        if not self.config.profiles:
            return ()
        
        # Build search paths: project-local, user, bundled
        from opm.profile import profile_search_paths

        search_paths = profile_search_paths(self.root)
        
        profiles = []
        for profile_name in self.config.profiles:
            # Find the actual profile path
            profile_path = None
            for sp in search_paths:
                candidate = sp / profile_name
                if candidate.is_dir():
                    profile_path = candidate
                    break
            
            if profile_path is None:
                raise FileNotFoundError(
                    f"Profile '{profile_name}' not found in any of: "
                    f"{', '.join(str(p) for p in search_paths)}"
                )
            
            profile_config = load_profiles([profile_name], search_paths)[0]
            profiles.append((profile_config, profile_path))
        
        return tuple(profiles)

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
            project=self,
        )

    # ── chunking ─────────────────────────────────────────────────────────────

    def _chunking(self) -> ChunkingConfig:
        if self.config.chunking is None:
            raise ValueError('no [chunking] section found in config.')
        return self.config.chunking

    def _chunking_runs(self) -> tuple[ChunkingConfig, ...]:
        """Every run, in order; a config built by hand may set only ``chunking``."""
        first = self._chunking()
        return self.config.chunking_runs or (first,)

    def chunk_output_dir(self, output_dir: Path | str | None = None) -> Path:
        """Where [`chunk`][opm.project.Project.chunk] writes: *output_dir*, else ``[chunking] output_dir``, below [`root`][opm.project.Project.root]."""
        return self.root / (output_dir if output_dir is not None else self._chunking().output_dir)

    def chunk_modules(self, odd: Path | str | None = None) -> tuple[ResolvedTransform, ...]:
        """Compile the modules a chunk run uses: the main one, then one per fragment ODD.

        The main ODD is *odd*, else ``[chunking] odd``, else the packaged one.
        Fragments without an ODD of their own use the main module. For a
        ``[[chunking]]`` array this is the first run's set.

        Raises:
            ValueError: The config has no ``[chunking]`` section.
        """
        return self._run_modules(self._chunking(), odd)

    def _run_modules(
        self, chunking: ChunkingConfig, odd: Path | str | None = None,
    ) -> tuple[ResolvedTransform, ...]:
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
        source: Path | str | None = None,
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
        on_step: Callable[[str], None] | None = None,
        pages: bool | str | None = None,
    ) -> ChunkRun:
        """Split *source* into pages, as ``opm chunk`` does.

        *source* is one XML file, a directory of them, or a glob pattern
        (``data/**/*.xml``). For a directory
        or a pattern, each document goes to a subdirectory named after it, and
        an HTML run also writes ``index.html`` listing the documents.

        A ``[[chunking]]`` run with an ``input`` of its own reads those files
        instead of *source*, and names their directories with its own
        ``document_name``; the runs without one process *source* together
        (see [`chunk_inputs`][opm.project.chunk_inputs]). ``pb-view`` output
        puts every document's data under ``<doc_path>/<name>.xml/`` instead.

        The arguments override the ``[chunking]`` settings of the same name.

        For HTML output, the auxiliary pages declared in ``[[pages]]`` are
        rendered into the same output root after the chunking runs, unless
        *pages* is ``False``; a *pages* string limits the build to pages whose
        ``path`` starts with it (``--page``). Non-HTML formats skip pages:
        they feed external site generators, which build their own.

        Once every page and the index are written, the ``after_chunking``
        hooks of the project's profiles run, each called with the project and
        the returned [`ChunkRun`][opm.project.ChunkRun].

        Args:
            source: An XML file, a directory of XML files (not searched
                recursively), or a glob pattern, where ``**`` matches any
                number of subdirectories. Read by the runs without an ``input``.
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
                document is processed, and with the entries of a data page
                as it is rendered.
            on_step: Called with a short label when a step after the
                chunking starts: the auxiliary pages, the collection index
                and each ``after_chunking`` hook.
            pages: ``False`` skips the ``[[pages]]`` auxiliary pages; a
                string builds only pages whose ``path`` starts with it;
                ``None`` (default) builds them all. HTML output only.

        Raises:
            ValueError: The config has no ``[chunking]`` section, *format* is
                unknown, a run has neither an ``input`` nor a *source*, a
                directory contains no XML files, a pattern matches no file, or
                two documents would be written to the same subdirectory.
            FileExistsError: The output directory exists and *overwrite*
                does not allow replacing it.
        """
        if format not in CHUNK_FORMATS:
            raise ValueError(f'format must be "html", "json" or "pb-view", got {format!r}')
        # Read before compiling anything, so a missing input fails fast.
        inputs = chunk_inputs(self._chunking_runs(), source)

        overrides: dict[str, Any] = {}
        if output_dir is not None:
            overrides['output_dir'] = str(output_dir)
        if template is not None:
            overrides['template'] = Path(template)
        if depth is not None:
            overrides['depth'] = depth
        if odd is not None:
            overrides['odd'] = Path(odd)

        # One or several runs ([[chunking]]), each with its modules compiled
        # and the call's overrides applied. They share the output directory.
        runs: list[ChunkingConfig] = []
        all_modules: list[ResolvedTransform] = []
        for run in self._chunking_runs():
            modules = self._run_modules(run, odd)
            all_modules.extend(modules)
            changes: dict[str, Any] = {'module': modules[0].module_path, **overrides}
            if run.fragments:
                compiled = iter(modules[1:])
                changes['fragments'] = [
                    replace(fragment, module=next(compiled).module_path if fragment.odd else None)
                    for fragment in run.fragments
                ]
            runs.append(replace(run, **changes))
        chunking = runs[0]

        # The same grouping, now over the compiled runs.
        position = {id(run): index for index, run in enumerate(self._chunking_runs())}
        groups: list[tuple[list[ChunkingConfig], list[Path]]] = [
            ([runs[position[id(run)]] for run in item.runs], list(item.files)) for item in inputs
        ]
        # A file read by several runs is listed once.
        all_files = list(dict.fromkeys(
            xml_file for _, group_files in groups for xml_file in group_files
        ))

        out_dir = self.chunk_output_dir(chunking.output_dir)
        _clear_output_dir(out_dir, overwrite)

        enabled = (
            True if format in ('json', 'pb-view')
            else webcomponents if webcomponents is not None
            else bool(self.config.webcomponents_enabled)
        )
        extensions = tuple(xpath_extensions) if xpath_extensions else None
        base_doc_path = doc_path or chunking.doc_path
        # What each document's directory is called: its file name, or the
        # document_name of the run that reads it. pb-view data stays
        # addressed by file.
        group_names = [
            document_names(
                group_files,
                None if format == 'pb-view' else group_runs[0].document_name,
                self.config,
                extensions=extensions,
            )
            for group_runs, group_files in groups
        ]
        _check_document_dirs(
            (xml_file, name) for names_of_group in group_names
            for xml_file, name in names_of_group.items()
        )
        # Each file's first directory, for what is keyed by file.
        doc_names: dict[Path, str] = {}
        for names_of_group in group_names:
            for xml_file, name in names_of_group.items():
                doc_names.setdefault(xml_file, name)
        # Built once and shared: templates test links against it.
        names = frozenset(
            name for names_of_group in group_names for name in names_of_group.values()
        )

        # Each document directory's anchor map, kept so the auxiliary pages
        # can link into the reading view: id → the directory + chunk file.
        anchors_by_dir: dict[str, dict[str, str]] = {}

        documents = [
            (group_runs, xml_file, names_of_group[xml_file])
            for (group_runs, group_files), names_of_group in zip(groups, group_names)
            for xml_file in group_files
        ]
        multi_document = len(inputs) > 1 or is_multi_document(inputs[0].source)
        for position, (group_runs, xml_file, doc_name) in enumerate(documents):
            if on_document is not None:
                on_document(position, xml_file)
            if multi_document and format == 'pb-view':
                document_doc_path = (
                    f'{base_doc_path.rstrip("/")}/{xml_file.name}' if base_doc_path
                    else xml_file.name
                )
            else:
                document_doc_path = base_doc_path

            # Each run of this document is handed the anchors of the runs
            # before it, so links between their pages resolve.
            anchors: dict[str, str] = {}
            written = 0
            for index, run in enumerate(group_runs):
                progress = on_progress
                if on_progress is not None and written:
                    # One count per document across its runs.
                    def progress(done: int, total: int, _base: int = written) -> None:
                        on_progress(_base + done, _base + total)
                anchors = chunk_document(
                    module_path=run.module,
                    xml_path=xml_file,
                    config=_document_config(run, xml_file, format, doc_name),
                    project=self,
                    template_path=run.template,
                    on_progress=progress,
                    webcomponents=(
                        enabled if format in ('json', 'pb-view') or webcomponents is not None
                        or run.webcomponents is None else run.webcomponents
                    ),
                    xpath_extensions=extensions,
                    output_format=format,
                    doc_path=document_doc_path,
                    documents=names,
                    anchors=anchors,
                    merge_manifest=index > 0,
                ) or {}  # a wrapped or stubbed chunk_document may still return None
                written = len(set(anchors.values()))
            anchors_by_dir[doc_name] = anchors

        # Auxiliary pages ([[pages]]): rendered after the runs, into the same
        # output root. They receive every document's anchors (prefixed with
        # the document's directory) so they can link into the reading view.
        page_results: list = []
        if format == 'html' and pages is not False:
            from opm.pages import render_pages

            # An id found in several directories (a file read by two runs)
            # links to the first run's page.
            page_anchors: dict[str, str] = {}
            for doc_name, doc_anchors in anchors_by_dir.items():
                for xml_id, chunk_file in doc_anchors.items():
                    page_anchors.setdefault(xml_id, f'{doc_name}/{chunk_file}')
            from opm.chunking import collect_index_entries

            # The documents just chunked, for pages that list or search them
            # (a register entry's "mentioned in"): source file and first page.
            first_pages = {entry.name: entry.href for entry in collect_index_entries(out_dir)}
            site_documents = [
                {
                    'name': doc_name,
                    'path': str(xml_file.resolve()),
                    'href': first_pages[doc_name],
                }
                for _, xml_file, doc_name in documents
                if doc_name in first_pages
            ]
            if on_step is not None and self.config.pages:
                on_step('Building pages')
            page_results = render_pages(
                self,
                out_dir=out_dir,
                run=chunking,
                webcomponents=enabled,
                xpath_extensions=extensions,
                anchors=page_anchors,
                documents=site_documents,
                only=pages if isinstance(pages, str) else None,
                on_progress=on_progress,
            )
        page_files = tuple(file for result in page_results for file in result.files)

        # Every HTML run leaves one subdirectory per document, which a web
        # server would otherwise show as a bare listing. A [[pages]] entry
        # with path "index.html" is the project's own landing page: it was
        # just written and takes the place of the generated index.
        index_file: Path | None = None
        own_index = out_dir / 'index.html'
        if own_index in page_files:
            index_file = own_index
        elif format == 'html':
            if on_step is not None:
                on_step('Writing index')
            index_file = build_index(
                out_dir,
                template_path=chunking.index_template,
                title=chunking.index_title or _source_label(inputs[0].source),
                module_path=chunking.module,
                project_config=self.config,
                project_root=self.root,
                chunking_config=chunking,
                webcomponents=enabled,
                project=self,
            )
        run_result = ChunkRun(
            output_dir=out_dir,
            documents=tuple(all_files),
            format=format,
            modules=tuple(all_modules),
            index_file=index_file,
            document_dirs=dict(doc_names),
            pages=page_files,
        )
        self._run_hooks('after_chunking', run_result, on_step=on_step)
        return run_result

    def _run_hooks(
        self, name: str, *args: Any, on_step: Callable[[str], None] | None = None
    ) -> None:
        """Call the *name* hooks of every profile, in the order the profiles are listed.

        *on_step*, if given, is told each hook's profile before it runs.
        """
        from opm.profile import load_hook

        for profile_config, profile_path in self._profiles:
            for entry in profile_config.hooks.get(name, ()):
                if on_step is not None:
                    on_step(f'Running {profile_config.name}')
                load_hook(profile_config.name, profile_path, entry)(self, *args)

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
        """Measure the ODD against *sources*, as ``opm odd coverage`` does.

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


def _merge_page(own: PageConfig, profile: PageConfig) -> PageConfig:
    """A project's ``[[pages]]`` entry laid over the profile's entry for the same path.

    Every key the project sets wins; the others come from the profile.
    ``context`` is merged key by key, so ``context = { page_title = "Orte" }``
    alone relabels the profile's page and keeps its template, selection,
    parameters and the rest of its context. ``enabled`` is the project's. The
    page stays a profile page (a missing ``source`` skips it) unless the
    project names its own ``source``, which must then exist.
    """
    merged = {
        f.name: getattr(own, f.name) if getattr(own, f.name) is not None else getattr(profile, f.name)
        for f in fields(PageConfig)
        if f.name not in ('path', 'enabled', 'from_profile')
    }
    if own.context is not None and profile.context is not None:
        merged['context'] = merge_deep(profile.context, own.context)
    return PageConfig(
        path=own.path,
        enabled=own.enabled,
        from_profile=own.source is None,
        **merged,
    )
