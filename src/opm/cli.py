"""Unified CLI: ``opm init``, ``opm transform``, ``opm chunk``, and ``opm serve``.

ODDs are compiled on demand into the user cache (``platformdirs``); there is no
separate ``compile`` command.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Optional, TYPE_CHECKING

import typer
from typer.main import get_command

if TYPE_CHECKING:  # rich is imported lazily: it costs ~30ms of startup
    from rich.progress import Progress

try:
    from typer._click.exceptions import NoArgsIsHelpError, UsageError
except ImportError:  # typer < 0.27 still depends on the click package
    from click.exceptions import NoArgsIsHelpError, UsageError

from lxml import etree

from opm.config import (
    ChunkingConfig,
    FragmentConfig,
    ProjectConfig,
    load_project_config,
    resolve_base_css,
)
from opm.odd_cache import ResolvedTransform, resolve_transform_module
from opm.resources import packaged_default_css, packaged_default_docx
from opm.scaffold import InitOptions, ScaffoldError, VOCABULARIES, scaffold
from opm.runtime.pm_runtime import resolve_context_element
from opm.transform import (
    load_transform_module,
    load_xpath_collections,
    load_xpath_documents,
    run_transform,
)
from opm.runtime.pm_runtime import xpath_runtime_context
from opm.chunking import build_index, chunk_document

app = typer.Typer(
    name='opm',
    help=(
        'Open Processing Model: transform XML via ODD processing models '
        '(ODDs compile on demand into the user cache).'
    ),
    no_args_is_help=True,
    context_settings={'help_option_names': ['-h', '--help']},
)


@app.command('init')
def init_cmd(
    directory: Annotated[
        Path,
        typer.Argument(help='Project directory (default: current directory).'),
    ] = Path('.'),
    force: Annotated[
        bool,
        typer.Option('--force', help='Overwrite existing generated files.'),
    ] = False,
    vocabulary: Annotated[
        str,
        typer.Option(
            '--vocabulary',
            help=f'Source vocabulary: {", ".join(VOCABULARIES)} (default: tei).',
        ),
    ] = 'tei',
    no_sample: Annotated[
        bool,
        typer.Option('--no-sample', help='Do not copy a sample XML document.'),
    ] = False,
    copy_base_odd: Annotated[
        bool,
        typer.Option(
            '--copy-base-odd',
            help='TEI only: also copy packaged teipublisher.odd and tp.css into odd/.',
        ),
    ] = False,
    title: Annotated[
        Optional[str],
        typer.Option('--title', help='Edition title used in README (default: directory name).'),
    ] = None,
) -> None:
    """Create a local project (config, templates, ODD) from packaged defaults."""
    vocab = vocabulary.strip().lower()
    if copy_base_odd and vocab != 'tei':
        typer.echo(
            f'opm: note: --copy-base-odd is TEI-only; {vocab} already copies its own ODD.',
            err=True,
        )
    try:
        result = scaffold(
            InitOptions(
                directory=directory,
                force=force,
                title=title,
                vocabulary=vocab,
                copy_base_odd=copy_base_odd and vocab == 'tei',
                include_sample=not no_sample,
            )
        )
    except ScaffoldError as e:
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e

    typer.echo(f'Created project in {result.directory}')
    for path in result.written:
        try:
            rel = path.relative_to(result.directory)
        except ValueError:
            rel = path
        typer.echo(f'  {rel}')
    if result.skipped:
        typer.echo(
            'Skipped existing files (pass --force to overwrite; '
            'AGENTS.md / CLAUDE.md are never overwritten):',
            err=True,
        )
        for path in result.skipped:
            try:
                rel = path.relative_to(result.directory)
            except ValueError:
                rel = path
            typer.echo(f'  {rel}', err=True)

    sample = 'data/sample.xml' if result.include_sample else 'your.xml'
    typer.echo('')
    typer.echo('Next:')
    typer.echo(f'  opm transform {sample} --preview')
    typer.echo(f'  opm chunk {sample} --force --preview')


def _preview_kind_from_module(mod) -> str:
    """Return ``'html'``, ``'markdown'``, ``'docx'``, ``'epub'``, or ``'text'`` based on output channels."""
    raw = mod.transform_output_channels()
    if not raw:
        return 'text'
    primary = raw[0] if isinstance(raw, (list, tuple)) else raw
    if primary == 'markdown':
        return 'markdown'
    if primary in ('web', 'print'):
        return 'html'
    if primary == 'docx':
        return 'docx'
    if primary == 'epub':
        return 'epub'
    if primary == 'typst':
        return 'typst'
    return 'text'


def _preview_html_in_browser(html: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        suffix='.html',
        delete=False,
        prefix='opm-preview-',
    ) as f:
        f.write(html)
        path = Path(f.name)
    webbrowser.open(path.as_uri())


def _preview_file_with_default_app(data: bytes, suffix: str, label: str) -> bool:
    """Write *data* to a temp file and open it in the platform's default app.

    Used for formats that cannot be rendered in a terminal or browser (docx,
    epub).  Returns ``False`` when no handler could be launched, so the caller
    can fall back to telling the user to pass ``--output``.
    """
    import click  # noqa: PLC0415

    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False,
        prefix='opm-preview-',
    ) as f:
        f.write(data)
        path = Path(f.name)
    try:
        if click.launch(str(path)) != 0:
            return False
    except OSError:
        return False
    typer.echo(f'Opened {label} preview: {path}', err=True)
    return True


def _preview_markdown_terminal(md: str) -> None:
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    # Rich's pager keeps ANSI styles (bold/italic) when handing off to the system pager
    # (e.g. less). Piping plain output to `less` drops a TTY and strips styling unless
    # FORCE_COLOR is set; using pager(styles=True) avoids that for interactive preview.
    if sys.stdout.isatty():
        with console.pager(styles=True):
            console.print(Markdown(md))
    else:
        console.print(Markdown(md))


def _preview_plain_terminal(text: str) -> None:
    from rich.console import Console

    Console().print(text)


def _parameters_from_cli(param_list: list[str] | None) -> dict[str, str]:
    """Parse ``KEY=VALUE`` strings into a parameters dict (XPath ``$parameters``)."""
    if not param_list:
        return {}
    out: dict[str, str] = {}
    for raw in param_list:
        if '=' not in raw:
            raise ValueError(f'--param must be KEY=VALUE, got {raw!r}')
        key, _, value = raw.partition('=')
        key = key.strip()
        if not key:
            raise ValueError(f'--param must be KEY=VALUE, got {raw!r}')
        out[key] = value
    return out


def _report_resolved_module(resolved: ResolvedTransform) -> None:
    """Print the cache path when the module was produced from an ODD."""
    if resolved.source_odd is None:
        return
    styled = typer.style(str(resolved.module_path), fg=typer.colors.GREEN, bold=True)
    if resolved.freshly_compiled:
        typer.echo(f'Compiled {resolved.source_odd} → {styled}', err=True)
    else:
        typer.echo(f'Cached module: {styled}', err=True)


def _resolve_cli_transform(
    *,
    cfg: ProjectConfig,
    odd: Path | None,
    transform_type: str | None,
    base_css: str | None = None,
) -> ResolvedTransform:
    """Resolve ``--odd`` / config odd / packaged default for transform."""
    mode = (transform_type or 'web').strip().lower() or 'web'

    if odd is not None:
        return resolve_transform_module(odd=odd, output_mode=mode, base_css=base_css)

    cfg_odd = cfg.odd_for_type(mode)
    if cfg_odd is not None:
        return resolve_transform_module(odd=cfg_odd, output_mode=mode, base_css=base_css)

    return resolve_transform_module(output_mode=mode, base_css=base_css)


def _materialize_chunking_modules(
    config: ChunkingConfig,
    base_css: str | None = None,
) -> tuple[ChunkingConfig, list[ResolvedTransform]]:
    """Compile ``odd`` entries on *config* into runtime ``module`` paths."""
    reported: list[ResolvedTransform] = []

    main = resolve_transform_module(
        odd=config.odd,
        output_mode='web',
        use_packaged_default=config.odd is None,
        base_css=base_css,
    )
    reported.append(main)

    new_fragments: list[FragmentConfig] | None = None
    if config.fragments:
        new_fragments = []
        for frag in config.fragments:
            if frag.odd is None:
                new_fragments.append(replace(frag, module=None))
                continue
            resolved = resolve_transform_module(
                odd=frag.odd,
                output_mode=frag.mode,
                use_packaged_default=False,
                base_css=base_css,
            )
            reported.append(resolved)
            new_fragments.append(replace(frag, module=resolved.module_path))

    return (
        replace(config, module=main.module_path, odd=config.odd, fragments=new_fragments),
        reported,
    )


def _chunk_input_files(input_path: Path) -> list[Path]:
    """Return XML files to process for ``opm chunk``."""
    if input_path.is_dir():
        return sorted(path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == '.xml')
    return [input_path]


def _append_doc_path(base_doc_path: str | None, xml_path: Path) -> str:
    """Append the XML filename to a configured pb-view document path."""
    if not base_doc_path:
        return xml_path.name
    return f'{base_doc_path.rstrip("/")}/{xml_path.name}'


def _chunk_progress() -> Progress:
    """Progress display for ``opm chunk``: description, bar, count, ETA.

    Disabled whenever stdout is not a terminal. The bar is decoration, never
    output — a piped or redirected run must see only what the command echoes,
    and rich would otherwise print one final frame when the display stops.
    """
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
    )

    console = Console()
    return Progress(
        TextColumn('{task.description}'),
        BarColumn(complete_style='cyan', finished_style='cyan'),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        disable=not console.is_terminal,
    )


def _append_output_dir(base_output_dir: str, xml_path: Path) -> str:
    """Append the XML filename to the chunk output directory."""
    return f'{base_output_dir.rstrip("/")}/{xml_path.name}'


def _prepare_chunk_output_dir(out_dir: Path, *, force: bool) -> None:
    """Remove *out_dir* if it already exists.

    With ``--force``, the directory (or file) is deleted immediately. Otherwise
    an interactive terminal is prompted; non-interactive runs error so scripts
    must pass ``--force``.
    """
    if not out_dir.exists():
        return
    if not force:
        prompt = f'Output directory {out_dir} already exists. Remove it and continue?'
        if sys.stdin.isatty():
            if not typer.confirm(prompt, default=False):
                raise SystemExit(1)
        else:
            typer.echo(
                f'opm: error: output directory {out_dir} already exists. '
                'Use --force to replace it.',
                err=True,
            )
            raise SystemExit(1)
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
    else:
        out_dir.unlink()


@app.command('transform')
def transform_cmd(
    input_xml: Annotated[Optional[Path], typer.Argument(help='Input XML file')] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help=(
                'ODD file to compile on demand into the user cache. '
                'Overrides transform.<type>.odd in config.'
            ),
        ),
    ] = None,
    transform_type: Annotated[
        Optional[str],
        typer.Option(
            '--type',
            '-t',
            metavar='TYPE',
            help=(
                'Transform type / ODD output channel (web, docx, typst, markdown, …). '
                'Selects transform.<type>.odd from config when --odd '
                'is omitted; also sets the compile mode for --odd.'
            ),
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            '--output',
            '-o',
            help='Write transform output to this file (default: stdout unless --preview)',
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help=(
                'Preview output: channel web/print → browser, markdown → Rich (paged in a TTY so '
                'bold/italic survive), docx/epub → the platform default application; other '
                'channels (e.g. typst) → plain text in the terminal.'
            ),
        ),
    ] = False,
    param: Annotated[
        list[str],
        typer.Option(
            '--param',
            '-p',
            metavar='KEY=VALUE',
            help='Runtime parameter for XPath $parameters (repeatable), e.g. -p mode=toc -p display=browse',
        ),
    ] = [],
    css: Annotated[
        Optional[Path],
        typer.Option(
            '--css',
            help='Optional external CSS file injected into <head> for full-document HTML output.',
        ),
    ] = None,
    template: Annotated[
        Optional[Path],
        typer.Option(
            '--template',
            help='Template path: Jinja2 for HTML/print/Typst output, or .docx for DOCX output.',
        ),
    ] = None,
    xpath: Annotated[
        Optional[str],
        typer.Option(
            '--xpath',
            '-x',
            metavar='EXPR',
            help=(
                'XPath 3.1 expression evaluated with the document root as the context item; '
                'the single selected element becomes the transform root. Unprefixed names use '
                'the same default element namespace as the document root. $parameters is bound '
                'from --param.'
            ),
        ),
    ] = None,
    xpath_extensions: Annotated[
        Optional[list[str]],
        typer.Option(
            '--xpath-extensions',
            help=(
                'Dotted import path(s) of Python module(s) whose public callables become XPath '
                'functions in the tp: namespace (repeat option to add modules; e.g. '
                '--xpath-extensions extensions.common --xpath-extensions extensions.dates). '
                'Importing these modules runs top-level code: only use trusted code.'
            ),
        ),
    ] = None,
    webcomponents: Annotated[
        Optional[bool],
        typer.Option(
            '--webcomponents/--no-webcomponents',
            help=(
                'Enable/disable tei-publisher web components mode: alternate behaviours emit '
                '<pb-alternate> and the document template loads tei-publisher-components. '
                'Falls back to transform.web.webcomponents.enabled in the project config.'
            ),
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Transform an XML document via an ODD with processing instructions and return the result (HTML, markdown, …)."""
    try:
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        if input_xml is None:
            typer.echo('opm: error: input XML file is required.', err=True)
            raise SystemExit(1)

        # --css / [document] css replaces the packaged base rules, which are
        # compiled into the ODD stylesheet — so it has to be known before the
        # ODD is compiled, and it is part of the cache key.
        # NB: cwd is the root only for the bare styles/default-styles.css
        # fallback; a configured path is already absolute by this point.
        effective_css = css if css is not None else cfg.document_css
        resolved = _resolve_cli_transform(
            cfg=cfg,
            odd=odd,
            transform_type=transform_type,
            base_css=resolve_base_css(effective_css, Path.cwd()),
        )
        _report_resolved_module(resolved)
        effective_script = resolved.module_path

        effective_webcomponents = webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False)
        mod = load_transform_module(effective_script)
        channels = mod.transform_output_channels()
        primary = channels[0] if channels else ''
        if isinstance(channels, (list, tuple)) and channels:
            primary = channels[0]
        elif not isinstance(channels, (list, tuple)):
            primary = channels

        # Print / EPUB have no interactive UI — never load web components.
        if primary in ('print', 'epub'):
            effective_webcomponents = False

        if primary == 'typst':
            effective_template = template if template is not None else cfg.typst_template
            effective_docx_template = None
        elif primary == 'docx':
            effective_template = None
            effective_docx_template = template if template is not None else cfg.document_docx_template
            if effective_docx_template is None:
                effective_docx_template = packaged_default_docx()
        elif primary == 'print':
            # Do not fall back to the web/document shell (nav, web components).
            effective_template = template if template is not None else cfg.print_template
            effective_docx_template = None
        elif primary == 'epub':
            effective_template = None
            effective_docx_template = None
        else:
            effective_template = template if template is not None else cfg.document_template
            effective_docx_template = None
        effective_extensions: tuple[str, ...] = (
            tuple(xpath_extensions) if xpath_extensions else cfg.xpath_extensions
        )

        # Config parameters seed $parameters; CLI -p overrides them.
        parameters = dict(cfg.parameters)
        parameters.update(_parameters_from_cli(param if param else None))
        # Add input_path to parameters for image processing in DOCX output
        parameters['input_path'] = str(input_xml)
        xpath_base_uri = input_xml.resolve().as_uri()
        xpath_documents = load_xpath_documents(cfg.xpath_documents)
        xpath_collections, xpath_documents = load_xpath_collections(
            cfg.xpath_collections, xpath_documents,
        )
        parameters.update(
            xpath_runtime_context(
                base_uri=xpath_base_uri,
                documents=xpath_documents,
                collections=xpath_collections,
                variables=dict(cfg.xpath_variables),
                namespaces=dict(cfg.xpath_namespaces),
            ),
        )

        tree = etree.parse(str(input_xml))
        doc_root = tree.getroot()
        root = (
            resolve_context_element(
                doc_root,
                xpath,
                parameters or None,
                xpath_extensions=effective_extensions,
            )
            if xpath
            else doc_root
        )

        template_context = cfg.context_for(
            primary, webcomponents=effective_webcomponents,
        )

        out = run_transform(
            mod,
            root,
            parameters=parameters,
            xpath_extensions=effective_extensions,
            webcomponents=effective_webcomponents,
            template_path=effective_template,
            template_context=template_context,
            docx_template=effective_docx_template,
            typst_template_path=effective_template if primary == 'typst' else None,
            xpath_base_uri=xpath_base_uri,
            xpath_documents=xpath_documents,
            epub_chunking=cfg.epub_chunking,
            epub_css=cfg.epub_css,
            epub_skip_title=cfg.epub_skip_title,
        )

        if isinstance(out, bytes):
            if output:
                output.write_bytes(out)
            elif preview:
                kind = _preview_kind_from_module(mod)
                label = 'EPUB' if kind == 'epub' else 'DOCX'
                ext = '.epub' if kind == 'epub' else '.docx'
                if not _preview_file_with_default_app(out, ext, label):
                    typer.echo(
                        f'{label} output cannot be previewed in the terminal and no '
                        f'application is registered for {ext} files. '
                        f'Use --output to write a {ext} file.',
                    )
            else:
                sys.stdout.buffer.write(out)
        else:
            if output:
                output.write_text(out, encoding='utf-8')
            elif preview:
                kind = _preview_kind_from_module(mod)
                if kind == 'html':
                    _preview_html_in_browser(out)
                elif kind == 'markdown':
                    _preview_markdown_terminal(out)
                elif kind == 'typst':
                    _preview_plain_terminal(out)
                else:
                    _preview_plain_terminal(out)
            else:
                print(out)
    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e


@app.command()
def chunk(
    input_xml: Annotated[
        Optional[Path],
        typer.Argument(
            help='XML file to transform and chunk, or a directory of XML files.',
        ),
    ] = None,
    odd: Annotated[
        Optional[Path],
        typer.Option(
            '--odd',
            '-d',
            help='ODD file to compile on demand for chunking (overrides chunking.odd in config).',
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            '--output-dir',
            '-o',
            help='Directory to write chunked files (overrides chunking.output_dir in config).',
        ),
    ] = None,
    template: Annotated[
        Optional[Path],
        typer.Option(
            '--template',
            '-t',
            exists=True,
            dir_okay=False,
            help='Jinja2 template for chunk pages (overrides chunking.template in config).',
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            '--force',
            '-f',
            help='Remove the existing output directory without prompting.',
        ),
    ] = False,
    depth: Annotated[
        Optional[int],
        typer.Option(
            '--depth',
            help='Maximum division/section depth for chunk splitting (overrides chunking.depth in config).',
        ),
    ] = None,
    webcomponents: Annotated[
        Optional[bool],
        typer.Option(
            '--webcomponents/--no-webcomponents',
            help=(
                'Enable/disable tei-publisher web components mode. '
                'Falls back to transform.web.webcomponents.enabled in the project config.'
            ),
        ),
    ] = None,
    xpath_extensions: Annotated[
        Optional[list[str]],
        typer.Option(
            '--xpath-extensions',
            help=(
                'Dotted import path(s) of Python module(s) whose public callables become XPath '
                'functions in the tp: namespace (repeatable). '
                'Falls back to transform.xpath_extensions in opm.toml.'
            ),
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            '--format',
            help=(
                'Output format for chunk files: "html" (default, rendered via Jinja2 template), '
                '"json" (one JSON file per chunk containing content, head, odd_css, and '
                'fragments — suitable for static site generators such as Eleventy), or '
                '"pb-view" (index.json lookup table plus one part file per chunk, consumable '
                'by the dynamic pb-view web component in static mode).'
            ),
        ),
    ] = 'html',
    doc_path: Annotated[
        Optional[str],
        typer.Option(
            '--doc-path',
            help=(
                'For --format pb-view: document path subdirectory. Data is written to '
                '<output-dir>/<doc-path>/ and must match the pb-document @path; CSS stays '
                'shared at <output-dir>/css/. Falls back to chunking.doc_path in config.'
            ),
        ),
    ] = None,
    preview: Annotated[
        bool,
        typer.Option(
            '--preview',
            '-v',
            help='After chunking, start a local HTTP server rooted at the output directory.',
        ),
    ] = False,
    port: Annotated[
        int,
        typer.Option(
            '--port',
            '-p',
            help='Port for --preview (default: 8080).',
        ),
    ] = 8080,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Chunk a large XML document into smaller HTML pages or JSON data files."""
    try:
        cfg = load_project_config(config)
        for p in cfg.pythonpath:
            entry = str(p.resolve())
            if entry not in sys.path:
                sys.path.insert(0, entry)

        if input_xml is None:
            typer.echo('opm: error: input XML file is required.', err=True)
            raise SystemExit(1)

        if not cfg.chunking:
            typer.echo(
                'opm: error: no [chunking] section found in config.',
                err=True
            )
            raise SystemExit(1)
        
        # Override config with CLI options
        chunking_config = cfg.chunking
        if output_dir:
            chunking_config.output_dir = str(output_dir)
        if template:
            chunking_config.template = template
        if depth is not None:
            chunking_config = replace(chunking_config, depth=depth)
        if odd is not None:
            chunking_config = replace(chunking_config, module=None, odd=odd)

        chunking_config, resolved_list = _materialize_chunking_modules(
            chunking_config, base_css=resolve_base_css(cfg.document_css, Path.cwd())
        )
        for resolved in resolved_list:
            _report_resolved_module(resolved)

        if output_format not in ('html', 'json', 'pb-view'):
            typer.echo(
                'opm: error: --format must be "html", "json" or "pb-view", '
                f'got {output_format!r}',
                err=True,
            )
            raise SystemExit(1)

        input_files = _chunk_input_files(input_xml)
        if input_xml.is_dir():
            if not input_files:
                typer.echo(
                    f'opm: error: no XML files found in directory {input_xml}.',
                    err=True,
                )
                raise SystemExit(1)

        out_dir = Path.cwd() / chunking_config.output_dir
        _prepare_chunk_output_dir(out_dir, force=force)
        
        # Config templates are already resolved relative to the config file;
        # a --template CLI path is relative to the current working directory.
        effective_template = chunking_config.template
        
        effective_webcomponents = (
            True if output_format in ('json', 'pb-view')
            else (webcomponents if webcomponents is not None else (cfg.webcomponents_enabled or False))
        )
        effective_extensions: tuple[str, ...] | None = (
            tuple(xpath_extensions) if xpath_extensions else None
        )

        # Chunk the document(s)
        effective_chunk_script = chunking_config.module
        if input_xml.is_dir():
            typer.echo(
                f'Chunking {len(input_files)} XML files from {input_xml} '
                f'using {effective_chunk_script or "module from config"}...'
            )
        else:
            typer.echo(f'Chunking {input_xml} using {effective_chunk_script or "module from config"}...')
        # ``on_progress`` counts chunks *within one document*, so a directory run
        # gets a second task counting files — one bar per unit, rather than
        # trading chunk-level detail for a file count.
        per_file = len(input_files) > 1
        with _chunk_progress() as progress:
            file_task = (
                progress.add_task('Files', total=len(input_files)) if per_file else None
            )
            # Total arrives with the first callback: only the chunker knows how
            # many chunks a document splits into. Until then the bar pulses.
            chunk_task = progress.add_task('Processing chunks', total=None)

            def _on_progress(current: int, total: int) -> None:
                progress.update(chunk_task, completed=current, total=total)

            base_doc_path = doc_path or chunking_config.doc_path

            for xml_file in input_files:
                if per_file:
                    # `update` cannot clear a total, so the next document's first
                    # callback replaces it; zero the count so the bar restarts.
                    progress.update(
                        chunk_task, completed=0, description=f'Chunking {xml_file.name}'
                    )
                if input_xml.is_dir() and output_format != 'pb-view':
                    effective_chunking_config = replace(
                        chunking_config,
                        output_dir=_append_output_dir(chunking_config.output_dir, xml_file),
                        link_doc=xml_file.name,
                    )
                else:
                    # Single-file output into …/<name>.xml/ should still expand {doc}.
                    out = Path(chunking_config.output_dir)
                    effective_chunking_config = (
                        replace(chunking_config, link_doc=xml_file.name)
                        if out.name == xml_file.name
                        else chunking_config
                    )
                effective_doc_path = (
                    _append_doc_path(base_doc_path, xml_file)
                    if input_xml.is_dir() and output_format == 'pb-view'
                    else base_doc_path
                )

                chunk_document(
                    module_path=chunking_config.module,
                    xml_path=xml_file,
                    config=effective_chunking_config,
                    project_root=Path.cwd(),
                    template_path=effective_template,
                    on_progress=_on_progress,
                    project_config=cfg,
                    webcomponents=effective_webcomponents,
                    xpath_extensions=effective_extensions,
                    output_format=output_format,
                    doc_path=effective_doc_path,
                )
                if file_task is not None:
                    progress.advance(file_task)

        # A directory run leaves one subdirectory per document, which the dev
        # server would otherwise show as a bare listing. Writing index.html is
        # enough: http.server prefers it over list_directory().
        index_file: Path | None = None
        if input_xml.is_dir() and output_format == 'html':
            index_file = build_index(
                out_dir,
                template_path=chunking_config.index_template,
                title=chunking_config.index_title or input_xml.name,
                module_path=chunking_config.module,
                project_config=cfg,
                project_root=Path.cwd(),
                chunking_config=chunking_config,
            )

        typer.echo(f'Chunks written to {out_dir}/')
        if output_format == 'pb-view':
            if input_xml.is_dir():
                data_subdir = f'{(doc_path or chunking_config.doc_path or "").rstrip("/")}/<document>.xml/'
                if data_subdir.startswith('/'):
                    data_subdir = data_subdir[1:]
            else:
                effective_doc_path = doc_path or chunking_config.doc_path
                data_subdir = f'{effective_doc_path}/' if effective_doc_path else ''
            typer.echo(f'  - {data_subdir}index.json: pb-view lookup table')
            typer.echo(f'  - {data_subdir}<xml:id>.json: part files')
            resolved_module = chunking_config.module
            odd_name = getattr(load_transform_module(resolved_module), 'ODD_NAME', '') if resolved_module else ''
            typer.echo(f'  - css/{odd_name}.css: ODD stylesheet')
        else:
            ext = 'json' if output_format == 'json' else 'html'
            if input_xml.is_dir():
                typer.echo('  - <document>.xml/manifest.json: metadata for page navigation and linking')
                typer.echo(f'  - <document>.xml/*.{ext}: chunk files')
                if index_file is not None:
                    typer.echo('  - index.html: collection index served at the site root')
            else:
                typer.echo('  - manifest.json: metadata for page navigation and linking')
                typer.echo(f'  - *.{ext}: chunk files')

        if preview:
            _serve_directory(out_dir, port)

    except (FileNotFoundError, ImportError, AttributeError, OSError, ValueError) as e:
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e


_SERVE_PORT_TRIES = 20


def _bind_http_server(handler: Any, port: int, tries: int = _SERVE_PORT_TRIES):
    """Bind an HTTP server, skipping ports that are already in use.

    Returns ``(httpd, bound_port)``. Raises the last ``OSError`` if every
    candidate from *port* through *port + tries - 1* fails.
    """
    import errno
    import http.server

    last_error: OSError | None = None
    for candidate in range(port, port + max(1, tries)):
        try:
            httpd = http.server.HTTPServer(('', candidate), handler)
            bound = httpd.socket.getsockname()[1]
            return httpd, bound
        except OSError as e:
            last_error = e
            if e.errno != errno.EADDRINUSE:
                raise
    assert last_error is not None
    raise last_error


def _serve_directory(root: Path, port: int) -> None:
    """Serve *root* over HTTP until interrupted (same behaviour as ``opm serve``)."""
    import errno
    import functools
    import http.server

    root = root.resolve()
    if not root.is_dir():
        typer.echo(f'opm: error: directory {root} does not exist.', err=True)
        raise SystemExit(1)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(root),
    )
    try:
        httpd, bound_port = _bind_http_server(handler, port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            typer.echo(
                f'opm: error: port {port} is already in use. '
                f'Try a different port with -p.',
                err=True,
            )
            raise SystemExit(1) from e
        typer.echo(f'opm: error: {e}', err=True)
        raise SystemExit(1) from e

    if bound_port != port:
        typer.echo(
            f'Port {port} is in use; serving on {bound_port} instead.',
            err=True,
        )
    with httpd:
        typer.echo(
            f'Serving {root} at ' + typer.style(
                f'http://localhost:{bound_port}/',
                fg=typer.colors.GREEN,
                bold=True,
            ) + ' — press Ctrl-C to stop.'
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


@app.command('serve')
def serve_cmd(
    port: Annotated[
        int,
        typer.Option('--port', '-p', help='Port to listen on (default: 8080).'),
    ] = 8080,
    directory: Annotated[
        Optional[Path],
        typer.Option(
            '--directory',
            '-d',
            help='Directory to serve (default: chunking.output_dir from config, or "chunks").',
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='Path to a TOML configuration file (default: opm.toml in the current directory).',
        ),
    ] = None,
) -> None:
    """Start a local HTTP server rooted at the chunks output directory."""
    cfg = load_project_config(config)
    if directory is not None:
        root = directory.resolve()
    elif cfg.chunking:
        root = (Path.cwd() / cfg.chunking.output_dir).resolve()
    else:
        root = (Path.cwd() / 'chunks').resolve()

    _serve_directory(root, port)


def main(argv: list[str] | None = None) -> int:
    """Programmatic entry (``argv`` is like ``sys.argv[1:]`` when invoking the installed script)."""
    cmd = get_command(app)
    try:
        cmd.main(args=argv, prog_name='opm', standalone_mode=False)
    except NoArgsIsHelpError:
        # With ``standalone_mode=False``, Click does not turn this into exit 0 (Typer ``no_args_is_help``).
        return 0
    except UsageError as e:
        # Missing required args, bad option values, etc. (``standalone_mode=False`` skips Click's handler).
        e.show()
        return e.exit_code
    except SystemExit as e:
        code = e.code
        if isinstance(code, int):
            return code
        return 1 if code else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
